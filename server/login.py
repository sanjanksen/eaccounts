"""
GT SSO + Duo 2FA login flow via HTTP requests.

Performs the full login chain:
  1. GET eAccounts → follows redirects to CAS login page
  2. POST credentials to CAS
  3. Interact with Duo frame API (trigger push, poll for approval)
  4. Follow SAML assertion back to eAccounts
  5. Return session cookies
"""

import json
import re
import time
import requests
from urllib.parse import urlparse, parse_qs, urlencode, urljoin
from bs4 import BeautifulSoup
from datetime import datetime


EACCOUNTS_URL = 'https://eacct-buzzcard-sp.transactcampus.com/buzzcard/AccountSummary.aspx'

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
}

# Max time to wait for Duo push approval (seconds)
DUO_POLL_TIMEOUT = 90
DUO_POLL_INTERVAL = 3


def log(msg):
    print(f'[{datetime.now()}] [login] {msg}', flush=True)


class LoginError(Exception):
    pass


def perform_login(username, password):
    """
    Perform full GT SSO + Duo login and return eAccounts session cookies.

    Args:
        username: GT username (e.g. 'gburdell3')
        password: GT password

    Returns:
        dict of {cookie_name: cookie_value} for eAccounts domain

    Raises:
        LoginError on any failure
    """
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    # ── Phase 1: Navigate to CAS login page ──
    # Follow redirects manually so we can log each hop and find CAS
    log('Phase 1: Navigating to eAccounts (following redirects to CAS)...')
    url = EACCOUNTS_URL
    resp = None
    max_redirects = 15
    for i in range(max_redirects):
        resp = session.get(url, allow_redirects=False, timeout=30)
        log(f'Hop {i}: {resp.status_code} {url}')

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get('Location', '')
            if location.startswith('/'):
                parsed = urlparse(url)
                location = f'{parsed.scheme}://{parsed.netloc}{location}'
            log(f'  -> Redirect to: {location}')
            url = location
            continue

        # Got a 200 — check if this is CAS login or the real page
        break

    log(f'Landed on: {url}')
    log(f'Status: {resp.status_code}, body length: {len(resp.text)}')
    log(f'Page title: {_get_title(resp.text)}')
    log(f'Body preview: {resp.text[:500]}')

    # Detect whether we're on CAS login, a Duo page, or eAccounts
    on_cas = 'cas' in url.lower() or 'login' in url.lower() or 'sso' in url.lower()
    on_eaccounts = 'transactcampus.com' in url

    # Check for SAML auto-submit form (SP-initiated SSO).
    # eAccounts returns a 200 with a form that POSTs SAMLRequest to GT IdP.
    # A browser would auto-submit via onload, but we need to do it manually.
    saml_request_form = _find_saml_request_form(resp.text)
    if saml_request_form:
        log(f'Found SAML AuthnRequest form -> {saml_request_form["action"]}')
        resp = session.post(
            saml_request_form['action'],
            data=saml_request_form['fields'],
            allow_redirects=True,
            timeout=30,
        )
        url = resp.url
        log(f'After SAML AuthnRequest POST: {url}')
        log(f'Status: {resp.status_code}, body length: {len(resp.text)}')
        log(f'Page title: {_get_title(resp.text)}')
        on_cas = 'cas' in url.lower() or 'login' in url.lower() or 'sso' in url.lower() or 'idp' in url.lower()

    if on_eaccounts and not saml_request_form:
        # Check if the page actually has account data (real session) vs a stub
        soup_check = BeautifulSoup(resp.text, 'html.parser')
        has_accounts = bool(soup_check.select('.account'))
        log(f'On eAccounts: has_accounts={has_accounts}')

        if has_accounts and len(resp.text) > 5000:
            log('Already logged in — session is still valid')
            return _extract_eaccounts_cookies(session)

        raise LoginError(f'eAccounts returned unexpected page (no SAML form, no accounts)')

    if not on_cas:
        log(f'Not on CAS. Current URL: {url}')
        log(f'Full body: {resp.text[:2000]}')
        raise LoginError(f'Could not reach CAS login page. Landed on: {url}')

    cas_login_url = url
    log(f'CAS login URL: {cas_login_url}')

    # Parse CAS login form
    soup = BeautifulSoup(resp.text, 'html.parser')
    form = soup.find('form', id='fm1') or soup.find('form')
    if not form:
        raise LoginError('Could not find CAS login form')

    form_action = form.get('action', '')
    if form_action.startswith('/'):
        parsed = urlparse(cas_login_url)
        form_action = f'{parsed.scheme}://{parsed.netloc}{form_action}'
    elif not form_action.startswith('http'):
        form_action = cas_login_url

    # Collect hidden fields
    form_data = {}
    for inp in form.find_all('input'):
        name = inp.get('name')
        if name:
            form_data[name] = inp.get('value', '')

    form_data['username'] = username
    form_data['password'] = password
    log(f'CAS form fields: {list(form_data.keys())}')
    log(f'Posting credentials to: {form_action}')

    # ── Phase 1b: Submit credentials to CAS ──
    resp = session.post(
        form_action,
        data=form_data,
        allow_redirects=True,
        timeout=30,
    )
    log(f'After CAS POST: {resp.url}')
    log(f'Status: {resp.status_code}, body length: {len(resp.text)}')

    # Check for CAS error (wrong credentials)
    if 'Invalid credentials' in resp.text or 'Authentication failed' in resp.text:
        raise LoginError('Invalid GT credentials')
    if 'Incorrect login or disabled account' in resp.text:
        raise LoginError('Invalid GT credentials or disabled account')

    # ── Phase 2: Duo 2FA ──
    log('Phase 2: Handling Duo 2FA...')
    duo_info = _extract_duo_info(resp.text, resp.url)

    if duo_info is None:
        # Check if we landed on a Duo Universal Prompt redirect
        duo_info = _check_duo_universal_prompt(resp, session)

    if duo_info is None:
        # Maybe CAS already completed (no Duo required?), or SAML form
        saml_form = _find_saml_form(resp.text)
        if saml_form:
            log('No Duo required — SAML assertion found directly')
            return _complete_saml_flow(session, saml_form, resp.url)
        # Log page content for debugging
        log(f'Page title: {_get_title(resp.text)}')
        log(f'Page body preview: {resp.text[:1000]}')
        raise LoginError('Could not find Duo iframe or SAML form after CAS login')

    auth_cookie = _do_duo_auth(session, duo_info)

    # ── Phase 3: Post Duo response back to CAS / service ──
    log('Phase 3: Completing authentication (SAML redirect)...')
    resp = _post_duo_response(session, duo_info, auth_cookie)

    # Follow the chain back to eAccounts
    cookies = _follow_post_duo_redirects(session, resp)
    return cookies


def _extract_duo_info(html, page_url):
    """
    Extract Duo iframe parameters from CAS page HTML.

    Looks for the iframe-based (v2) Duo integration:
    - duo_host (e.g. api-XXXXXXXX.duosecurity.com)
    - sig_request (TX|...:APP|...)
    - post_action URL (where to POST sig_response back)
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Method 1: Look for duo_form iframe
    duo_iframe = soup.find('iframe', id='duo_iframe')
    if duo_iframe:
        log('Found Duo iframe element')

    # Method 2: Look in script tags
    duo_host = None
    sig_request = None
    post_action = None

    # Check for hidden inputs first
    for inp in soup.find_all('input', type='hidden'):
        name = inp.get('name', '').lower()
        val = inp.get('value', '')
        if 'duo_host' in name or name == 'duohost':
            duo_host = val
        elif 'sig_request' in name or name == 'duosigrequest':
            sig_request = val

    # Check script tags
    for script in soup.find_all('script'):
        text = script.string or ''
        if not duo_host:
            m = re.search(r"['\"]host['\"]:\s*['\"]([^'\"]+)['\"]", text)
            if m:
                duo_host = m.group(1)
        if not sig_request:
            m = re.search(r"['\"]sig_request['\"]:\s*['\"]([^'\"]+)['\"]", text)
            if m:
                sig_request = m.group(1)
        if not post_action:
            m = re.search(r"['\"]post_action['\"]:\s*['\"]([^'\"]+)['\"]", text)
            if m:
                post_action = m.group(1)

    # Check data attributes on iframe
    if duo_iframe:
        duo_host = duo_host or duo_iframe.get('data-host', '')
        sig_request = sig_request or duo_iframe.get('data-sig-request', '')
        post_action = post_action or duo_iframe.get('data-post-action', '')

    if not duo_host or not sig_request:
        log(f'Duo iframe params not found (host={duo_host}, sig_request={bool(sig_request)})')
        return None

    if not post_action:
        post_action = page_url

    # Parse TX and APP tokens from sig_request
    tx_match = re.search(r'(TX\|[^:]+)', sig_request)
    app_match = re.search(r'(APP\|[^:]+)', sig_request)
    if not tx_match or not app_match:
        raise LoginError(f'Could not parse TX/APP from sig_request: {sig_request[:100]}...')

    log(f'Duo host: {duo_host}')
    log(f'TX token length: {len(tx_match.group(1))}')
    log(f'APP token length: {len(app_match.group(1))}')
    log(f'Post action: {post_action}')

    return {
        'host': duo_host,
        'tx': tx_match.group(1),
        'app': app_match.group(1),
        'post_action': post_action,
        'type': 'iframe',
    }


def _check_duo_universal_prompt(resp, session):
    """
    Check if CAS redirected to Duo Universal Prompt (OIDC-based).
    This is the newer flow where CAS redirects to Duo's hosted page.
    """
    if 'duosecurity.com' in resp.url:
        log(f'Landed on Duo Universal Prompt: {resp.url}')
        return {
            'type': 'universal',
            'url': resp.url,
            'html': resp.text,
        }

    # Check for a meta refresh or JS redirect to Duo
    soup = BeautifulSoup(resp.text, 'html.parser')
    meta = soup.find('meta', attrs={'http-equiv': 'refresh'})
    if meta:
        content = meta.get('content', '')
        m = re.search(r'url=(.+)', content, re.IGNORECASE)
        if m and 'duosecurity.com' in m.group(1):
            duo_url = m.group(1).strip()
            log(f'Meta refresh to Duo: {duo_url}')
            resp2 = session.get(duo_url, allow_redirects=True, timeout=30)
            return {
                'type': 'universal',
                'url': resp2.url,
                'html': resp2.text,
            }

    return None


def _do_duo_auth(session, duo_info):
    """
    Interact with Duo frame API to trigger push and wait for approval.
    Returns the auth cookie/signature from Duo.
    """
    if duo_info['type'] == 'universal':
        return _do_duo_universal(session, duo_info)
    else:
        return _do_duo_iframe(session, duo_info)


def _do_duo_iframe(session, duo_info):
    """Handle iframe-based (v2) Duo flow."""
    duo_host = duo_info['host']
    tx = duo_info['tx']
    parent = duo_info['post_action']

    # Step 1: POST to /frame/web/v1/auth to initiate Duo session
    auth_url = f'https://{duo_host}/frame/web/v1/auth'
    log(f'POST {auth_url}')

    resp = session.post(
        auth_url,
        params={'tx': tx, 'parent': parent, 'v': '2.6'},
        data={
            'parent': parent,
            'java_version': '',
            'flash_version': '',
            'screen_resolution_width': '1920',
            'screen_resolution_height': '1080',
            'color_depth': '24',
            'is_cef_browser': 'false',
            'is_ipad_os': 'false',
        },
        headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': f'https://{duo_host}',
        },
        allow_redirects=True,
        timeout=30,
    )
    log(f'Duo auth response: {resp.status_code}, url: {resp.url}')

    # Extract sid from the redirect URL
    parsed = urlparse(resp.url)
    query = parse_qs(parsed.query)
    if 'sid' not in query:
        # Check for remembered device bypass
        soup = BeautifulSoup(resp.text, 'html.parser')
        js_cookie_input = soup.find('input', {'name': 'js_cookie'})
        if js_cookie_input:
            log('Duo remembered device — bypassing 2FA')
            return js_cookie_input.get('value', '')
        log(f'No sid in Duo redirect URL: {resp.url}')
        log(f'Duo response preview: {resp.text[:500]}')
        raise LoginError('Failed to get Duo session ID (sid)')

    sid = query['sid'][0]
    log(f'Duo session ID: {sid[:20]}...')

    # Parse preferred factor/device from the prompt page
    soup = BeautifulSoup(resp.text, 'html.parser')
    factor_input = soup.find('input', {'name': 'preferred_factor'})
    device_input = soup.find('input', {'name': 'preferred_device'})
    factor = factor_input.get('value', 'Duo Push') if factor_input else 'Duo Push'
    device = device_input.get('value', 'phone1') if device_input else 'phone1'
    log(f'Preferred factor: {factor}, device: {device}')

    # Step 2: Trigger Duo Push
    prompt_url = f'https://{duo_host}/frame/prompt'
    log(f'Triggering Duo Push...')

    resp = session.post(
        prompt_url,
        data={
            'sid': sid,
            'factor': 'Duo Push',
            'device': 'phone1',
            'postAuthDestination': 'OIDC_EXIT',
            'out_of_date': '',
            'days_out_of_date': '',
            'days_to_block': 'None',
        },
        headers={
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Accept': 'text/plain, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'https://{duo_host}/frame/prompt',
        },
        timeout=30,
    )

    prompt_result = resp.json()
    log(f'Duo prompt response: {prompt_result}')

    if prompt_result.get('stat') != 'OK':
        raise LoginError(f'Duo push failed: {prompt_result}')

    txid = prompt_result['response']['txid']
    log(f'Duo transaction ID: {txid}')
    log('Waiting for Duo push approval (check your phone)...')

    # Step 3: Poll /frame/status until approved
    status_url = f'https://{duo_host}/frame/status'
    start_time = time.time()

    while time.time() - start_time < DUO_POLL_TIMEOUT:
        time.sleep(DUO_POLL_INTERVAL)

        resp = session.post(
            status_url,
            data={'sid': sid, 'txid': txid},
            headers={
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Accept': 'text/plain, */*; q=0.01',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f'https://{duo_host}/frame/prompt',
            },
            timeout=30,
        )

        status_result = resp.json()
        status_code = status_result.get('response', {}).get('status_code', '')
        status_msg = status_result.get('response', {}).get('status', '')
        log(f'Duo status: {status_code} — {status_msg}')

        if status_code == 'allow':
            log('Duo push approved!')
            result_url = status_result['response'].get('result_url', '')
            if result_url:
                # Fetch the auth cookie from result_url
                full_result_url = f'https://{duo_host}{result_url}'
                resp = session.post(
                    full_result_url,
                    data={'sid': sid},
                    headers={
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'Accept': 'text/plain, */*; q=0.01',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    timeout=30,
                )
                result_json = resp.json()
                log(f'Duo result response stat: {result_json.get("stat")}')
                auth_cookie = result_json.get('response', {}).get('cookie', '')
                if not auth_cookie:
                    raise LoginError(f'No auth cookie in Duo result: {result_json}')
                return auth_cookie
            else:
                raise LoginError('No result_url in Duo allow response')

        elif status_code == 'deny':
            raise LoginError('Duo push was denied')
        elif status_code == 'timeout':
            raise LoginError('Duo push timed out — no response from phone')

    raise LoginError(f'Duo push approval timed out after {DUO_POLL_TIMEOUT}s')


def _do_duo_universal(session, duo_info):
    """
    Handle Universal Prompt (v4 frameless) Duo flow.
    The initial page is a preauth page with a plugin_form that must be
    submitted first to initialize the Duo session, then we can trigger a push.
    """
    html = duo_info['html']
    current_url = duo_info['url']
    soup = BeautifulSoup(html, 'html.parser')
    parsed = urlparse(current_url)
    duo_host = parsed.netloc

    log(f'Duo Universal Prompt page: {current_url}')
    log(f'Page title: {_get_title(html)}')

    # Step 1: Extract and submit the preauth plugin_form.
    # This form collects browser info and initializes the Duo session.
    # Without this, /frame/v4/prompt returns error 57.
    plugin_form = soup.find('form', id='plugin_form')
    if not plugin_form:
        plugin_form = soup.find('form')

    if plugin_form:
        form_data = {}
        for inp in plugin_form.find_all('input'):
            name = inp.get('name')
            if name:
                form_data[name] = inp.get('value', '')

        # Fill in browser fingerprint fields
        form_data['screen_resolution_width'] = '1920'
        form_data['screen_resolution_height'] = '1080'
        form_data['color_depth'] = '24'
        form_data['is_cef_browser'] = 'false'
        form_data['is_ipad_os'] = 'false'
        form_data['is_ie_compatibility_mode'] = ''
        form_data['is_user_verifying_platform_authenticator_available'] = 'false'
        form_data['react_support'] = 'true'

        # Extract the clean xsrf token from the hidden field
        xsrf_token = form_data.get('_xsrf', '')
        log(f'Preauth xsrf token: {xsrf_token}')
        log(f'Preauth form fields: {list(form_data.keys())}')

        # POST preauth form to the same URL (no action = same page)
        preauth_url = current_url
        log(f'Submitting preauth form to: {preauth_url}')

        resp = session.post(
            preauth_url,
            data=form_data,
            allow_redirects=True,
            timeout=30,
        )
        log(f'Preauth response: {resp.status_code}, url: {resp.url}')
        log(f'Preauth body length: {len(resp.text)}')

        # After preauth, we land on the healthcheck page with a React app.
        # Parse the base-data JSON embedded in the page — it has device info.
        import json as json_mod
        preauth_soup = BeautifulSoup(resp.text, 'html.parser')
        base_data_el = preauth_soup.find('script', id='base-data')
        if base_data_el and base_data_el.string:
            try:
                base_data = json_mod.loads(base_data_el.string)
                log(f'base-data keys: {list(base_data.keys())}')
                log(f'base-data: {json_mod.dumps(base_data, indent=2)[:2000]}')
            except Exception as e:
                log(f'Failed to parse base-data: {e}')
                base_data = {}
        else:
            log('No base-data found in preauth response')
            base_data = {}

        # Extract sid from new URL
        new_parsed = urlparse(resp.url)
        new_sid = parse_qs(new_parsed.query).get('sid', [None])
        if new_sid and new_sid[0]:
            sid = new_sid[0]
        else:
            sid = parse_qs(parsed.query).get('sid', [None])[0]

        # Get xsrf token from base-data (most reliable source)
        xsrf_token = base_data.get('xsrf_token', '')
        log(f'xsrf from base-data: {xsrf_token}')

        # Build raw cookie header from the session's Set-Cookie responses.
        # requests.Session may mangle cookie names with pipe characters like
        # "sid|{uuid}" and "_xsrf|{uuid}", so we capture them from the
        # response headers directly.
        duo_cookies = {}
        for r in [resp] + list(getattr(resp, 'history', [])):
            for header_val in r.headers.get('Set-Cookie', '').split('\n'):
                if not header_val:
                    continue
                # Also check raw headers for multiple Set-Cookie
                pass
        # Use response.cookies which has the parsed cookies from the last response chain
        for cookie in session.cookies:
            if 'duosecurity.com' in (cookie.domain or ''):
                duo_cookies[cookie.name] = cookie.value
                log(f'  Duo session cookie: {cookie.name} = {cookie.value[:50]}...')

        # Also manually extract from raw response headers (in case requests mangled them)
        log(f'Session cookie jar has {len(list(session.cookies))} total cookies')
        for cookie in session.cookies:
            log(f'  cookie jar: domain={cookie.domain} name={cookie.name}')

        log(f'Using sid: {sid[:30]}...')
    else:
        sid = parse_qs(parsed.query).get('sid', [None])[0]
        xsrf_token = None
        duo_cookies = {}

    if not sid:
        raise LoginError('Could not extract session ID from Duo Universal Prompt')

    return _poll_duo_push(session, duo_host, sid, xsrf_token, duo_cookies)


def _poll_duo_push(session, duo_host, sid, xsrf_token=None, duo_cookies=None):
    """Trigger Duo push and poll for approval. Uses v4 frameless API."""

    browser_features = json.dumps({
        'touch_supported': False,
        'platform_authenticator_status': 'available',
        'webauthn_supported': True,
        'screen_resolution_height': 915,
        'screen_resolution_width': 1463,
        'screen_color_depth': 24,
        'is_uvpa_available': True,
        'client_capabilities_uvpa': True,
    })

    # Build manual Cookie header — requests.Session can't handle pipe chars
    # in cookie names like "sid|{uuid}" and "_xsrf|{uuid}"
    cookie_header = '; '.join(f'{k}={v}' for k, v in (duo_cookies or {}).items())
    log(f'Manual Duo cookie header: {cookie_header[:200]}...')

    # Build headers — v4 frameless requires xsrf token
    api_headers = {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'Accept': '*/*',
        'Origin': f'https://{duo_host}',
        'Referer': f'https://{duo_host}/frame/v4/auth/prompt?sid={sid}',
    }
    if xsrf_token:
        api_headers['X-Xsrftoken'] = xsrf_token
    if cookie_header:
        api_headers['Cookie'] = cookie_header

    log(f'Duo API headers: { {k: (v[:50] + "...") if len(str(v)) > 50 else v for k,v in api_headers.items()} }')

    # Step 1: GET /frame/v4/auth/prompt/data — initializes the session
    data_url = f'https://{duo_host}/frame/v4/auth/prompt/data'
    data_params = {
        'post_auth_action': 'OIDC_EXIT',
        'browser_features': browser_features,
        'sid': sid,
    }
    log(f'Fetching auth prompt data from {data_url}...')
    resp = requests.get(data_url, params=data_params, headers={**BROWSER_HEADERS, **api_headers}, timeout=30)
    log(f'Auth prompt data response status: {resp.status_code}')
    log(f'Auth prompt data response body: {resp.text[:2000]}')

    # Step 2: POST /frame/v4/prompt — trigger push
    prompt_url = f'https://{duo_host}/frame/v4/prompt'
    log(f'Triggering Duo Push via {prompt_url}...')

    prompt_data = {
        'device': 'phone1',
        'factor': 'Duo Push',
        'postAuthDestination': 'OIDC_EXIT',
        'browser_features': browser_features,
        'sid': sid,
    }

    resp = requests.post(prompt_url, data=prompt_data, headers={**BROWSER_HEADERS, **api_headers}, timeout=30)
    log(f'Duo prompt response status: {resp.status_code}')
    log(f'Duo prompt response body: {resp.text[:500]}')

    try:
        prompt_result = resp.json()
    except Exception:
        raise LoginError(f'Duo prompt returned non-JSON (status {resp.status_code}): {resp.text[:500]}')

    log(f'Duo prompt response: {prompt_result}')

    if prompt_result.get('stat') != 'OK':
        raise LoginError(f'Duo push failed: {prompt_result}')

    txid = prompt_result['response']['txid']
    log(f'Duo txid: {txid}')
    log('Waiting for Duo push approval (check your phone)...')

    # Step 3: POST /frame/v4/status — poll for approval
    status_url = f'https://{duo_host}/frame/v4/status'
    start_time = time.time()

    while time.time() - start_time < DUO_POLL_TIMEOUT:
        time.sleep(DUO_POLL_INTERVAL)

        resp = requests.post(
            status_url,
            data={'txid': txid, 'sid': sid},
            headers={**BROWSER_HEADERS, **api_headers},
            timeout=30,
        )

        try:
            status_result = resp.json()
        except Exception:
            log(f'Duo status non-JSON (status {resp.status_code}): {resp.text[:300]}')
            continue

        status_code = status_result.get('response', {}).get('status_code', '')
        status_msg = status_result.get('response', {}).get('status', '')
        log(f'Duo status: {status_code} — {status_msg}')

        if status_code == 'allow':
            log('Duo push approved!')
            result_url = status_result['response'].get('result_url', '')
            if result_url:
                resp = requests.post(
                    f'https://{duo_host}{result_url}',
                    data={'sid': sid},
                    headers={**BROWSER_HEADERS, **api_headers},
                    timeout=30,
                )
                log(f'Duo result status: {resp.status_code}')
                log(f'Duo result body: {resp.text[:500]}')

                try:
                    result_json = resp.json()
                except Exception:
                    # v4 might return HTML redirect instead of JSON
                    log('Duo result returned non-JSON — checking for redirect')
                    return {'type': 'redirect', 'response': resp}

                auth_cookie = result_json.get('response', {}).get('cookie', '')
                if auth_cookie:
                    return auth_cookie

                # v4 might return a parent redirect URL
                parent = result_json.get('response', {}).get('parent', '')
                if parent:
                    log(f'Duo redirect parent: {parent}')
                    return result_json['response']

                return result_json

            raise LoginError(f'Unexpected Duo result: {status_result}')

        elif status_code == 'deny':
            raise LoginError('Duo push was denied')
        elif status_code == 'timeout':
            raise LoginError('Duo push timed out')

    raise LoginError(f'Duo poll timed out after {DUO_POLL_TIMEOUT}s')


def _post_duo_response(session, duo_info, auth_cookie):
    """
    Post the Duo auth response back to CAS.
    For iframe-based flow: POST sig_response = AUTH:APP
    For universal flow: follow the redirect chain
    """
    if duo_info['type'] == 'iframe':
        sig_response = f'{auth_cookie}:{duo_info["app"]}'
        post_action = duo_info['post_action']
        log(f'Posting sig_response to: {post_action}')

        # Find the form field names — CAS typically expects signedDuoResponse
        resp = session.post(
            post_action,
            data={
                'signedDuoResponse': sig_response,
                '_eventId': 'submit',
            },
            allow_redirects=True,
            timeout=30,
        )
        log(f'After Duo POST-back: {resp.url}')
        log(f'Status: {resp.status_code}')
        return resp

    elif duo_info['type'] == 'universal':
        # Universal Prompt (v4 frameless) — Duo redirects back to CAS with a duo code.
        # The auth_cookie could be: a string, a dict with parent/cookie, or a redirect response.
        log(f'Duo Universal response type: {type(auth_cookie).__name__}')

        if isinstance(auth_cookie, dict):
            # Check for a redirect response object
            if auth_cookie.get('type') == 'redirect':
                resp = auth_cookie['response']
                log(f'Using Duo redirect response: {resp.url}')
                return resp

            parent = auth_cookie.get('parent', '')
            if parent:
                log(f'Following Duo parent redirect: {parent}')
                resp = session.get(parent, allow_redirects=True, timeout=30)
                log(f'After Duo parent redirect: {resp.url}')
                return resp

            # Try the result_url if present
            result_url = auth_cookie.get('result_url', '')
            if result_url:
                log(f'Following Duo result_url: {result_url}')
                resp = session.get(result_url, allow_redirects=True, timeout=30)
                log(f'After Duo result_url: {resp.url}')
                return resp

            log(f'Duo response dict keys: {list(auth_cookie.keys())}')
            log(f'Duo response dict: {auth_cookie}')

        # For v4 frameless, after approval Duo should redirect back to CAS
        # via the redirect_uri in the original tx JWT.
        # The redirect_uri was: https://sso.gatech.edu/cas/login
        # with a duo_code parameter. Let's try following the Duo page again.
        log('Following redirects back from Duo Universal Prompt...')
        resp = session.get(duo_info['url'], allow_redirects=True, timeout=30)
        log(f'After revisiting Duo URL: {resp.url}')
        log(f'Status: {resp.status_code}, body length: {len(resp.text)}')
        return resp


def _follow_post_duo_redirects(session, resp):
    """
    After Duo auth, follow the redirect chain back to eAccounts.
    CAS → SAML assertion → eAccounts sets session cookies.
    """
    # Check if we're already on eAccounts
    if 'transactcampus.com' in resp.url:
        log(f'Already on eAccounts: {resp.url}')
        return _extract_eaccounts_cookies(session)

    # Look for SAML auto-submit form
    saml_form = _find_saml_form(resp.text)
    if saml_form:
        log('Found SAML assertion form, submitting...')
        result = _complete_saml_flow(session, saml_form, resp.url)
        return result

    # Check for additional redirects
    if resp.status_code in (301, 302, 303, 307):
        location = resp.headers.get('Location', '')
        log(f'Following redirect to: {location}')
        resp = session.get(location, allow_redirects=True, timeout=30)
        return _follow_post_duo_redirects(session, resp)

    # Maybe there's a JS redirect or meta refresh
    soup = BeautifulSoup(resp.text, 'html.parser')
    meta = soup.find('meta', attrs={'http-equiv': 'refresh'})
    if meta:
        content = meta.get('content', '')
        m = re.search(r'url=(.+)', content, re.IGNORECASE)
        if m:
            url = m.group(1).strip().rstrip('"').rstrip("'")
            log(f'Following meta refresh to: {url}')
            resp = session.get(url, allow_redirects=True, timeout=30)
            return _follow_post_duo_redirects(session, resp)

    # If we're on CAS with a ticket, follow service URL
    if 'cas' in resp.url.lower() and 'ticket=' in resp.url:
        log(f'CAS ticket in URL, following...')
        resp = session.get(resp.url, allow_redirects=True, timeout=30)
        return _follow_post_duo_redirects(session, resp)

    log(f'Redirect chain ended at: {resp.url}')
    log(f'Response status: {resp.status_code}')
    log(f'Page title: {_get_title(resp.text)}')
    log(f'Body preview: {resp.text[:500]}')

    # Last resort: try navigating to eAccounts directly
    # (the session might have the right cookies now)
    log('Attempting direct navigation to eAccounts...')
    resp = session.get(EACCOUNTS_URL, allow_redirects=True, timeout=30)
    log(f'Direct navigation landed on: {resp.url}')

    if 'login' in resp.url.lower() or 'cas' in resp.url.lower():
        raise LoginError('Login flow completed but session was not established. '
                         'The redirect chain may have failed.')

    return _extract_eaccounts_cookies(session)


def _find_saml_request_form(html):
    """Find a SAML AuthnRequest auto-submit form (SP -> IdP)."""
    soup = BeautifulSoup(html, 'html.parser')
    saml_input = soup.find('input', {'name': 'SAMLRequest'})
    if not saml_input:
        return None

    form = saml_input.find_parent('form')
    if not form:
        return None

    action = form.get('action', '')
    fields = {}
    for inp in form.find_all('input'):
        name = inp.get('name')
        if name:
            fields[name] = inp.get('value', '')

    return {'action': action, 'fields': fields}


def _find_saml_form(html):
    """Find a SAML assertion auto-submit form in the HTML."""
    soup = BeautifulSoup(html, 'html.parser')

    # Look for SAMLResponse hidden field
    saml_input = soup.find('input', {'name': 'SAMLResponse'})
    if not saml_input:
        return None

    form = saml_input.find_parent('form')
    if not form:
        return None

    action = form.get('action', '')
    fields = {}
    for inp in form.find_all('input', type='hidden'):
        name = inp.get('name')
        if name:
            fields[name] = inp.get('value', '')

    log(f'SAML form action: {action}')
    log(f'SAML form fields: {list(fields.keys())}')
    return {'action': action, 'fields': fields}


def _complete_saml_flow(session, saml_form, page_url):
    """Submit the SAML assertion form and follow to eAccounts."""
    action = saml_form['action']
    if not action.startswith('http'):
        parsed = urlparse(page_url)
        action = f'{parsed.scheme}://{parsed.netloc}{action}'

    log(f'Posting SAML assertion to: {action}')
    resp = session.post(
        action,
        data=saml_form['fields'],
        allow_redirects=True,
        timeout=30,
    )
    log(f'After SAML POST: {resp.url}')
    log(f'Status: {resp.status_code}')

    # There might be another SAML form (chained assertions)
    nested_saml = _find_saml_form(resp.text)
    if nested_saml:
        log('Found nested SAML form, submitting...')
        return _complete_saml_flow(session, nested_saml, resp.url)

    if 'transactcampus.com' in resp.url:
        return _extract_eaccounts_cookies(session)

    # If we ended up somewhere else, try eAccounts directly
    log(f'SAML flow ended at: {resp.url}, trying eAccounts directly...')
    resp = session.get(EACCOUNTS_URL, allow_redirects=True, timeout=30)
    if 'login' in resp.url.lower() or 'cas' in resp.url.lower():
        raise LoginError('SAML assertion was posted but eAccounts session not established')

    return _extract_eaccounts_cookies(session)


def _extract_eaccounts_cookies(session):
    """Extract eAccounts cookies from the session's cookie jar."""
    cookies = {}
    for cookie in session.cookies:
        if 'transactcampus.com' in (cookie.domain or ''):
            cookies[cookie.name] = cookie.value
            log(f'Cookie: {cookie.name} = {cookie.value[:50]}...')

    if not cookies:
        # Also check for cookies without domain filtering (some may not have domain set)
        log('No transactcampus.com cookies found, checking all cookies...')
        for cookie in session.cookies:
            log(f'  All cookies: {cookie.domain} / {cookie.name}')

    log(f'Extracted {len(cookies)} eAccounts cookies')
    return cookies


def _get_title(html):
    """Extract page title from HTML."""
    m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else '(no title)'

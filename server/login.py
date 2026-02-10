"""
GT SSO + Duo 2FA login flow via HTTP requests.

Performs the full login chain:
  1. GET eAccounts → follows redirects to CAS login page
  2. POST credentials to CAS
  3. Interact with Duo frame API (trigger push, poll for approval)
  4. Follow SAML assertion back to eAccounts
  5. Return session cookies
"""

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
    log('Phase 1: Navigating to eAccounts (following redirects to CAS)...')
    resp = session.get(EACCOUNTS_URL, allow_redirects=True, timeout=30)
    log(f'Landed on: {resp.url}')
    log(f'Status: {resp.status_code}, body length: {len(resp.text)}')

    if 'login' not in resp.url and 'cas' not in resp.url.lower():
        # Maybe we already have a valid session
        if 'AccountSummary' in resp.url:
            log('Already logged in — session is still valid')
            return _extract_eaccounts_cookies(session)
        raise LoginError(f'Unexpected landing page: {resp.url}')

    cas_login_url = resp.url
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
    Handle Universal Prompt (OIDC) Duo flow.
    This is the newer flow where you're on a duosecurity.com page.
    """
    html = duo_info['html']
    current_url = duo_info['url']
    soup = BeautifulSoup(html, 'html.parser')

    log(f'Duo Universal Prompt page: {current_url}')
    log(f'Page title: {_get_title(html)}')

    # The Universal Prompt page is a full page (not iframe).
    # We need to find the API endpoint and session info.
    # Look for xsrf token and session data in the page.

    # Extract xsrf token from meta tag or cookie
    xsrf_token = None
    meta_xsrf = soup.find('meta', {'name': 'csrf-token'})
    if meta_xsrf:
        xsrf_token = meta_xsrf.get('content', '')

    # Check cookies for xsrf
    for cookie in session.cookies:
        if 'xsrf' in cookie.name.lower() or cookie.name == 'has_trust_token':
            log(f'Duo cookie: {cookie.name}={cookie.value[:50]}...')

    # The Universal Prompt typically embeds JSON config in the page
    # Look for it in script tags
    config = None
    for script in soup.find_all('script'):
        text = script.string or ''
        # Look for JSON config object
        m = re.search(r'window\.__DUO_UNIVERSAL__\s*=\s*(\{.+?\});', text, re.DOTALL)
        if m:
            import json
            config = json.loads(m.group(1))
            log(f'Found Duo Universal config keys: {list(config.keys())}')
            break

    # The Universal Prompt uses a different API pattern.
    # It typically shows a prompt page where we need to:
    # 1. Find the "Send Me a Push" button / form
    # 2. POST to trigger the push
    # 3. Poll for completion
    # 4. Follow the redirect back

    # Look for forms on the page
    forms = soup.find_all('form')
    for f in forms:
        log(f'Form found: action={f.get("action")}, method={f.get("method")}')

    # For the Universal Prompt, the flow is typically:
    # The page has API calls embedded that we need to replicate.
    # Let's look for the Duo API base URL in the page.

    parsed = urlparse(current_url)
    duo_base = f'{parsed.scheme}://{parsed.netloc}'

    # Try to find the healthcheck/auth endpoint
    # Universal prompt typically uses /frame/v4/auth/prompt or similar
    sid = parse_qs(parsed.query).get('sid', [None])[0]
    if not sid:
        # Try fragment
        if parsed.fragment:
            sid = parse_qs(parsed.fragment).get('sid', [None])[0]

    if sid:
        log(f'Found sid from URL: {sid[:20]}...')
        # Use the same prompt/status flow as iframe
        return _poll_duo_push(session, parsed.netloc, sid)

    # If we can't find sid, try to extract it from the page content
    m = re.search(r'"sid"\s*:\s*"([^"]+)"', html)
    if m:
        sid = m.group(1)
        log(f'Found sid from page content: {sid[:20]}...')
        return _poll_duo_push(session, parsed.netloc, sid)

    log(f'Universal Prompt page HTML preview: {html[:2000]}')
    raise LoginError('Could not extract session ID from Duo Universal Prompt')


def _poll_duo_push(session, duo_host, sid):
    """Shared logic for triggering and polling a Duo push."""
    # Trigger push
    prompt_url = f'https://{duo_host}/frame/prompt'
    log(f'Triggering Duo Push via {prompt_url}...')

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
        },
        timeout=30,
    )

    prompt_result = resp.json()
    log(f'Duo prompt response: {prompt_result}')

    if prompt_result.get('stat') != 'OK':
        raise LoginError(f'Duo push failed: {prompt_result}')

    txid = prompt_result['response']['txid']
    log(f'Duo txid: {txid}')
    log('Waiting for Duo push approval (check your phone)...')

    # Poll
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
                resp = session.post(
                    f'https://{duo_host}{result_url}',
                    data={'sid': sid},
                    headers={
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'Accept': 'text/plain, */*; q=0.01',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    timeout=30,
                )
                result_json = resp.json()
                auth_cookie = result_json.get('response', {}).get('cookie', '')
                if auth_cookie:
                    return auth_cookie

                # Universal prompt might have parent URL in the response
                parent = result_json.get('response', {}).get('parent', '')
                if parent:
                    log(f'Duo redirect parent: {parent}')
                    return result_json['response']

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
        # Universal Prompt handles redirects differently
        # The auth_cookie might be a dict with redirect info or a string
        if isinstance(auth_cookie, dict):
            parent = auth_cookie.get('parent', '')
            if parent:
                resp = session.get(parent, allow_redirects=True, timeout=30)
                log(f'After Duo Universal redirect: {resp.url}')
                return resp

        # Try following the current page's redirect back
        log('Following redirects back from Duo Universal Prompt...')
        # After approval, Duo redirects back to CAS with an auth code
        # The session should handle this via cookies
        resp = session.get(duo_info['url'], allow_redirects=True, timeout=30)
        log(f'After revisiting Duo URL: {resp.url}')
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

import requests
import pickle
import os
import re
import json
import base64
from datetime import datetime
from bs4 import BeautifulSoup
from login import _find_saml_request_form, _find_saml_form, _complete_saml_flow

BASE_URL = 'https://eacct-buzzcard-sp.transactcampus.com/buzzcard'

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
}


def log(msg):
    print(f'[{datetime.now()}] {msg}', flush=True)


class SessionExpiredError(Exception):
    pass


class DiningBalanceScraper:
    def __init__(self):
        self.cookies_file = 'cookies.pkl'
        self.sso_cookies_file = 'sso_cookies.pkl'
        self.cookie_dict = {}  # plain {name: value} dict
        self.load_cookies()

    def _cookie_header(self):
        """Build a Cookie header string, same as Node.js version."""
        header = '; '.join(f'{k}={v}' for k, v in self.cookie_dict.items())
        log(f'Cookie header length: {len(header)} chars, {len(self.cookie_dict)} cookies')
        return header

    def load_cookies(self):
        """Load cookies from file, falling back to INITIAL_COOKIES env var."""
        log(f'load_cookies() called')
        log(f'  cookies.pkl exists: {os.path.exists(self.cookies_file)}')
        log(f'  INITIAL_COOKIES env var set: {bool(os.environ.get("INITIAL_COOKIES"))}')

        # Try cookies.pkl first
        if os.path.exists(self.cookies_file):
            try:
                with open(self.cookies_file, 'rb') as f:
                    self.cookie_dict = pickle.load(f)
                log(f'Loaded {len(self.cookie_dict)} cookies from {self.cookies_file}')
                for name in self.cookie_dict:
                    log(f'  cookie: {name} = {str(self.cookie_dict[name])[:50]}...')
                return
            except Exception as e:
                log(f'Failed to load {self.cookies_file}: {e}')

        # Fallback to INITIAL_COOKIES env var (base64 encoded JSON)
        env_cookies = os.environ.get('INITIAL_COOKIES')
        if env_cookies:
            log(f'INITIAL_COOKIES length: {len(env_cookies)} chars')
            try:
                decoded = base64.b64decode(env_cookies)
                log(f'Base64 decoded length: {len(decoded)} bytes')
                cookie_data = json.loads(decoded)
                log(f'JSON parsed, type: {type(cookie_data).__name__}')

                if isinstance(cookie_data, dict) and 'cookies' in cookie_data:
                    log(f'Playwright storageState format, {len(cookie_data["cookies"])} total cookies')
                    for c in cookie_data['cookies']:
                        domain = c.get('domain', '')
                        log(f'  cookie domain={domain} name={c.get("name", "?")}')
                        if 'eacct-buzzcard-sp.transactcampus.com' in domain:
                            self.cookie_dict[c['name']] = c['value']
                            log(f'    -> KEPT')
                        else:
                            log(f'    -> SKIPPED (wrong domain)')
                elif isinstance(cookie_data, dict):
                    log(f'Plain dict format with {len(cookie_data)} keys')
                    self.cookie_dict = cookie_data

                log(f'Final cookie_dict has {len(self.cookie_dict)} cookies:')
                for name in self.cookie_dict:
                    log(f'  {name} = {str(self.cookie_dict[name])[:50]}...')

                self.save_cookies()
                log(f'Loaded {len(self.cookie_dict)} cookies from INITIAL_COOKIES env var')
                return
            except Exception as e:
                log(f'Failed to parse INITIAL_COOKIES: {e}')
                import traceback
                traceback.print_exc()

        log(f'No cookies found!')

    def save_cookies(self):
        """Save current cookies to file."""
        with open(self.cookies_file, 'wb') as f:
            pickle.dump(self.cookie_dict, f)
        log(f'Saved {len(self.cookie_dict)} cookies to {self.cookies_file}')

    def _refresh_via_saml(self, saml_html):
        """Attempt to refresh eAccounts session by following the SAML redirect chain
        using saved SSO/Duo cookies (no Duo push needed if SSO session is still valid).

        Returns True on success, raises SessionExpiredError if SSO cookies are also expired.
        """
        log('Attempting SAML session refresh...')

        # Load all saved cookies (SSO, Duo, eAccounts)
        if not os.path.exists(self.sso_cookies_file):
            log('No sso_cookies.pkl found — cannot refresh via SAML')
            raise SessionExpiredError('Session expired (no SSO cookies saved)')

        try:
            with open(self.sso_cookies_file, 'rb') as f:
                all_cookies = pickle.load(f)
            log(f'Loaded {len(all_cookies)} SSO cookies from {self.sso_cookies_file}')
        except Exception as e:
            log(f'Failed to load SSO cookies: {e}')
            raise SessionExpiredError('Session expired (failed to load SSO cookies)')

        # Create a requests.Session and load all cookies with proper domains
        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)
        for c in all_cookies:
            domain = c['domain']
            # Strip leading dot for requests compatibility
            if domain.startswith('.'):
                domain = domain[1:]
            session.cookies.set(
                c['name'], c['value'],
                domain=domain, path=c.get('path', '/'),
            )

        # Parse the SAML form from the HTML (SAMLRequest form from eAccounts -> IdP)
        saml_request_form = _find_saml_request_form(saml_html)
        if not saml_request_form:
            log('No SAML request form found in HTML')
            raise SessionExpiredError('Session expired (no SAML form in response)')

        log(f'SAML request form action: {saml_request_form["action"]}')

        try:
            # POST the SAMLRequest to the IdP
            resp = session.post(
                saml_request_form['action'],
                data=saml_request_form['fields'],
                allow_redirects=True,
                timeout=30,
            )
            log(f'After SAML request POST: {resp.url} (status {resp.status_code})')

            # Check if IdP returned a SAML response form (SSO cookies still valid)
            saml_form = _find_saml_form(resp.text)
            if saml_form:
                log('IdP returned SAML assertion — SSO session is valid!')
                cookies = _complete_saml_flow(session, saml_form, resp.url)
                if cookies:
                    self.cookie_dict = cookies
                    self.save_cookies()
                    # Update SSO cookies with any refreshed values
                    self._save_sso_cookies(session)
                    log(f'SAML refresh successful — {len(cookies)} fresh eAccounts cookies')
                    return True

            # Check if we ended up on eAccounts directly (cookies already set via redirects)
            if 'transactcampus.com' in resp.url:
                cookies = {}
                for cookie in session.cookies:
                    if 'transactcampus.com' in (cookie.domain or ''):
                        cookies[cookie.name] = cookie.value
                if cookies:
                    self.cookie_dict = cookies
                    self.save_cookies()
                    self._save_sso_cookies(session)
                    log(f'SAML refresh successful (direct) — {len(cookies)} fresh eAccounts cookies')
                    return True

            # If we landed on a login page, SSO cookies are also expired
            if 'login' in resp.url.lower() or 'cas' in resp.url.lower():
                log(f'SSO cookies expired — landed on login page: {resp.url}')
                raise SessionExpiredError('Session expired (SSO cookies also expired)')

            log(f'SAML refresh ended at unexpected URL: {resp.url}')
            raise SessionExpiredError('Session expired (SAML refresh failed)')

        except SessionExpiredError:
            raise
        except Exception as e:
            log(f'SAML refresh error: {e}')
            import traceback
            traceback.print_exc()
            raise SessionExpiredError(f'Session expired (SAML refresh error: {e})')

    def _save_sso_cookies(self, session):
        """Save all cookies from a requests.Session to sso_cookies.pkl."""
        all_cookies = []
        for cookie in session.cookies:
            all_cookies.append({
                'name': cookie.name,
                'value': cookie.value,
                'domain': cookie.domain or '',
                'path': cookie.path or '/',
            })
        with open(self.sso_cookies_file, 'wb') as f:
            pickle.dump(all_cookies, f)
        log(f'Saved {len(all_cookies)} SSO cookies to {self.sso_cookies_file}')

    def _update_cookies_from_response(self, response):
        """Update cookie dict from Set-Cookie response headers."""
        new_cookies = list(response.cookies)
        if new_cookies:
            log(f'Response Set-Cookie headers: {len(new_cookies)} cookies')
            for cookie in new_cookies:
                log(f'  Set-Cookie: {cookie.name} = {str(cookie.value)[:50]}...')
                self.cookie_dict[cookie.name] = cookie.value
        else:
            log(f'No Set-Cookie headers in response')

    def _fetch_page(self, url):
        """GET a page with manual Cookie header."""
        log(f'GET {url}')
        response = requests.get(
            url,
            headers={**BROWSER_HEADERS, 'Cookie': self._cookie_header()},
            timeout=30,
            allow_redirects=False,
        )
        log(f'GET Response: {response.status_code}, body length: {len(response.text)} chars')
        log(f'GET Response headers: {dict(response.headers)}')

        if response.status_code == 302:
            location = response.headers.get('Location', '')
            log(f'GET Redirect to: {location}')
            if 'login' in location.lower() or 'cas' in location.lower() or 'sso' in location.lower():
                raise SessionExpiredError('Session expired')
            raise Exception(f'Redirected to: {location}')

        if response.status_code != 200:
            log(f'GET Unexpected status! Body preview: {response.text[:500]}')
            raise Exception(f'Unexpected status: {response.status_code}')

        # Log a snippet of the HTML to confirm we got the right page
        title_match = re.search(r'<title>(.*?)</title>', response.text, re.IGNORECASE)
        if title_match:
            log(f'Page title: {title_match.group(1)}')
        else:
            log(f'No <title> found, body preview: {response.text[:200]}')

        # Detect SAML redirect pages (200 with auto-submit form to SSO/IDP)
        if 'document.forms.theform.submit()' in response.text and 'idp' in response.text.lower():
            log('SAML redirect page detected — attempting auto-refresh via SSO cookies')
            self._refresh_via_saml(response.text)
            # Retry the original request with fresh cookies
            log(f'Retrying GET {url} with refreshed cookies...')
            response = requests.get(
                url,
                headers={**BROWSER_HEADERS, 'Cookie': self._cookie_header()},
                timeout=30,
                allow_redirects=False,
            )
            log(f'Retry response: {response.status_code}, body length: {len(response.text)} chars')
            # If it's still a SAML redirect after refresh, give up
            if 'document.forms.theform.submit()' in response.text and 'idp' in response.text.lower():
                log('SAML redirect again after refresh — session expired')
                raise SessionExpiredError('Session expired (SAML redirect after refresh)')
            if response.status_code != 200:
                raise Exception(f'Unexpected status after refresh: {response.status_code}')

        self._update_cookies_from_response(response)
        self.save_cookies()
        return response.text

    def _ajax_post(self, url, form_data):
        """POST an ASP.NET AJAX async postback with manual Cookie header."""
        log(f'POST {url}')
        log(f'POST form_data keys: {list(form_data.keys())}')
        log(f'POST __EVENTTARGET: {form_data.get("__EVENTTARGET", "?")}')
        log(f'POST RadScriptManager1: {form_data.get("ctl00$RadScriptManager1", "?")}')
        log(f'POST __VIEWSTATE length: {len(form_data.get("__VIEWSTATE", ""))}')
        log(f'POST __EVENTVALIDATION length: {len(form_data.get("__EVENTVALIDATION", ""))}')

        response = requests.post(
            url,
            data=form_data,
            headers={
                **BROWSER_HEADERS,
                'Cookie': self._cookie_header(),
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-MicrosoftAjax': 'Delta=true',
                'X-Requested-With': 'XMLHttpRequest',
            },
            timeout=30,
            allow_redirects=False,
        )
        log(f'POST Response: {response.status_code}, body length: {len(response.text)} chars')
        log(f'POST Response headers: {dict(response.headers)}')

        if response.status_code == 302:
            location = response.headers.get('Location', '')
            log(f'POST Redirect to: {location}')
            raise SessionExpiredError('Session expired during POST')

        text = response.text
        if 'pageRedirect' in text:
            log(f'pageRedirect detected! Response preview: {text[:500]}')
            raise SessionExpiredError('Session expired (server redirected)')

        # Log delta response summary
        log(f'POST response preview: {text[:300]}')

        self._update_cookies_from_response(response)
        self.save_cookies()
        return self._parse_delta_response(text)

    @staticmethod
    def _parse_delta_response(text):
        """Parse ASP.NET AJAX delta format: length|type|id|content|"""
        parts = []
        pos = 0
        while pos < len(text):
            pipe1 = text.find('|', pos)
            if pipe1 == -1:
                break
            try:
                length = int(text[pos:pipe1])
            except ValueError:
                break
            pos = pipe1 + 1

            pipe2 = text.find('|', pos)
            if pipe2 == -1:
                break
            part_type = text[pos:pipe2]
            pos = pipe2 + 1

            pipe3 = text.find('|', pos)
            if pipe3 == -1:
                break
            part_id = text[pos:pipe3]
            pos = pipe3 + 1

            content = text[pos:pos + length]
            pos = pos + length + 1

            parts.append({'type': part_type, 'id': part_id, 'content': content})

        log(f'Parsed {len(parts)} delta parts:')
        for p in parts:
            log(f'  type={p["type"]} id={p["id"]} content_length={len(p["content"])}')
        return parts

    @staticmethod
    def _extract_hidden_fields(soup):
        """Extract all hidden input fields from a page."""
        fields = {}
        for inp in soup.find_all('input', type='hidden'):
            name = inp.get('name')
            value = inp.get('value', '')
            if name:
                fields[name] = value
        log(f'Extracted {len(fields)} hidden fields')
        return fields

    @staticmethod
    def _extract_delta_hidden_fields(delta_parts):
        """Extract updated hidden fields from a delta response."""
        fields = {}
        for part in delta_parts:
            if part['type'] == 'hiddenField':
                fields[part['id']] = part['content']
        return fields

    @staticmethod
    def _to_telerik_date(date_str):
        """Convert 'M/D/YYYY h:mm AM' to 'YYYY-MM-DD-HH-MM-SS' for Telerik."""
        dt = datetime.strptime(date_str, '%m/%d/%Y %I:%M %p')
        return dt.strftime('%Y-%m-%d-%H-%M-%S')

    @staticmethod
    def _to_client_state(date_str):
        """Build Telerik dateInput ClientState JSON."""
        dt = datetime.strptime(date_str, '%m/%d/%Y %I:%M %p')
        telerik = dt.strftime('%Y-%m-%d-%H-%M-%S')
        return json.dumps({
            'enabled': True,
            'emptyMessage': '',
            'validationText': telerik,
            'valueAsString': telerik,
            'minDateStr': '1980-01-01-00-00-00',
            'maxDateStr': '2099-12-30-00-00-00',
            'lastSetTextBoxValue': date_str,
        })

    @staticmethod
    def _parse_transaction_rows(html):
        """Parse transaction rows from HTML, filtering out pager/header junk."""
        soup = BeautifulSoup(html, 'html.parser')
        transactions = []
        for tr in soup.find_all('tr'):
            cells = tr.find_all('td')
            if len(cells) < 3:
                continue

            row = [cell.get_text(strip=True) for cell in cells]

            if row[0] and re.match(r'^\d{1,2}/\d{1,2}/\d{4}', row[0]):
                transactions.append({
                    'date': row[0],
                    'account': row[1],
                    'location': row[3],
                    'type': row[4],
                    'amount': row[5],
                })
        log(f'Parsed {len(transactions)} transaction rows from HTML')
        return transactions

    def get_balance(self):
        """Fetch account balances from the Account Summary page."""
        log('=== get_balance() START ===')
        try:
            html = self._fetch_page(f'{BASE_URL}/AccountSummary.aspx')
            soup = BeautifulSoup(html, 'html.parser')

            accounts = []
            account_els = soup.select('.account')
            log(f'Found {len(account_els)} .account elements')

            for el in account_els:
                name_el = el.select_one('.accountName')
                balance_el = el.select_one('.accountBalance span')
                status_el = el.select_one('.accountStatus')

                name = name_el.get_text(strip=True) if name_el else ''

                if balance_el:
                    balance = balance_el.get_text(strip=True)
                    log(f'  Account: {name} = {balance}')
                    accounts.append({'name': name, 'balance': balance})
                elif status_el:
                    status = status_el.get_text(strip=True)
                    log(f'  Account: {name} = {status}')
                    accounts.append({'name': name, 'balance': status})

            log(f'=== get_balance() SUCCESS: {len(accounts)} accounts ===')
            return {
                'accounts': accounts,
                'timestamp': datetime.now().isoformat(),
                'status': 'success',
            }

        except SessionExpiredError:
            log('=== get_balance() FAILED: session expired ===')
            return {'error': 'session_expired'}
        except Exception as e:
            log(f'=== get_balance() FAILED: {e} ===')
            import traceback
            traceback.print_exc()
            return {'error': str(e)}

    def get_transactions(self, begin_date=None, end_date=None):
        """Fetch transaction history. Dates in 'M/D/YYYY h:mm AM' format, or None for defaults."""
        log(f'=== get_transactions() START (begin={begin_date}, end={end_date}) ===')
        try:
            html = self._fetch_page(f'{BASE_URL}/AccountTransaction.aspx')
            soup = BeautifulSoup(html, 'html.parser')

            hidden = self._extract_hidden_fields(soup)

            # Get default dropdown values
            account_select = soup.find('select', id='MainContent_Accounts')
            account_val = account_select.find('option', selected=True) if account_select else None
            account_val = account_val['value'] if account_val else 'eabaee3a-1e38-448b-9470-4ffd85e666ce'
            log(f'Account dropdown value: {account_val}')

            trans_select = soup.find('select', id='MainContent_TransactionType')
            trans_val = trans_select.find('option', selected=True) if trans_select else None
            trans_val = trans_val['value'] if trans_val else 'eabaee3a-1e38-448b-9470-4ffd85e666ce'
            log(f'Transaction type dropdown value: {trans_val}')

            # Resolve dates
            begin_input = soup.find('input', {'name': 'ctl00$MainContent$BeginRadDateTimePicker$dateInput'})
            end_input = soup.find('input', {'name': 'ctl00$MainContent$EndRadDateTimePicker$dateInput'})
            begin_display = begin_date or (begin_input.get('value', '') if begin_input else '')
            end_display = end_date or (end_input.get('value', '') if end_input else '')
            log(f'Date range: {begin_display} -> {end_display}')

            use_custom = begin_date and end_date
            if use_custom:
                begin_telerik = self._to_telerik_date(begin_date)
                end_telerik = self._to_telerik_date(end_date)
                begin_cs = self._to_client_state(begin_date)
                end_cs = self._to_client_state(end_date)
                log(f'Using custom dates: {begin_telerik} -> {end_telerik}')
            else:
                begin_telerik = hidden.get('ctl00_MainContent_BeginRadDateTimePicker', '')
                end_telerik = hidden.get('ctl00_MainContent_EndRadDateTimePicker', '')
                begin_cs = hidden.get('ctl00_MainContent_BeginRadDateTimePicker_dateInput_ClientState', '')
                end_cs = hidden.get('ctl00_MainContent_EndRadDateTimePicker_dateInput_ClientState', '')
                log(f'Using default dates from page: {begin_telerik} -> {end_telerik}')

            form_data = {
                'RadScriptManager1_TSM': hidden.get('RadScriptManager1_TSM', ''),
                '__EVENTTARGET': 'ctl00$MainContent$ContinueButton',
                '__EVENTARGUMENT': '',
                '__VIEWSTATE': hidden.get('__VIEWSTATE', ''),
                '__VIEWSTATEGENERATOR': hidden.get('__VIEWSTATEGENERATOR', ''),
                '__SCROLLPOSITIONX': '0',
                '__SCROLLPOSITIONY': '0',
                '__VIEWSTATEENCRYPTED': '',
                '__EVENTVALIDATION': hidden.get('__EVENTVALIDATION', ''),
                'ctl00$MainContent$Accounts': account_val,
                'ctl00$MainContent$TransactionType': trans_val,
                'ctl00$MainContent$BeginRadDateTimePicker': begin_telerik,
                'ctl00$MainContent$BeginRadDateTimePicker$dateInput': begin_display,
                'ctl00_MainContent_BeginRadDateTimePicker_dateInput_ClientState': begin_cs,
                'ctl00_MainContent_BeginRadDateTimePicker_calendar_SD': hidden.get('ctl00_MainContent_BeginRadDateTimePicker_calendar_SD', '[]'),
                'ctl00_MainContent_BeginRadDateTimePicker_calendar_AD': hidden.get('ctl00_MainContent_BeginRadDateTimePicker_calendar_AD', ''),
                'ctl00_MainContent_BeginRadDateTimePicker_ClientState': hidden.get('ctl00_MainContent_BeginRadDateTimePicker_ClientState', ''),
                'ctl00_MainContent_BeginRadDateTimePicker_timeView_ClientState': hidden.get('ctl00_MainContent_BeginRadDateTimePicker_timeView_ClientState', ''),
                'ctl00$MainContent$EndRadDateTimePicker': end_telerik,
                'ctl00$MainContent$EndRadDateTimePicker$dateInput': end_display,
                'ctl00_MainContent_EndRadDateTimePicker_dateInput_ClientState': end_cs,
                'ctl00_MainContent_EndRadDateTimePicker_calendar_SD': hidden.get('ctl00_MainContent_EndRadDateTimePicker_calendar_SD', '[]'),
                'ctl00_MainContent_EndRadDateTimePicker_calendar_AD': hidden.get('ctl00_MainContent_EndRadDateTimePicker_calendar_AD', ''),
                'ctl00_MainContent_EndRadDateTimePicker_ClientState': hidden.get('ctl00_MainContent_EndRadDateTimePicker_ClientState', ''),
                'ctl00_MainContent_EndRadDateTimePicker_timeView_ClientState': hidden.get('ctl00_MainContent_EndRadDateTimePicker_timeView_ClientState', ''),
                'ctl00$MainContent$AmountRangeFrom': '',
                'ctl00_MainContent_AmountRangeFrom_ClientState': hidden.get('ctl00_MainContent_AmountRangeFrom_ClientState', ''),
                'ctl00$MainContent$AmountRangeTo': '',
                'ctl00_MainContent_AmountRangeTo_ClientState': hidden.get('ctl00_MainContent_AmountRangeTo_ClientState', ''),
                'ctl00$MainContent$Location': '',
                'ctl00$RadScriptManager1': 'ctl00$MainContent$ctl00$MainContent$ActionPanelPanel|ctl00$MainContent$ContinueButton',
                '__ASYNCPOST': 'true',
            }

            ncform = hidden.get('__ncforminfo')
            if ncform:
                form_data['__ncforminfo'] = ncform
                log(f'__ncforminfo included, length: {len(ncform)}')

            # Page 1
            log('Submitting search (page 1)...')
            delta_parts = self._ajax_post(f'{BASE_URL}/AccountTransaction.aspx', form_data)
            all_transactions = []

            for part in delta_parts:
                if part['type'] == 'updatePanel' and '<tr' in part['content']:
                    all_transactions.extend(self._parse_transaction_rows(part['content']))

            log(f'Page 1: {len(all_transactions)} transactions')

            # Pagination
            page_num = 2
            while True:
                result_html = ''
                for part in delta_parts:
                    if part['type'] == 'updatePanel' and 'ResultRadGrid' in part['content']:
                        result_html = part['content']

                if not result_html:
                    log(f'No ResultRadGrid panel found, stopping pagination')
                    break

                page_soup = BeautifulSoup(result_html, 'html.parser')
                next_target = None
                for a in page_soup.find_all('a', href=True):
                    if a.get_text(strip=True) == str(page_num) and '__doPostBack' in a['href']:
                        match = re.search(r"__doPostBack\('([^']+)'", a['href'])
                        if match:
                            next_target = match.group(1)
                            break

                if not next_target:
                    log(f'No page {page_num} link found, stopping pagination')
                    break

                log(f'Fetching page {page_num} (target: {next_target})...')
                updated = self._extract_delta_hidden_fields(delta_parts)
                page_form = dict(form_data)
                page_form['__VIEWSTATE'] = updated.get('__VIEWSTATE', form_data['__VIEWSTATE'])
                page_form['__EVENTVALIDATION'] = updated.get('__EVENTVALIDATION', form_data['__EVENTVALIDATION'])
                page_form['__VIEWSTATEGENERATOR'] = updated.get('__VIEWSTATEGENERATOR', form_data['__VIEWSTATEGENERATOR'])
                page_form['__EVENTTARGET'] = next_target
                page_form['__EVENTARGUMENT'] = ''
                page_form['ctl00$RadScriptManager1'] = f'ctl00$MainContent$ctl00$MainContent$ResultPanelPanel|{next_target}'

                if updated.get('__ncforminfo'):
                    page_form['__ncforminfo'] = updated['__ncforminfo']

                delta_parts = self._ajax_post(f'{BASE_URL}/AccountTransaction.aspx', page_form)

                page_transactions = []
                for part in delta_parts:
                    if part['type'] == 'updatePanel' and '<tr' in part['content']:
                        page_transactions.extend(self._parse_transaction_rows(part['content']))

                if not page_transactions:
                    log(f'Page {page_num} returned 0 transactions, stopping')
                    break

                log(f'Page {page_num}: {len(page_transactions)} transactions')
                all_transactions.extend(page_transactions)
                page_num += 1

            log(f'=== get_transactions() SUCCESS: {len(all_transactions)} total ===')
            return {
                'transactions': all_transactions,
                'count': len(all_transactions),
                'begin_date': begin_display,
                'end_date': end_display,
                'timestamp': datetime.now().isoformat(),
                'status': 'success',
            }

        except SessionExpiredError:
            log('=== get_transactions() FAILED: session expired ===')
            return {'error': 'session_expired'}
        except Exception as e:
            log(f'=== get_transactions() FAILED: {e} ===')
            import traceback
            traceback.print_exc()
            return {'error': str(e)}


if __name__ == '__main__':
    scraper = DiningBalanceScraper()

    print('\n--- BALANCES ---')
    balances = scraper.get_balance()
    if balances.get('status') == 'success':
        for a in balances['accounts']:
            print(f"  {a['name']}: {a['balance']}")
    else:
        print(f"  Error: {balances.get('error')}")

    print('\n--- TRANSACTIONS ---')
    txns = scraper.get_transactions()
    if txns.get('status') == 'success':
        for t in txns['transactions']:
            print(f"  {t['date']} | {t['account']} | {t['location']} | {t['type']} | {t['amount']}")
        print(f"\n  Total: {txns['count']} transactions")
    else:
        print(f"  Error: {txns.get('error')}")

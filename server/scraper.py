import requests
import pickle
import os
import re
import json
import base64
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urlencode

BASE_URL = 'https://eacct-buzzcard-sp.transactcampus.com/buzzcard'

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}


class SessionExpiredError(Exception):
    pass


class DiningBalanceScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        self.cookies_file = 'cookies.pkl'
        self.load_cookies()

    def load_cookies(self):
        """Load cookies from file, falling back to INITIAL_COOKIES env var."""
        # Try cookies.pkl first
        if os.path.exists(self.cookies_file):
            try:
                with open(self.cookies_file, 'rb') as f:
                    cookies = pickle.load(f)
                for name, value in cookies.items():
                    self.session.cookies.set(name, value)
                print(f'[{datetime.now()}] Loaded cookies from {self.cookies_file}')
                return
            except Exception as e:
                print(f'[{datetime.now()}] Failed to load {self.cookies_file}: {e}')

        # Fallback to INITIAL_COOKIES env var (base64 encoded JSON)
        env_cookies = os.environ.get('INITIAL_COOKIES')
        if env_cookies:
            try:
                cookie_data = json.loads(base64.b64decode(env_cookies))
                # Support both formats: plain dict or Playwright storageState
                if isinstance(cookie_data, dict) and 'cookies' in cookie_data:
                    # Playwright storageState format
                    for c in cookie_data['cookies']:
                        if 'eacct-buzzcard-sp.transactcampus.com' in c.get('domain', ''):
                            self.session.cookies.set(c['name'], c['value'])
                elif isinstance(cookie_data, dict):
                    # Plain {name: value} dict
                    for name, value in cookie_data.items():
                        self.session.cookies.set(name, value)
                self.save_cookies()
                print(f'[{datetime.now()}] Loaded cookies from INITIAL_COOKIES env var')
                return
            except Exception as e:
                print(f'[{datetime.now()}] Failed to parse INITIAL_COOKIES: {e}')

        print(f'[{datetime.now()}] No cookies found')

    def save_cookies(self):
        """Save current session cookies to file."""
        cookies = {}
        for cookie in self.session.cookies:
            cookies[cookie.name] = cookie.value
        with open(self.cookies_file, 'wb') as f:
            pickle.dump(cookies, f)
        print(f'[{datetime.now()}] Saved cookies to {self.cookies_file}')

    def _fetch_page(self, url):
        """GET a page and check for session expiry."""
        response = self.session.get(url, timeout=15, allow_redirects=False)

        if response.status_code == 302:
            location = response.headers.get('Location', '')
            if 'login' in location.lower() or 'cas' in location.lower() or 'sso' in location.lower():
                raise SessionExpiredError('Session expired')
            raise Exception(f'Redirected to: {location}')

        if response.status_code != 200:
            raise Exception(f'Unexpected status: {response.status_code}')

        self.save_cookies()
        return response.text

    def _ajax_post(self, url, form_data):
        """POST an ASP.NET AJAX async postback."""
        response = self.session.post(
            url,
            data=form_data,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-MicrosoftAjax': 'Delta=true',
                'X-Requested-With': 'XMLHttpRequest',
            },
            timeout=30,
            allow_redirects=False,
        )

        if response.status_code == 302:
            raise SessionExpiredError('Session expired during POST')

        text = response.text
        if 'pageRedirect' in text:
            raise SessionExpiredError('Session expired (server redirected)')

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

            # Only include rows that have a date pattern in the first cell
            if row[0] and re.match(r'^\d{1,2}/\d{1,2}/\d{4}', row[0]):
                transactions.append({
                    'date': row[0],
                    'account': row[1],
                    'location': row[3],
                    'type': row[4],
                    'amount': row[5],
                })
        return transactions

    def get_balance(self):
        """Fetch account balances from the Account Summary page."""
        try:
            html = self._fetch_page(f'{BASE_URL}/AccountSummary.aspx')
            soup = BeautifulSoup(html, 'html.parser')

            accounts = []
            for el in soup.select('.account'):
                name_el = el.select_one('.accountName')
                balance_el = el.select_one('.accountBalance span')
                status_el = el.select_one('.accountStatus')

                name = name_el.get_text(strip=True) if name_el else ''

                if balance_el:
                    accounts.append({'name': name, 'balance': balance_el.get_text(strip=True)})
                elif status_el:
                    accounts.append({'name': name, 'balance': status_el.get_text(strip=True)})

            return {
                'accounts': accounts,
                'timestamp': datetime.now().isoformat(),
                'status': 'success',
            }

        except SessionExpiredError:
            return {'error': 'session_expired'}
        except Exception as e:
            return {'error': str(e)}

    def get_transactions(self, begin_date=None, end_date=None):
        """Fetch transaction history. Dates in 'M/D/YYYY h:mm AM' format, or None for defaults."""
        try:
            html = self._fetch_page(f'{BASE_URL}/AccountTransaction.aspx')
            soup = BeautifulSoup(html, 'html.parser')

            hidden = self._extract_hidden_fields(soup)

            # Get default dropdown values
            account_select = soup.find('select', id='MainContent_Accounts')
            account_val = account_select.find('option', selected=True) if account_select else None
            account_val = account_val['value'] if account_val else 'eabaee3a-1e38-448b-9470-4ffd85e666ce'

            trans_select = soup.find('select', id='MainContent_TransactionType')
            trans_val = trans_select.find('option', selected=True) if trans_select else None
            trans_val = trans_val['value'] if trans_val else 'eabaee3a-1e38-448b-9470-4ffd85e666ce'

            # Resolve dates
            begin_input = soup.find('input', {'name': 'ctl00$MainContent$BeginRadDateTimePicker$dateInput'})
            end_input = soup.find('input', {'name': 'ctl00$MainContent$EndRadDateTimePicker$dateInput'})
            begin_display = begin_date or (begin_input.get('value', '') if begin_input else '')
            end_display = end_date or (end_input.get('value', '') if end_input else '')

            use_custom = begin_date and end_date
            if use_custom:
                begin_telerik = self._to_telerik_date(begin_date)
                end_telerik = self._to_telerik_date(end_date)
                begin_cs = self._to_client_state(begin_date)
                end_cs = self._to_client_state(end_date)
            else:
                begin_telerik = hidden.get('ctl00_MainContent_BeginRadDateTimePicker', '')
                end_telerik = hidden.get('ctl00_MainContent_EndRadDateTimePicker', '')
                begin_cs = hidden.get('ctl00_MainContent_BeginRadDateTimePicker_dateInput_ClientState', '')
                end_cs = hidden.get('ctl00_MainContent_EndRadDateTimePicker_dateInput_ClientState', '')

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

            # Page 1
            delta_parts = self._ajax_post(f'{BASE_URL}/AccountTransaction.aspx', form_data)
            all_transactions = []

            for part in delta_parts:
                if part['type'] == 'updatePanel' and '<tr' in part['content']:
                    all_transactions.extend(self._parse_transaction_rows(part['content']))

            # Pagination
            page_num = 2
            while True:
                result_html = ''
                for part in delta_parts:
                    if part['type'] == 'updatePanel' and 'ResultRadGrid' in part['content']:
                        result_html = part['content']

                if not result_html:
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
                    break

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
                    break

                all_transactions.extend(page_transactions)
                page_num += 1

            return {
                'transactions': all_transactions,
                'count': len(all_transactions),
                'begin_date': begin_display,
                'end_date': end_display,
                'timestamp': datetime.now().isoformat(),
                'status': 'success',
            }

        except SessionExpiredError:
            return {'error': 'session_expired'}
        except Exception as e:
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

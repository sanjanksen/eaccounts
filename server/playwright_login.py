"""
GT SSO + Duo 2FA login via headless Chromium (Playwright).

Navigates a real browser through the full login chain:
  1. eAccounts → CAS login form → fill credentials
  2. Duo push prompt → wait for approval
  3. Redirect back to eAccounts → extract session cookies
"""

from datetime import datetime
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


EACCOUNTS_URL = 'https://eacct-buzzcard-sp.transactcampus.com/buzzcard/AccountSummary.aspx'


class LoginError(Exception):
    pass


def log(msg):
    print(f'[{datetime.now()}] [playwright_login] {msg}', flush=True)


def _is_eaccounts(url):
    """Check if the URL hostname is actually eAccounts (not just in a query param)."""
    return 'transactcampus.com' in urlparse(url).netloc


def playwright_login(username: str, password: str, timeout_ms: int = 90000) -> tuple:
    """
    Perform full GT SSO + Duo login using a headless browser.

    Args:
        username: GT username (e.g. 'gburdell3')
        password: GT password
        timeout_ms: Max time in ms to wait for Duo approval (default 90s)

    Returns:
        (eaccounts_cookies, all_cookies) where:
        - eaccounts_cookies: {name: value} for transactcampus.com only
        - all_cookies: [{name, value, domain, path}, ...] for all domains

    Raises:
        LoginError on any failure
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()

            # Phase 1: Navigate to eAccounts (redirects to CAS)
            log(f'Navigating to {EACCOUNTS_URL}...')
            page.goto(EACCOUNTS_URL, wait_until='networkidle', timeout=30000)
            log(f'Landed on: {page.url}')

            # Phase 2: Fill CAS login form
            try:
                page.wait_for_selector('#username', timeout=15000)
            except PlaywrightTimeout:
                # Check if we're already on eAccounts (session still valid)
                if _is_eaccounts(page.url):
                    log('Already logged in — session is still valid')
                    return _extract_cookies(context)
                raise LoginError(f'CAS login form not found. Landed on: {page.url}')

            log('Found CAS login form, filling credentials...')
            page.fill('#username', username)
            page.fill('#password', password)
            page.click('button[type="submit"], input[type="submit"]')
            log('Credentials submitted, waiting for response...')

            # Check for invalid credentials
            page.wait_for_load_state('networkidle', timeout=15000)

            error_el = page.query_selector('#msg.errors, .alert-danger, #status')
            if error_el:
                error_text = error_el.inner_text()
                if 'invalid' in error_text.lower() or 'incorrect' in error_text.lower() or 'failed' in error_text.lower():
                    raise LoginError(f'Invalid GT credentials: {error_text.strip()}')

            log(f'After CAS submit: {page.url}')

            # Phase 3: Wait for Duo and then eAccounts
            # Duo auto-pushes by default. A "Skip for now" button may appear
            # (e.g. device management prompt) — click it if so.
            log(f'Waiting for Duo approval (up to {timeout_ms // 1000}s)...')
            import time
            deadline = time.time() + timeout_ms / 1000
            duo_code_logged = False
            while time.time() < deadline:
                # Already redirected to eAccounts?
                if _is_eaccounts(page.url):
                    break

                # Try to read the Duo verification code from the page
                if not duo_code_logged and 'duosecurity.com' in page.url:
                    try:
                        # Try known selectors for the Duo verification code
                        code_el = page.query_selector('[data-testid="verification-code"], .verification-code, .duo-code, #auth-view-wrapper h2')
                        if code_el:
                            code_text = code_el.inner_text().strip()
                            if code_text:
                                log(f'========== DUO VERIFICATION CODE: {code_text} ==========')
                                duo_code_logged = True
                        else:
                            # Fallback: log all visible large text on the page
                            # (the code is usually displayed prominently)
                            body_text = page.inner_text('body')
                            log(f'Duo page text: {body_text[:500]}')
                            duo_code_logged = True
                    except Exception:
                        pass

                # Click through Duo interstitial buttons if they appear.
                # Clicking may trigger a navigation (SAML redirect chain),
                # which destroys the execution context — that's fine, just
                # wait for the navigation to settle.
                try:
                    for label in ["Yes, this is my device", "Skip", "skip for now"]:
                        btn = page.query_selector(f'button:has-text("{label}")')
                        if btn:
                            log(f'Found "{label}" button on Duo page — clicking it')
                            btn.click()
                            page.wait_for_load_state('networkidle', timeout=15000)
                            break
                except Exception as e:
                    log(f'Navigation during button click (expected): {e}')
                    page.wait_for_load_state('networkidle', timeout=15000)

                # Wait a bit before checking again
                try:
                    page.wait_for_url(lambda u: _is_eaccounts(u), timeout=3000)
                    break
                except PlaywrightTimeout:
                    pass

            if not _is_eaccounts(page.url):
                raise LoginError(
                    f'Timed out waiting for Duo approval after {timeout_ms // 1000}s. '
                    f'Push may have been denied or ignored. Current URL: {page.url}'
                )

            # Wait for the page to fully load so cookies are set
            page.wait_for_load_state('networkidle', timeout=15000)
            log(f'Login complete! Landed on: {page.url}')

            # Phase 4: Extract cookies
            return _extract_cookies(context)

        finally:
            browser.close()


def _extract_cookies(context) -> tuple:
    """Extract cookies from the browser context.

    Returns:
        (eaccounts_cookies, all_cookies) where:
        - eaccounts_cookies: {name: value} for transactcampus.com only
        - all_cookies: [{name, value, domain, path}, ...] for everything (SSO, Duo, eAccounts)
    """
    browser_cookies = context.cookies()
    eaccounts_cookies = {}
    all_cookies = []
    for c in browser_cookies:
        all_cookies.append({
            'name': c['name'],
            'value': c['value'],
            'domain': c['domain'],
            'path': c.get('path', '/'),
        })
        if 'transactcampus.com' in c['domain']:
            eaccounts_cookies[c['name']] = c['value']
            log(f'Cookie: {c["name"]} = {c["value"][:50]}...')

    if not eaccounts_cookies:
        log('No transactcampus.com cookies found. All cookies:')
        for c in browser_cookies:
            log(f'  {c["domain"]} / {c["name"]}')

    log(f'Extracted {len(eaccounts_cookies)} eAccounts cookies, {len(all_cookies)} total cookies')
    return eaccounts_cookies, all_cookies

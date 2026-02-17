import os
import pickle
import time
import threading
from datetime import datetime
from flask import Flask, jsonify, request
from scraper import DiningBalanceScraper
from playwright_login import playwright_login, LoginError

app = Flask(__name__)

KEEPALIVE_INTERVAL = 900  # 15 minutes


def keepalive_loop():
    print(f'[{datetime.now()}] Keep-alive thread starting...')
    while True:
        time.sleep(KEEPALIVE_INTERVAL)
        try:
            scraper = DiningBalanceScraper()
            print(f'[{datetime.now()}] Keep-alive: refreshing session...')
            result = scraper.get_balance()

            if result.get('error') == 'session_expired':
                print(f'[{datetime.now()}] Keep-alive: SESSION EXPIRED')
            elif result.get('status') == 'success':
                print(f'[{datetime.now()}] Keep-alive: session refreshed')
                for a in result['accounts']:
                    print(f'  {a["name"]}: {a["balance"]}')
            else:
                print(f'[{datetime.now()}] Keep-alive error: {result.get("error")}')
        except Exception as e:
            print(f'[{datetime.now()}] Keep-alive error: {e}')


@app.route('/api/balance', methods=['GET'])
def get_balance():
    scraper = DiningBalanceScraper()
    result = scraper.get_balance()

    if result.get('error') == 'session_expired':
        return jsonify({'error': 'Session expired — cookies need to be refreshed'}), 401

    if 'error' in result:
        return jsonify(result), 500

    return jsonify(result)


@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    begin_date = request.args.get('begin_date')  # e.g. 2/1/2026 12:00 AM
    end_date = request.args.get('end_date')

    scraper = DiningBalanceScraper()
    result = scraper.get_transactions(begin_date=begin_date, end_date=end_date)

    if result.get('error') == 'session_expired':
        return jsonify({'error': 'Session expired — cookies need to be refreshed'}), 401

    if 'error' in result:
        return jsonify(result), 500

    return jsonify(result)


@app.route('/api/login', methods=['POST'])
def login():
    username = os.environ.get('GT_USERNAME', '')
    password = os.environ.get('GT_PASSWORD', '')

    if not username or not password:
        return jsonify({'error': 'GT_USERNAME and GT_PASSWORD env vars must be set'}), 400

    try:
        eaccounts_cookies, all_cookies = playwright_login(username, password)

        if not eaccounts_cookies:
            return jsonify({'error': 'Login completed but no cookies were returned'}), 500

        # Save eAccounts cookies to cookies.pkl (same format the scraper expects)
        with open('cookies.pkl', 'wb') as f:
            pickle.dump(eaccounts_cookies, f)

        # Save all cookies (SSO, Duo, eAccounts) for SAML session refresh
        with open('sso_cookies.pkl', 'wb') as f:
            pickle.dump(all_cookies, f)

        return jsonify({
            'status': 'success',
            'message': f'Login successful — {len(eaccounts_cookies)} eAccounts + {len(all_cookies)} total cookies saved',
            'cookies_count': len(eaccounts_cookies),
        })

    except LoginError as e:
        return jsonify({'error': str(e)}), 401
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Login failed: {str(e)}'}), 500


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    threading.Thread(target=keepalive_loop, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

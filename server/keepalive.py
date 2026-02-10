import time
import sys
from datetime import datetime
from scraper import DiningBalanceScraper


def keep_alive():
    print(f'[{datetime.now()}] Keep-alive service starting...')

    while True:
        try:
            scraper = DiningBalanceScraper()
            print(f'[{datetime.now()}] Making keep-alive request...')

            result = scraper.get_balance()

            if result.get('error') == 'session_expired':
                print(f'[{datetime.now()}] SESSION EXPIRED — update INITIAL_COOKIES env var and redeploy')
                sys.exit(1)

            if result.get('status') == 'success':
                print(f'[{datetime.now()}] Session refreshed, cookies updated')
                for a in result['accounts']:
                    print(f'  {a["name"]}: {a["balance"]}')
            else:
                print(f'[{datetime.now()}] Error: {result.get("error")}')

        except Exception as e:
            print(f'[{datetime.now()}] Error: {e}')

        print(f'[{datetime.now()}] Sleeping 15 minutes...')
        time.sleep(900)


if __name__ == '__main__':
    keep_alive()

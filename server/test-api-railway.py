import requests

BASE = 'https://eaccounts-production.up.railway.app'

# Health check
print('--- HEALTH CHECK ---')
r = requests.get(f'{BASE}/api/health')
print(f'  Status: {r.status_code}')
print(f'  Response: {r.json()}')

# Balance
print('\n--- BALANCES ---')
r = requests.get(f'{BASE}/api/balance')
print(f'  Status: {r.status_code}')
data = r.json()
if data.get('status') == 'success':
    for a in data['accounts']:
        print(f"  {a['name']}: {a['balance']}")
else:
    print(f"  Error: {data.get('error')}")

# Transactions (default dates)
print('\n--- TRANSACTIONS ---')
r = requests.get(f'{BASE}/api/transactions', timeout=60)
print(f'  Status: {r.status_code}')
data = r.json()
if data.get('status') == 'success':
    for t in data['transactions']:
        print(f"  {t['date']} | {t['account']} | {t['location']} | {t['type']} | {t['amount']}")
    print(f"\n  Total: {data['count']} transactions")
else:
    print(f"  Error: {data.get('error')}")

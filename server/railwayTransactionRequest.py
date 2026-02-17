import requests

BASE = 'https://eaccounts-production.up.railway.app'

print('--- BALANCE ---')
resp = requests.get(f'{BASE}/api/balance', timeout=60)
print(f'Status: {resp.status_code}')
print(resp.json())

print('\n--- TRANSACTIONS ---')
resp = requests.get(f'{BASE}/api/transactions', timeout=60)
print(f'Status: {resp.status_code}')
print(resp.json())

import requests

resp = requests.post('https://eaccounts-production.up.railway.app/api/login', timeout=120)
print(f'Status: {resp.status_code}')
print(f'Response: {resp.json()}')

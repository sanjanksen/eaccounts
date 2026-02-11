"""Test the POST /api/login endpoint."""

import requests
import sys

import os
BASE = os.environ.get("TEST_BASE", "http://localhost:5000")
# Set TEST_BASE=https://eaccounts-production.up.railway.app to test Railway

print("=== Testing POST /api/login ===")
print("This will trigger a Duo push — approve on your phone!\n")

resp = requests.post(f"{BASE}/api/login", timeout=120)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")

if resp.status_code != 200:
    print("\nLogin failed.")
    sys.exit(1)

print("\n=== Testing GET /api/balance ===")
resp = requests.get(f"{BASE}/api/balance", timeout=30)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")

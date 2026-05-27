#!/usr/bin/env python3
import os
import json
from pathlib import Path
from datetime import datetime, timezone

# Load /etc/environment
try:
    with open('/etc/environment') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k, v)
except Exception:
    pass

from plaid.api import plaid_api
from plaid.configuration import Configuration
from plaid.api_client import ApiClient
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest

PLAID_CLIENT_ID = os.environ.get('PLAID_CLIENT_ID', '')
PLAID_SECRET = os.environ.get('PLAID_SECRET', '')

TOKENS_PATH = Path('/root/.openclaw/scripts/plaid/plaid_tokens.json')
OUT_PATH = Path('/root/.openclaw/dashboard/plaid_data.json')

if not TOKENS_PATH.exists():
    raise SystemExit('No plaid_tokens.json found')

tokens = json.loads(TOKENS_PATH.read_text())
if not tokens:
    raise SystemExit('No access tokens stored')

access_token = tokens[-1].get('access_token')
if not access_token:
    raise SystemExit('Missing access token')

configuration = Configuration(
    host='https://production.plaid.com',
    api_key={
        'clientId': PLAID_CLIENT_ID,
        'secret': PLAID_SECRET,
    }
)
api_client = ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

request = AccountsBalanceGetRequest(access_token=access_token)
response = client.accounts_balance_get(request)

accounts = []
for acct in response['accounts']:
    bal = acct.get('balances', {})
    accounts.append({
        'name': acct.get('name') or acct.get('official_name') or 'Unknown',
        'type': str(acct.get('type')) if acct.get('type') is not None else None,
        'subtype': str(acct.get('subtype')) if acct.get('subtype') is not None else None,
        'balance': bal.get('current'),
        'available': bal.get('available'),
        'iso_currency_code': bal.get('iso_currency_code')
    })

payload = {
    'updated': datetime.now(timezone.utc).isoformat(),
    'accounts': accounts
}

OUT_PATH.write_text(json.dumps(payload, indent=2))
print(json.dumps(payload, indent=2))

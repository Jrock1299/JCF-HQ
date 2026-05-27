#!/usr/bin/env python3
"""
Plaid Transaction Sync — pulls income + expense data and writes
/root/.openclaw/dashboard/plaid_transactions.json

Fetches from Jan 1 of the current year so YTD figures are accurate.

Cron (every 6 hours):
  0 */6 * * * /usr/bin/python3 /root/.openclaw/scripts/plaid/sync_plaid_transactions.py >> /root/.openclaw/logs/plaid_tx.log 2>&1
"""
import json
import os
import datetime
from collections import defaultdict
from pathlib import Path

# ── Load /etc/environment (same pattern as sync_plaid.py) ─────────────────
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
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

# ── Config ─────────────────────────────────────────────────────────────────
PLAID_CLIENT_ID = os.environ.get('PLAID_CLIENT_ID', '')
PLAID_SECRET    = os.environ.get('PLAID_SECRET', '')
TOKENS_PATH     = Path('/root/.openclaw/scripts/plaid/plaid_tokens.json')
OUT_PATH        = Path('/root/.openclaw/dashboard/plaid_transactions.json')

# ── Plaid client ────────────────────────────────────────────────────────────
tokens = json.loads(TOKENS_PATH.read_text())
if not tokens:
    raise SystemExit('No access tokens in plaid_tokens.json')
access_token = tokens[-1].get('access_token')

configuration = Configuration(
    host='https://production.plaid.com',
    api_key={'clientId': PLAID_CLIENT_ID, 'secret': PLAID_SECRET},
)
client = plaid_api.PlaidApi(ApiClient(configuration))


# ── Helpers ─────────────────────────────────────────────────────────────────

def safe_get(obj, field, default=None):
    """Dict or attribute access — handles both Plaid SDK return styles."""
    try:
        v = obj.get(field)
        if v is not None:
            return v
    except AttributeError:
        pass
    return getattr(obj, field, default)


def date_to_str(d) -> str:
    if d is None:
        return ''
    if isinstance(d, (datetime.date, datetime.datetime)):
        return d.isoformat()[:10]
    return str(d)[:10]


def get_plaid_category(tx) -> list:
    cats = safe_get(tx, 'category')
    if not cats:
        return []
    return [str(c).lower() for c in cats]


def map_income_category(tx) -> str:
    """Map Plaid categories to simplified income labels."""
    cats = get_plaid_category(tx)
    name = (safe_get(tx, 'name') or '').lower()
    if 'payroll' in cats:
        return 'salary'
    if any(k in name for k in ['payroll', 'direct dep', 'direct deposit']):
        return 'salary'
    if 'transfer' in cats:
        return 'transfer'
    if 'deposit' in cats:
        return 'deposit'
    return 'income'


def is_internal_transfer(tx, debit_index: dict) -> bool:
    """
    Returns True if this credit (income) transaction is an internal
    transfer between Jase's own accounts — i.e., a matching debit of
    the same amount exists in a DIFFERENT account on the same day.

    debit_index: dict keyed by (date_str, rounded_amount) → set of account_ids
    """
    cats = get_plaid_category(tx)
    # Plaid explicitly classifies it as internal
    if 'internal account transfer' in cats:
        return True

    amount  = safe_get(tx, 'amount', 0)       # negative = credit
    acct_id = safe_get(tx, 'account_id', '')
    key     = (date_to_str(safe_get(tx, 'date')), round(abs(amount), 2))

    matching_accounts = debit_index.get(key, set())
    # Internal if a debit of the same amount exists in a different account
    return bool(matching_accounts - {acct_id})


# ── Fetch transactions (paginated) ──────────────────────────────────────────

today      = datetime.date.today()
start_date = datetime.date(today.year, 1, 1)   # Jan 1 → true YTD
end_date   = today

print(f'[plaid-tx] Fetching {start_date} → {end_date}')

all_transactions = []
offset = 0

while True:
    req = TransactionsGetRequest(
        access_token=access_token,
        start_date=start_date,
        end_date=end_date,
        options=TransactionsGetRequestOptions(count=500, offset=offset),
    )
    resp  = client.transactions_get(req)
    batch = resp['transactions']
    total = resp['total_transactions']
    all_transactions.extend(batch)
    print(f'[plaid-tx]   fetched {len(all_transactions)}/{total}')
    if len(all_transactions) >= total:
        break
    offset = len(all_transactions)

print(f'[plaid-tx] Total transactions: {len(all_transactions)}')


# ── Build debit index for internal-transfer detection ───────────────────────
# debit_index: (date_str, abs_amount) → set of account_ids that have a DEBIT

debit_index: dict = defaultdict(set)
for tx in all_transactions:
    amount = safe_get(tx, 'amount', 0)
    if amount > 0:   # debit (money out)
        key = (date_to_str(safe_get(tx, 'date')), round(amount, 2))
        debit_index[key].add(safe_get(tx, 'account_id', ''))


# ── Categorise ──────────────────────────────────────────────────────────────

month_start = datetime.date(today.year, today.month, 1)
year_start  = datetime.date(today.year, 1, 1)

income_transactions = []
income_this_month   = 0.0
income_ytd          = 0.0
expenses_this_month = 0.0

for tx in all_transactions:
    amount   = safe_get(tx, 'amount', 0)     # Plaid: positive=debit, negative=credit
    date_str = date_to_str(safe_get(tx, 'date'))
    name     = safe_get(tx, 'name') or ''

    tx_date = datetime.date.fromisoformat(date_str) if date_str else None
    if not tx_date:
        continue

    if amount < 0:
        # Credit — money coming IN → potential income
        income_amount = abs(amount)

        if is_internal_transfer(tx, debit_index):
            continue   # skip internal transfers between own accounts

        cats = get_plaid_category(tx)
        if 'transfer' in cats and 'payroll' not in cats:
            # Generic transfers that aren't payroll — skip unless clearly external
            # (e.g. Venmo/Zelle receipts are real income; internal ones already filtered above)
            pass  # keep them — internal already filtered

        category_label = map_income_category(tx)

        income_transactions.append({
            'date':     date_str,
            'name':     name,
            'amount':   round(income_amount, 2),
            'type':     'income',
            'category': category_label,
        })

        if tx_date >= month_start:
            income_this_month += income_amount
        if tx_date >= year_start:
            income_ytd += income_amount

    else:
        # Debit — money going OUT → expense
        if tx_date >= month_start:
            # Only skip internal debits from expense totals
            cats = get_plaid_category(tx)
            if 'internal account transfer' not in cats:
                expenses_this_month += amount


# Sort income transactions newest first
income_transactions.sort(key=lambda t: t['date'], reverse=True)


# ── Write output ─────────────────────────────────────────────────────────────

from datetime import timezone
now_ts = datetime.datetime.now(timezone.utc).isoformat()

payload = {
    'updated':            now_ts,
    'income_this_month':  round(income_this_month, 2),
    'income_ytd':         round(income_ytd, 2),
    'expenses_this_month': round(expenses_this_month, 2),
    'transactions':       income_transactions,
}

OUT_PATH.write_text(json.dumps(payload, indent=2))
print(f'[plaid-tx] Done → {OUT_PATH}')
print(f'[plaid-tx]   Income this month: ${income_this_month:.2f}')
print(f'[plaid-tx]   Income YTD:        ${income_ytd:.2f}')
print(f'[plaid-tx]   Expenses this month: ${expenses_this_month:.2f}')
print(f'[plaid-tx]   Income transactions: {len(income_transactions)}')

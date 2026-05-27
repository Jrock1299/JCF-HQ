#!/usr/bin/env python3
import os, json, datetime, sys
from datetime import timezone
import robin_stocks.robinhood as rh
def load_env():
    try:
        with open('/etc/environment') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass

load_env()

OUT_PATH = "/root/.openclaw/dashboard/robinhood_data.json"

USER = os.getenv("ROBINHOOD_USERNAME")
PWD = os.getenv("ROBINHOOD_PASSWORD")
if not USER or not PWD:
    print("Missing ROBINHOOD_USERNAME or ROBINHOOD_PASSWORD in /etc/environment", file=sys.stderr)
    sys.exit(1)

# login - device token stored by robin_stocks in ~/.config/robin_stocks
try:
    rh.login(USER, PWD, expiresIn=86400, store_session=True)
except Exception as e:
    try:
        code = input("Enter Robinhood 2FA code: ").strip()
        rh.login(USER, PWD, expiresIn=86400, store_session=True, mfa_code=code)
    except Exception as e2:
        print(f"Login error: {e2}", file=sys.stderr)
        raise

# helper
now = datetime.datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

# portfolio profile (for total_equity reference)
portfolio = rh.account.load_portfolio_profile() or {}
last_core_equity = safe_float(portfolio.get('last_core_equity'))

# holdings
holdings = rh.account.build_holdings() or {}

# stocks value = sum equity for stock positions
stocks_val = 0.0
trades = []
for sym, h in holdings.items():
    if (h.get('type') or '').lower() != 'stock':
        continue
    eq = safe_float(h.get('equity'))
    stocks_val += eq
    trades.append({
        "date": datetime.datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        "asset": sym,
        "direction": "Long",
        "entry": safe_float(h.get('average_buy_price')),
        "exit": safe_float(h.get('price')),
        "pnl": safe_float(h.get('equity_change')),
        "status": "Open",
        "account": "robinhood"
    })

# options value = sum (qty * avg_open_price * 100) where qty>0
options_val = 0.0
try:
    ops = rh.options.get_open_option_positions() or []
    if isinstance(ops, list):
        for p in ops:
            q = safe_float(p.get('quantity'))
            if q <= 0:
                continue
            avg = safe_float(p.get('average_price'))
            options_val += q * avg * 100
    elif isinstance(ops, dict):
        q = safe_float(ops.get('quantity'))
        if q > 0:
            avg = safe_float(ops.get('average_price'))
            options_val = q * avg * 100
except Exception:
    pass

# Roth IRA value (skip for now)
roth_val = 0.0

# recent trades (last 30 days)
trades = []
cutoff = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=30)

def parse_date(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(timezone.utc)
    except Exception:
        return None

# stock orders (filled)
try:
    orders = rh.orders.get_all_stock_orders() or []
    for o in orders:
        if o.get('state') != 'filled':
            continue
        d = parse_date(o.get('last_transaction_at') or o.get('updated_at') or o.get('created_at'))
        if not d or d < cutoff: continue
        side = o.get('side','buy')
        instr = o.get('instrument')
        sym = o.get('symbol')
        if not sym and instr:
            try:
                sym = rh.stocks.get_symbol_by_url(instr)
            except Exception:
                sym = None
        if not sym and instr:
            sym = instr.split('/')[-2]
        price = safe_float(o.get('average_price'))
        trades.append({
            "date": d.strftime('%Y-%m-%d'),
            "asset": sym or '',
            "direction": "Long" if side=='buy' else "Short",
            "entry": price,
            "exit": price,
            "pnl": 0.0,
            "status": "Closed",
            "account": "robinhood"
        })
except Exception:
    pass

# dedupe by date/asset
seen = set()
uniq = []
for t in trades:
    key = (t['date'], t['asset'], t['direction'])
    if key in seen: continue
    seen.add(key)
    uniq.append(t)

out = {
    "stocks": round(stocks_val,2),
    "options": round(options_val,2),
    "roth_ira": round(roth_val,2),
    "total_equity": round(last_core_equity,2),
    "last_update": now,
    "trades": trades
}

with open(OUT_PATH,'w') as f:
    json.dump(out,f,indent=2)

print(f"Saved {OUT_PATH}")

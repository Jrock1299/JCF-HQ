import json
import os
from datetime import datetime, timezone
from tradelocker import TLAPI

OUTPUT_FILE = "/root/.openclaw/dashboard/tradelocker_trades.json"


def load_env():
    try:
        with open('/etc/environment') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass


load_env()

tl = TLAPI(
    environment="https://live.tradelocker.com",
    username="Febres.mgmt@gmail.com",
    password=os.environ.get("TRADELOCKER_PASS"),
    server="HEROFX",
    log_level="warning"
)

accounts = tl.get_all_accounts()

# Normalize account object
account = {}
try:
    account = accounts.iloc[0].to_dict()
except Exception:
    try:
        account = accounts[0]
    except Exception:
        account = {}

balance = account.get("balance") or account.get("accountBalance") or account.get("equity") or account.get("cash") or 0
pnl = account.get("pnl") or account.get("profit") or account.get("accountPnl") or 0

# Build instrument ID → name map
inst_map = {}
try:
    instruments = tl.get_all_instruments()
    try:
        inst_iter = instruments.to_dict('records')
    except Exception:
        inst_iter = instruments
    for it in inst_iter:
        tid = it.get('tradableInstrumentId')
        name = it.get('name') or it.get('symbol') or it.get('instrument')
        if tid is not None and name:
            inst_map[int(tid)] = str(name)
except Exception:
    inst_map = {}

# Lazy cache: tradableInstrumentId → lotSize (contract multiplier)
# P&L = price_diff × filledQty_in_lots × lotSize
# e.g. SPX500.PRO lotSize=100 means 1 lot = $100/point
_lot_size_cache = {}

def get_lot_size(tid):
    if tid is None:
        return 1.0
    tid_int = int(tid)
    if tid_int not in _lot_size_cache:
        try:
            details = tl.get_instrument_details(tid_int)
            ls = float(details.get('lotSize', 1) or 1) if isinstance(details, dict) else 1.0
            _lot_size_cache[tid_int] = ls
        except Exception:
            _lot_size_cache[tid_int] = 1.0
    return _lot_size_cache[tid_int]

def format_symbol(name):
    if not name:
        return name
    if '/' in name:
        return name
    n = str(name)
    # Convert 6-letter FX/metals (e.g., EURUSD, XAUUSD) to EUR/USD
    if len(n) == 6 and n.isalpha() and n.isupper():
        return f"{n[:3]}/{n[3:]}"
    return n

orders = tl.get_all_orders(lookback_period="30D", history=True)

trades = []
positions_list = []
try:
    orders_iter = orders.to_dict('records')
except Exception:
    orders_iter = orders

def _to_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default

def _to_iso(ts):
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts/1000, tz=timezone.utc).isoformat()
        if isinstance(ts, str) and ts.isdigit():
            return datetime.fromtimestamp(int(ts)/1000, tz=timezone.utc).isoformat()
        return ts
    except Exception:
        return ts

# Group filled orders by positionId and compute P&L
pos_map = {}
for o in orders_iter:
    if str(o.get("status", "")).lower() == "filled":
        pid = o.get("positionId")
        if pid is None:
            continue
        pos_map.setdefault(pid, []).append(o)

computed_trades = []
for pid, lst in pos_map.items():
    if pid is None:
        continue
    if len(lst) < 2:
        continue
    # sort by createdDate
    lst_sorted = sorted(lst, key=lambda x: _to_float(x.get("createdDate", 0)))
    open_o = lst_sorted[0]
    close_orders = lst_sorted[1:]

    open_side = str(open_o.get("side", "")).lower()
    direction = "long" if open_side == "buy" else "short"

    open_avg = _to_float(open_o.get("avgPrice", open_o.get("price", 0)))
    open_qty = _to_float(open_o.get("filledQty", open_o.get("qty", 0)))

    # Get contract multiplier for this instrument (e.g. 100 for SPX500.PRO, 100000 for FX)
    _tid = open_o.get("tradableInstrumentId")
    lot_size = get_lot_size(_tid)

    total_qty = 0.0
    exit_notional = 0.0
    total_pnl = 0.0
    for c in close_orders:
        close_avg = _to_float(c.get("avgPrice", c.get("price", 0)))
        close_qty = _to_float(c.get("filledQty", c.get("qty", 0)))
        if close_qty <= 0:
            continue
        total_qty += close_qty
        exit_notional += close_avg * close_qty
        if direction == "long":
            total_pnl += (close_avg - open_avg) * close_qty * lot_size
        else:
            total_pnl += (open_avg - close_avg) * close_qty * lot_size

    if total_qty <= 0:
        continue

    exit_avg = exit_notional / total_qty if total_qty else 0

    tid = open_o.get("tradableInstrumentId")
    raw_symbol = open_o.get("symbol") or open_o.get("instrument") or (inst_map.get(int(tid)) if tid is not None and str(tid).isdigit() else None)
    symbol = format_symbol(raw_symbol or tid)

    open_date = _to_iso(open_o.get("createdDate"))
    close_date = _to_iso(close_orders[-1].get("createdDate"))

    computed_trades.append({
        "positionId": pid,
        "symbol": symbol,
        "side": direction,
        "entry_price": round(open_avg, 5),
        "exit_price": round(exit_avg, 5),
        "qty": round(total_qty, 6),
        "pnl": round(total_pnl, 2),
        "open_date": open_date,
        "close_date": close_date
    })

# merge with existing manual edits
existing_trades = []
try:
    with open(OUTPUT_FILE, "r") as f:
        existing = json.load(f)
        existing_trades = existing.get("trades", []) if isinstance(existing, dict) else []
except Exception:
    existing_trades = []

manual_by_pos = {t.get("positionId"): t for t in existing_trades if t.get("manual_edit") and t.get("positionId") is not None}
existing_by_pos = {t.get("positionId"): t for t in existing_trades if t.get("positionId") is not None}
existing_no_pos = [t for t in existing_trades if t.get("positionId") is None]

def _nopos_key(t):
    return (
        t.get('symbol'),
        t.get('open_date'),
        t.get('close_date'),
        t.get('side'),
        t.get('qty'),
        t.get('entry_price'),
        t.get('exit_price')
    )

existing_no_pos_map = {}
for t in existing_no_pos:
    k = _nopos_key(t)
    if k in existing_no_pos_map:
        if t.get('manual_edit'):
            existing_no_pos_map[k] = t
    else:
        existing_no_pos_map[k] = t
# Drop trades without positionId to prevent duplicates
existing_no_pos = []

merged_by_pos = dict(existing_by_pos)

# Only add truly NEW trades; preserve manual edits
for t in computed_trades:
    pid = t.get("positionId")
    if pid is None:
        continue
    if pid in manual_by_pos:
        merged_by_pos[pid] = manual_by_pos[pid]
    else:
        merged_by_pos[pid] = t  # always recompute non-manual trades so direction stays correct

merged = existing_no_pos + list(merged_by_pos.values())

# Deduplicate by positionId (keep manual_edit if present)
by_pos = {}
for t in merged:
    pid = t.get("positionId")
    if pid is None:
        continue
    if pid in by_pos:
        if t.get("manual_edit"):
            by_pos[pid] = t
    else:
        by_pos[pid] = t

merged = existing_no_pos + list(by_pos.values())

wins = sum(1 for t in merged if (t.get("pnl", 0) or 0) > 0)
losses = sum(1 for t in merged if (t.get("pnl", 0) or 0) < 0)
trade_count = len(merged)
win_rate = f"{round((wins / trade_count) * 100, 1)}%" if trade_count else "0%"
computed_total_pnl = round(sum(t.get("pnl", 0) for t in merged), 2)

payload = {
    "balance": balance,
    "pnl": computed_total_pnl,
    "wins": wins,
    "losses": losses,
    "win_rate": win_rate,
    "last_sync": datetime.now(timezone.utc).isoformat(),
    "trades": merged
}

with open(OUTPUT_FILE, "w") as f:
    json.dump(payload, f, indent=2)

print(f"Synced {len(merged)} trades. Total P&L: {computed_total_pnl} | Win rate: {win_rate}")

# ── Goat Funded Trader sync (all accounts) ──────────────────────────────

GOAT_OUTPUT_FILE = "/root/.openclaw/dashboard/tradelocker_trades_goat.json"

GOAT_USERNAME = os.environ.get("GOAT_TRADELOCKER_EMAIL") or os.environ.get("GOAT_TRADELOCKER_USER", "febres.mgmt@gmail.com")
GOAT_PASSWORD = os.environ.get("GOAT_TRADELOCKER_PASS")
GOAT_SERVER   = os.environ.get("GOAT_TRADELOCKER_SERVER", "GFTTL")

try:
    if not GOAT_PASSWORD:
        raise RuntimeError("GOAT_TRADELOCKER_PASS env var not set — add to crontab or /etc/environment")

    tl_goat = TLAPI(
        environment="https://demo.tradelocker.com",
        username=GOAT_USERNAME,
        password=GOAT_PASSWORD,
        server=GOAT_SERVER,
        log_level="warning"
    )

    # Get all accounts from the Goat login
    goat_accounts_raw = tl_goat.get_all_accounts()
    goat_accounts_list = []
    try:
        goat_accounts_list = goat_accounts_raw.to_dict('records')
    except Exception:
        try:
            goat_accounts_list = list(goat_accounts_raw)
        except Exception:
            goat_accounts_list = [goat_accounts_raw] if goat_accounts_raw else []

    # Load existing output to preserve manual edits (keyed by positionId)
    existing_by_pos = {}  # key: f"{acct_id}_{positionId}" → trade
    if os.path.exists(GOAT_OUTPUT_FILE):
        try:
            with open(GOAT_OUTPUT_FILE) as f:
                prev_data = json.load(f)
                prev_accounts = prev_data.get("accounts") or []
                for acct in prev_accounts:
                    for t in acct.get("trades", []):
                        if t.get("manual_edit") and t.get("positionId") is not None:
                            key = f"{acct.get('id')}_{t.get('positionId')}"
                            existing_by_pos[key] = t
        except Exception:
            pass

    # Build instrument map for GOAT (tradableInstrumentId → name)
    goat_inst_map = {}
    try:
        goat_instruments = tl_goat.get_all_instruments()
        try:
            goat_inst_iter = goat_instruments.to_dict('records')
        except Exception:
            goat_inst_iter = goat_instruments
        for it in goat_inst_iter:
            tid = it.get('tradableInstrumentId')
            nm = it.get('name') or it.get('symbol') or it.get('instrument')
            if tid is not None and nm:
                goat_inst_map[int(tid)] = str(nm)
    except Exception:
        goat_inst_map = {}

    _goat_lot_cache = {}
    def get_goat_lot_size(tid):
        if tid is None:
            return 1.0
        tid_int = int(tid)
        if tid_int not in _goat_lot_cache:
            try:
                details = tl_goat.get_instrument_details(tid_int)
                ls = float(details.get('lotSize', 1) or 1) if isinstance(details, dict) else 1.0
                _goat_lot_cache[tid_int] = ls
            except Exception:
                _goat_lot_cache[tid_int] = 1.0
        return _goat_lot_cache[tid_int]

    # Sort accounts by id for stable "Eval 100K (N)" numbering
    def _acct_sort_key(a):
        try:
            return int(a.get("id") or a.get("accountId") or 0)
        except Exception:
            return 0
    sorted_accts = sorted(goat_accounts_list, key=_acct_sort_key)

    # Assign display name + type by balance range
    # $90K–$110K  → EVAL 100K (numbered), $20K–$40K → LIVE 25K, fallback → size-based
    eval_100k_idx = 0
    live_25k_idx = 0
    name_type_by_id = {}
    for acct_raw in sorted_accts:
        aid = str(acct_raw.get("id") or acct_raw.get("accountId") or acct_raw.get("account_id") or "")
        bal = float(acct_raw.get("balance") or acct_raw.get("accountBalance") or 0)
        if 90_000 <= bal <= 110_000:
            eval_100k_idx += 1
            name_type_by_id[aid] = (f"GOAT Funded — Eval 100K ({eval_100k_idx})", "EVAL")
        elif 20_000 <= bal < 40_000:
            live_25k_idx += 1
            label = "GOAT Funded — Live 25K" if live_25k_idx == 1 else f"GOAT Funded — Live 25K ({live_25k_idx})"
            name_type_by_id[aid] = (label, "LIVE")
        else:
            size = f"{int(round(bal/1000))}K" if bal >= 1000 else str(int(bal))
            name_type_by_id[aid] = (f"GOAT Funded — {size}", "EVAL")

    accounts_out = []
    for acct_raw in sorted_accts:
        acct_id = str(acct_raw.get("id") or acct_raw.get("accountId") or acct_raw.get("account_id") or "")
        acct_balance = float(
            acct_raw.get("balance") or acct_raw.get("accountBalance") or
            acct_raw.get("equity") or acct_raw.get("cash") or 0
        )
        acct_name, acct_type = name_type_by_id.get(acct_id, (f"Goat Account {acct_id}", "LIVE"))

        # Switch TLAPI to this specific account before fetching orders
        orders_iter = []
        try:
            raw_acc_id = acct_raw.get("id") or acct_raw.get("accountId") or acct_raw.get("account_id")
            raw_acc_num = acct_raw.get("accNum") or acct_raw.get("acc_num")
            if raw_acc_id is not None:
                tl_goat.account_id = int(raw_acc_id)
            if raw_acc_num is not None:
                tl_goat.acc_num = int(raw_acc_num)
            raw = tl_goat.get_all_orders(lookback_period="30D", history=True)
            if hasattr(raw, 'to_dict'):
                orders_iter = raw.to_dict('records')
            elif isinstance(raw, list):
                orders_iter = raw
        except Exception as e:
            print(f"[GOAT:{acct_id}] fetch orders error: {e}")

        # Group filled orders by positionId and compute P&L
        # (same algorithm as HEROFX branch above: first order = open, rest = closes)
        pos_map = {}
        for o in orders_iter:
            if str(o.get("status", "")).lower() != "filled":
                continue
            pid = o.get("positionId")
            if pid is None:
                continue
            pos_map.setdefault(pid, []).append(o)

        trades_out = []
        for pid, lst in pos_map.items():
            if pid is None or len(lst) < 2:
                continue
            lst_sorted = sorted(lst, key=lambda x: _to_float(x.get("createdDate", 0)))
            open_o = lst_sorted[0]
            close_orders = lst_sorted[1:]

            open_side = str(open_o.get("side", "")).lower()
            direction = "long" if open_side == "buy" else "short"

            open_avg = _to_float(open_o.get("avgPrice", open_o.get("price", 0)))
            _tid = open_o.get("tradableInstrumentId")
            lot_size = get_goat_lot_size(_tid)

            total_qty = 0.0
            exit_notional = 0.0
            total_pnl = 0.0
            for c in close_orders:
                close_avg = _to_float(c.get("avgPrice", c.get("price", 0)))
                close_qty = _to_float(c.get("filledQty", c.get("qty", 0)))
                if close_qty <= 0:
                    continue
                total_qty += close_qty
                exit_notional += close_avg * close_qty
                if direction == "long":
                    total_pnl += (close_avg - open_avg) * close_qty * lot_size
                else:
                    total_pnl += (open_avg - close_avg) * close_qty * lot_size

            if total_qty <= 0:
                continue

            exit_avg = exit_notional / total_qty if total_qty else 0

            tid = open_o.get("tradableInstrumentId")
            raw_symbol = open_o.get("symbol") or open_o.get("instrument") or (
                goat_inst_map.get(int(tid)) if tid is not None and str(tid).isdigit() else None
            )
            symbol = format_symbol(raw_symbol or tid)

            open_date = _to_iso(open_o.get("createdDate"))
            close_date = _to_iso(close_orders[-1].get("createdDate"))

            key = f"{acct_id}_{pid}"
            existing = existing_by_pos.get(key, {})
            computed_pnl = round(total_pnl, 2)
            final_pnl = existing.get("pnl") if existing.get("manual_edit") else computed_pnl

            trades_out.append({
                "positionId": pid,
                "symbol": symbol,
                "side": direction,
                "lots": round(total_qty, 6),
                "qty": round(total_qty, 6),
                "entry_price": round(open_avg, 5),
                "exit_price": round(exit_avg, 5),
                "open_price": round(open_avg, 5),
                "close_price": round(exit_avg, 5),
                "open_date": open_date,
                "close_date": close_date,
                "open_time": open_date,
                "close_time": close_date,
                "pnl": final_pnl,
                "source": "GOAT",
                "account_id": acct_id,
                "manual_edit": existing.get("manual_edit", False),
            })

        wins = sum(1 for t in trades_out if (t.get("pnl") or 0) > 0)
        losses = sum(1 for t in trades_out if (t.get("pnl") or 0) < 0)
        count = len(trades_out)
        acct_pnl = round(sum((t.get("pnl") or 0) for t in trades_out), 2)
        accounts_out.append({
            "id": acct_id,
            "name": acct_name,
            "balance": acct_balance,
            "type": acct_type,
            "trades": trades_out,
            "wins": wins,
            "losses": losses,
            "win_rate": f"{round((wins/count)*100,1)}%" if count else "0%",
            "pnl": acct_pnl,
        })
        print(f"[GOAT:{acct_id}] {acct_name} ({acct_type}) — balance={acct_balance}, trades={count}, pnl={acct_pnl}")

    goat_output = {
        "accounts": accounts_out,
        "last_synced": datetime.now(timezone.utc).isoformat(),
    }

    with open(GOAT_OUTPUT_FILE, "w") as f:
        json.dump(goat_output, f, indent=2)

    print(f"[GOAT] Synced {len(accounts_out)} account(s)")

except Exception as e:
    print(f"[GOAT] sync failed: {e}")

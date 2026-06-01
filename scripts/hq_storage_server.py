#!/usr/bin/env python3
"""
JCF HQ Storage Server
Tiny Flask API that persists dashboard data server-side
so balances/stats survive across devices and browsers.
Runs on port 8900, served alongside the dashboard.
"""
from flask import Flask, request, jsonify
import json, os
from datetime import datetime, timezone

app = Flask(__name__)
STORAGE_FILE = '/root/.openclaw/dashboard/hq_userdata.json'

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
}

def load_data():
    if os.path.exists(STORAGE_FILE):
        try:
            return json.load(open(STORAGE_FILE))
        except:
            pass
    return {
        "accounts": {},
        "income_entries": [],
        "trading_accounts": [],
        "basketball": {},
        "last_updated": None
    }

def save_data(data):
    data['last_updated'] = datetime.now(timezone.utc).isoformat()
    with open(STORAGE_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@app.route('/hq/data', methods=['GET', 'OPTIONS'])
def get_data():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    data = load_data()
    return (jsonify(data), 200, CORS_HEADERS)

@app.route('/hq/data', methods=['POST'])
def set_data():
    body = request.get_json(force=True)
    data = load_data()
    # Merge — only update keys that are sent
    for key in ['accounts', 'income_entries', 'trading_accounts', 'basketball']:
        if key in body:
            data[key] = body[key]
    save_data(data)
    return (jsonify({'ok': True, 'last_updated': data['last_updated']}), 200, CORS_HEADERS)

@app.route('/hq/account/<key>', methods=['POST', 'OPTIONS'])
def set_account(key):
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    body = request.get_json(force=True)
    data = load_data()
    data['accounts'][key] = body
    save_data(data)
    return (jsonify({'ok': True}), 200, CORS_HEADERS)

@app.route('/hq/income', methods=['POST', 'OPTIONS'])
def add_income():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    body = request.get_json(force=True)
    data = load_data()
    data['income_entries'].insert(0, body)
    save_data(data)
    return (jsonify({'ok': True}), 200, CORS_HEADERS)

@app.route('/hq/income/<int:entry_id>', methods=['DELETE', 'OPTIONS'])
def delete_income(entry_id):
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    data = load_data()
    data['income_entries'] = [e for e in data['income_entries'] if e.get('id') != entry_id]
    save_data(data)
    return (jsonify({'ok': True}), 200, CORS_HEADERS)

@app.route('/hq/trading-accounts', methods=['POST', 'OPTIONS'])
def add_trading_acct():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    body = request.get_json(force=True)
    data = load_data()
    data['trading_accounts'].append(body)
    save_data(data)
    return (jsonify({'ok': True}), 200, CORS_HEADERS)

@app.route('/hq/basketball', methods=['POST', 'OPTIONS'])
def set_basketball():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    body = request.get_json(force=True)
    data = load_data()
    data['basketball'] = body
    save_data(data)
    return (jsonify({'ok': True}), 200, CORS_HEADERS)

HUB_PATH = "/root/.openclaw/dashboard/agent_hub.json"

def load_hub_data():
    import json
    import os
    if not os.path.exists(HUB_PATH):
        return {"messages": [], "max_messages": 500}
    with open(HUB_PATH, "r") as f:
        return json.load(f)

def save_hub_data(data):
    import json
    import os
    with open(HUB_PATH, "w") as f:
        json.dump(data, f, indent=2)

def add_hub_message(agent, msg_type, message, tags=None, timestamp=None):
    from datetime import datetime, timezone
    data = load_hub_data()
    new_msg = {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "type": msg_type,
        "message": message,
        "tags": tags or []
    }
    data["messages"].append(new_msg)

    # Enforce max_messages limit
    if len(data["messages"]) > data["max_messages"]:
        data["messages"] = data["messages"][-data["max_messages"]:]

    save_hub_data(data)
    return new_msg

@app.route('/hq/hub', methods=['POST'])
def add_hub_entry():
    data = request.get_json()
    agent = data.get('agent', 'unknown')
    msg_type = data.get('type', 'log')
    message = data.get('message', '')
    tags = data.get('tags', [])
    timestamp = data.get('timestamp')
    if message:
        add_hub_message(agent, msg_type, message, tags, timestamp=timestamp)
    return jsonify({'ok': True})

@app.route('/hq/hub', methods=['GET'])
def get_hub_entries():
    data = load_hub_data()
    msgs = data.get('messages', [])
    try:
        limit = int(request.args.get('limit', 0))
    except Exception:
        limit = 0
    # newest first
    msgs = list(reversed(msgs))
    if limit and limit > 0:
        msgs = msgs[:limit]
    return (jsonify(msgs), 200, CORS_HEADERS)

@app.route('/hq/hub/collab', methods=['POST', 'OPTIONS'])
def hub_collab():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    import subprocess, threading
    body = request.get_json(force=True) or {}
    question = (body.get('question') or '').strip()
    if not question:
        return (jsonify({'ok': False, 'error': 'missing question'}), 400, CORS_HEADERS)
    # Save the question immediately so it appears in the feed
    add_hub_message('jase', 'question', question, tags=['collab'])
    # Run hub_collab.py in the background — don't block the response
    def _run():
        try:
            subprocess.run(
                ['python3', '/root/.openclaw/scripts/hub_collab.py', question],
                timeout=180,
            )
        except Exception as e:
            print(f'[collab] background error: {e}')
    threading.Thread(target=_run, daemon=True).start()
    return (jsonify({'ok': True, 'status': 'processing'}), 200, CORS_HEADERS)

@app.route('/hq/hub/stats', methods=['GET'])
def get_hub_stats():
    data = load_hub_data()
    total_messages = len(data.get('messages', []))
    agent_counts = {}
    type_counts = {}
    for msg in data.get('messages', []):
        agent_counts[msg.get('agent', 'unknown')] = agent_counts.get(msg.get('agent', 'unknown'), 0) + 1
        type_counts[msg.get('type', 'unknown')] = type_counts.get(msg.get('type', 'unknown'), 0) + 1
    return (jsonify({
        'total_messages': total_messages,
        'agent_counts': agent_counts,
        'type_counts': type_counts,
        'max_messages': data.get('max_messages', 500)
    }), 200, CORS_HEADERS)

# TradeLocker manual edits
TL_FILE = '/root/.openclaw/dashboard/tradelocker_trades.json'

@app.route('/hq/tradelocker/trades/<int:idx>', methods=['PATCH', 'OPTIONS'])
def patch_tradelocker_trade(idx):
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    body = request.get_json(force=True) or {}
    try:
        with open(TL_FILE, 'r') as f:
            data = json.load(f)
    except Exception:
        return (jsonify({'ok': False, 'error': 'missing'}), 404, CORS_HEADERS)
    trades = data.get('trades', [])
    if idx < 0 or idx >= len(trades):
        return (jsonify({'ok': False, 'error': 'index'}), 400, CORS_HEADERS)
    t = trades[idx]
    if 'entry_price' in body: t['entry_price'] = body['entry_price']; t['open_price'] = body['entry_price']
    if 'exit_price' in body: t['exit_price'] = body['exit_price']; t['close_price'] = body['exit_price']
    if 'qty' in body: t['qty'] = body['qty']; t['lots'] = body['qty']
    if 'pnl' in body: t['pnl'] = body['pnl']
    if body: t['manual_edit'] = True
    trades[idx] = t
    data['trades'] = trades
    wins = sum(1 for x in trades if (x.get('pnl',0) or 0) > 0)
    losses = sum(1 for x in trades if (x.get('pnl',0) or 0) < 0)
    count = len(trades)
    data['wins'] = wins
    data['losses'] = losses
    data['win_rate'] = f"{round((wins/count)*100,1)}%" if count else '0%'
    data['pnl'] = round(sum((x.get('pnl',0) or 0) for x in trades),2)
    with open(TL_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    return (jsonify({'ok': True}), 200, CORS_HEADERS)


@app.route('/hq/robinhood-holdings', methods=['GET', 'OPTIONS'])
def get_robinhood_holdings():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    path = '/root/.openclaw/dashboard/robinhood_holdings.json'
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return (jsonify(json.load(f)), 200, CORS_HEADERS)
    except Exception as e:
        print(f'[robinhood-holdings] error: {e}')
    return (jsonify({'positions': [], 'total_equity': 0, 'count': 0, 'last_updated': None}), 200, CORS_HEADERS)


@app.route('/hq/tao-daily-change', methods=['GET', 'OPTIONS'])
def get_tao_daily_change():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    tao_path = '/root/.openclaw/dashboard/tao_portfolio.json'
    try:
        if os.path.exists(tao_path):
            with open(tao_path, 'r') as f:
                tao = json.load(f)
            price       = float(tao.get('tao_price_usd', 0) or 0)
            root_tao    = float(tao.get('root_staked_tao', 0) or 0)
            subnet_tao  = sum(float(p.get('current_value_tao', p.get('staked_tao', 0)) or 0)
                             for p in tao.get('subnet_positions', []))
            total_tao   = root_tao + subnet_tao
            usd_value   = total_tao * price
            prev_price  = float(tao.get('previous_price_usd', price) or price)
            daily_change_usd = total_tao * (price - prev_price)
            daily_change_pct = ((price - prev_price) / prev_price * 100) if prev_price else 0
            return (jsonify({
                'staked_tao': round(total_tao, 4),
                'usd_value': round(usd_value, 2),
                'daily_change_usd': round(daily_change_usd, 2),
                'daily_change_pct': round(daily_change_pct, 2),
            }), 200, CORS_HEADERS)
    except Exception as e:
        print(f'[tao-daily-change] error: {e}')
    return (jsonify({'staked_tao': 0, 'usd_value': 0, 'daily_change_usd': 0, 'daily_change_pct': 0}), 200, CORS_HEADERS)


@app.route('/hq/agent-status', methods=['GET', 'OPTIONS'])
def get_agent_status():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    import subprocess
    from datetime import datetime, timezone

    AGENT_SERVICES = {
        'huncho':  'openclaw-gateway.service',
        'jerry':   'jerry.service',
        'phantom': 'phantom.service',
    }

    status = {}

    # Check systemd services
    for agent, service in AGENT_SERVICES.items():
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', service],
                capture_output=True, text=True, timeout=3
            )
            status[agent] = 'active' if result.stdout.strip() == 'active' else 'idle'
        except Exception:
            status[agent] = 'idle'

    # Check last hub message timestamp (within 10 min = active)
    try:
        hub = load_hub_data()
        msgs = hub.get('messages', [])
        now = datetime.now(timezone.utc)
        for msg in msgs:
            agent = (msg.get('agent') or '').lower()
            if not agent or agent in status:
                continue
            try:
                ts = datetime.fromisoformat(msg.get('timestamp', '').replace('Z', '+00:00'))
                elapsed = (now - ts).total_seconds()
                if elapsed < 600:  # 10 minutes
                    status[agent] = 'active'
            except Exception:
                pass
    except Exception as e:
        print(f'[agent-status] hub error: {e}')

    # Default all known agents to idle if not already set
    all_agents = ['huncho', 'blade', 'crisp', 'lens', 'advisor', 'strategist', 'tao',
                  'jerry', 'phantom', 'norman', 'forge', 'lucy', 'victoria']
    for a in all_agents:
        if a not in status:
            status[a] = 'idle'

    return (jsonify(status), 200, CORS_HEADERS)




KRAKEN_DATA_FILE = '/root/.openclaw/dashboard/kraken_data.json'

@app.route('/hq/kraken-holdings', methods=['GET', 'OPTIONS'])
def get_kraken_holdings():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    if not os.path.exists(KRAKEN_DATA_FILE):
        return (jsonify({'error': 'kraken_data.json not found — run sync_kraken.py'}), 404, CORS_HEADERS)
    try:
        with open(KRAKEN_DATA_FILE) as f:
            data = json.load(f)
        return (jsonify(data), 200, CORS_HEADERS)
    except Exception as e:
        return (jsonify({'error': str(e)}), 500, CORS_HEADERS)


@app.route('/hq/api-costs', methods=['GET', 'OPTIONS'])
def get_api_costs():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    import glob as _glob
    from calendar import monthrange

    now           = datetime.now(timezone.utc)
    today         = now.strftime('%Y-%m-%d')
    month         = today[:7]                          # YYYY-MM
    days_in_month = monthrange(now.year, now.month)[1]
    days_elapsed  = max(1, now.day)

    today_breakdown   = {}
    mtd_breakdown     = {}
    today_total       = 0.0
    mtd_total         = 0.0

    cost_files = sorted(_glob.glob('/root/.openclaw/logs/*_api_costs.json'))
    for fpath in cost_files:
        agent_name = os.path.basename(fpath).replace('_api_costs.json', '')
        try:
            with open(fpath) as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                continue
        except Exception:
            continue

        agent_today = 0.0
        agent_mtd   = 0.0
        for entry in entries:
            cost = float(entry.get('cost_usd', 0) or 0)
            date = entry.get('date', '')
            if date == today:
                agent_today += cost
            if date.startswith(month):
                agent_mtd += cost

        today_breakdown[agent_name] = round(agent_today, 4)
        mtd_breakdown[agent_name]   = round(agent_mtd,   4)
        today_total += agent_today
        mtd_total   += agent_mtd

    projected_monthly = round((mtd_total / days_elapsed) * days_in_month, 2)

    return (jsonify({
        'today': {
            'total':     round(today_total, 4),
            'breakdown': today_breakdown,
        },
        'mtd': {
            'total':     round(mtd_total, 4),
            'breakdown': mtd_breakdown,
        },
        'projected_monthly': projected_monthly,
        'last_updated':      now.isoformat(),
    }), 200, CORS_HEADERS)


# ── Agent-specific data endpoints ─────────────────────────────────────

def _serve_json_file(path, fallback):
    """Return file contents as JSON or fallback if missing/error."""
    try:
        if os.path.exists(path):
            with open(path) as f:
                return (jsonify(json.load(f)), 200, CORS_HEADERS)
    except Exception as e:
        print(f'[json-file] {path} error: {e}')
    return (jsonify(fallback), 200, CORS_HEADERS)


@app.route('/hq/jerry-portfolio', methods=['GET', 'OPTIONS'])
def get_jerry_portfolio():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    return _serve_json_file(
        '/root/.openclaw/dashboard/jerry_portfolio.json',
        {'balance': 0, 'total_pnl': 0, 'open_positions': [], 'status': 'unknown'},
    )


@app.route('/hq/phantom-portfolio', methods=['GET', 'OPTIONS'])
def get_phantom_portfolio():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    return _serve_json_file(
        '/root/.openclaw/dashboard/phantom_portfolio.json',
        {'balance': 0, 'total_pnl': 0, 'open_positions': [], 'status': 'unknown'},
    )


@app.route('/hq/victoria-report', methods=['GET', 'OPTIONS'])
def get_victoria_report():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    return _serve_json_file(
        '/root/.openclaw/dashboard/victoria_report.json',
        {},
    )


@app.route('/hq/norman-report', methods=['GET', 'OPTIONS'])
def get_norman_report():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    return _serve_json_file(
        '/root/.openclaw/dashboard/norman_report.json',
        {},
    )


@app.route('/hq/lucy-research', methods=['GET', 'OPTIONS'])
def get_lucy_research():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    return _serve_json_file(
        '/root/.openclaw/dashboard/lucy_research.json',
        {'niches': [], 'research_date': None},
    )


@app.route('/hq/forge-builds', methods=['GET', 'OPTIONS'])
def get_forge_builds():
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    builds_path = '/root/.openclaw/agents/forge/data/build_log.json'
    specs_path  = '/root/.openclaw/agents/forge/data/product_specs.json'
    builds, specs = [], []
    try:
        if os.path.exists(builds_path):
            with open(builds_path) as f:
                builds = json.load(f)
    except Exception as e:
        print(f'[forge-builds] builds error: {e}')
    try:
        if os.path.exists(specs_path):
            with open(specs_path) as f:
                specs = json.load(f)
    except Exception as e:
        print(f'[forge-builds] specs error: {e}')
    return (jsonify({'builds': builds, 'specs': specs}), 200, CORS_HEADERS)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8900, debug=False)

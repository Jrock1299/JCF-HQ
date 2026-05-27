#!/usr/bin/env python3
import json
from datetime import datetime, timezone

def sync_pnl():
    trades_path = '/root/.openclaw/dashboard/agent_trades.json'
    output_path = '/root/.openclaw/dashboard/agent_pnl.json'

    try:
        with open(trades_path, 'r') as f:
            data = json.load(f)
            trades = data.get('trades', [])
    except (FileNotFoundError, json.JSONDecodeError):
        trades = []

    agents = ['crisp', 'blade']
    stats = {agent: {'pnl': 0.0, 'trades': 0, 'wins': 0, 'best': None, 'sessions': set()} for agent in agents}

    for trade in trades:
        agent = trade.get('agent')
        if agent not in agents:
            continue

        pnl = float(trade.get('pnl', trade.get('pnl_usd', 0)) or 0)
        direction = trade.get('direction', '')
        trade_date = trade.get('date')

        stats[agent]['pnl'] += pnl
        if trade_date:
            stats[agent]['sessions'].add(trade_date)

        # Count a trade if direction is set and not 'none'
        if direction and direction != 'none':
            stats[agent]['trades'] += 1
            if pnl > 0:
                stats[agent]['wins'] += 1

        if stats[agent]['best'] is None or pnl > stats[agent]['best']:
            stats[agent]['best'] = pnl

    output_data = {}
    for agent in agents:
        total_trades = stats[agent]['trades']
        wins = stats[agent]['wins']
        win_rate = round((wins / total_trades * 100), 1) if total_trades > 0 else 0
        best = stats[agent]['best'] if stats[agent]['best'] is not None else 0

        output_data[agent] = {
            'pnl': round(stats[agent]['pnl'], 2),
            'trades': total_trades,
            'wr': win_rate,
            'best': round(best, 2),
            'sessions': len(stats[agent]['sessions'])
        }

    output_data['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"Agent P&L synced successfully to {output_path}")
    print(json.dumps(output_data, indent=2))

if __name__ == '__main__':
    sync_pnl()

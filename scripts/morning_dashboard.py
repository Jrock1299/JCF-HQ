import json
import re
import os
import subprocess
from datetime import datetime, timezone, timedelta

OUTPUT_DIR = '/root/.openclaw/dashboard'
os.makedirs(OUTPUT_DIR, exist_ok=True)

CRISP_LOG = '/root/.openclaw/agents/crisp/bot/crisp.log'
BLADE_LOG = '/root/.openclaw/agents/blade/bot/blade.log'
ORACLE_LOG_DIR = '/root/.openclaw/agents/oracle/bot'


def get_yesterday():
    """Returns the previous weekday date in UTC (skips weekends)."""
    today = datetime.now(timezone.utc).date()
    day = today - timedelta(days=1)
    while day.weekday() >= 5:  # 5=Saturday, 6=Sunday
        day -= timedelta(days=1)
    return day


def parse_trades(log_file, agent_name, date_filter=None):
    trades = []
    if not os.path.exists(log_file):
        return trades

    with open(log_file) as f:
        for line in f:
            if date_filter:
                m = re.match(r'^(\d{4}-\d{2}-\d{2})', line)
                if not m or datetime.strptime(m.group(1), '%Y-%m-%d').date() != date_filter:
                    continue
            if 'PAPER TRADE:' in line:
                try:
                    symbol = re.search(r'PAPER TRADE: (\S+)', line)
                    direction = re.search(r'(LONG|SHORT)', line)
                    entry = re.search(r'Entry:([\d.]+)', line)
                    if symbol and direction and entry:
                        trades.append({
                            'agent': agent_name,
                            'symbol': symbol.group(1),
                            'direction': direction.group(1),
                            'entry': float(entry.group(1)),
                            'status': 'OPEN',
                            'pnl': 0,
                            'result': 'OPEN'
                        })
                except:
                    pass
            elif 'TP HIT:' in line or 'STOP HIT:' in line or 'TIME STOP:' in line:
                try:
                    result = 'WIN' if 'TP HIT' in line else ('LOSS' if 'STOP HIT' in line else 'TIME')
                    symbol = re.search(r'(?:TP HIT|STOP HIT|TIME STOP): (\S+)', line)
                    pnl = re.search(r'PnL:\$([-\d.]+)', line)
                    balance = re.search(r'Balance:\$([\d.]+)', line)
                    if symbol and pnl:
                        trades.append({
                            'agent': agent_name,
                            'symbol': symbol.group(1),
                            'result': result,
                            'pnl': float(pnl.group(1)),
                            'balance': float(balance.group(1)) if balance else 0,
                            'status': 'CLOSED',
                            'direction': ''
                        })
                except:
                    pass
    return trades


def parse_oracle_report():
    sports = []
    politics = []
    if not os.path.exists(ORACLE_LOG_DIR):
        return sports, politics

    reports = sorted([f for f in os.listdir(ORACLE_LOG_DIR) if f.startswith('report_')], reverse=True)
    if not reports:
        return sports, politics

    report_file = os.path.join(ORACLE_LOG_DIR, reports[0])
    with open(report_file, encoding='utf-8') as f:
        content = f.read()

    # Split into sections
    sports_section = ''
    politics_section = ''
    if '\U0001f3c6 SPORTS PICKS' in content:
        parts = content.split('\U0001f3c6 SPORTS PICKS')
        if len(parts) > 1:
            rest = parts[1]
            if '\U0001f3af HIGH VALUE' in rest:
                sports_section = rest.split('\U0001f3af HIGH VALUE')[0]
                politics_section = rest.split('\U0001f3af HIGH VALUE')[1]
            else:
                sports_section = rest
    else:
        # fallback - everything goes to politics
        if '\U0001f3af HIGH VALUE' in content:
            politics_section = content.split('\U0001f3af HIGH VALUE')[1]

    def parse_section(text, limit):
        opps = []
        current = {}
        for line in text.split('\n'):
            line = line.rstrip()
            if '\U0001f4cc' in line:
                if current and 'yes' in current:
                    opps.append(current)
                current = {'title': line.replace('\U0001f4cc', '').strip(), 'note': ''}
            elif line.strip().startswith('Title:') and current:
                current['title'] = line.strip()[6:].strip()
            elif line.strip().startswith('Market:') and current:
                current['market'] = line.strip()[7:].strip()
            elif 'Yes:' in line and 'No:' in line and current:
                yes = re.search(r'Yes: (\d+)%', line)
                no = re.search(r'No: (\d+)%', line)
                if yes and no:
                    current['yes'] = int(yes.group(1))
                    current['no'] = int(no.group(1))
                    current['bet'] = 'YES' if current['yes'] < 50 else 'NO'
            elif 'Volume:' in line and current and 'volume' not in current:
                vol = re.search(r'Volume: ([\d,]+)', line)
                if vol:
                    current['volume'] = vol.group(1)
            elif '\u26a1' in line and current:
                note = line.replace('\u26a1', '').strip()
                if 'volume' not in note.lower() and note:
                    current['note'] = note
        if current and 'yes' in current:
            opps.append(current)
        return opps[:limit]

    return parse_section(sports_section, 7), parse_section(politics_section, 5)


STYLES = """
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#080c10;--surface:#0e1420;--border:#1e2d40;--text:#cdd9e5;--muted:#5a7a9a;--blue:#4fb3ff;--green:#3ddc84;--red:#ff5b5b;--gold:#ffd166;--purple:#c084fc;--orange:#ff9f43}
body{background:var(--bg);color:var(--text);font-family:'Arial Black',Arial,sans-serif;padding:24px;width:1100px}
.mono{font-family:'Courier New',monospace}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;border-bottom:1px solid var(--border);padding-bottom:16px}
.title{font-size:15px;font-weight:900;letter-spacing:.15em;text-transform:uppercase}
.time{font-family:'Courier New',monospace;font-size:11px;color:var(--muted)}
.stats-row{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:20px;background:var(--surface)}
.stat-box{padding:20px 24px;border-right:1px solid var(--border);position:relative}
.stat-box:last-child{border-right:none}
.stat-box::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.stat-box.green::before{background:var(--green)}.stat-box.blue::before{background:var(--blue)}.stat-box.gold::before{background:var(--gold)}
.stat-label{font-size:10px;font-weight:900;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:10px}
.stat-value{font-family:'Courier New',monospace;font-size:28px;font-weight:700;line-height:1}
.stat-value.green{color:var(--green)}.stat-value.red{color:var(--red)}.stat-value.blue{color:var(--blue)}.stat-value.gold{color:var(--gold)}
.stat-sub{font-size:11px;color:var(--muted);margin-top:8px;font-family:'Courier New',monospace}
.body-row{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.section-label{font-size:10px;font-weight:900;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:12px}
.trade-row{display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--bg);border-radius:8px;margin-bottom:6px;border:1px solid var(--border)}
.trade-agent{font-size:9px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;padding:3px 8px;border-radius:4px;min-width:48px;text-align:center}
.trade-agent.crisp{background:rgba(79,179,255,.15);color:var(--blue)}.trade-agent.blade{background:rgba(255,209,102,.15);color:var(--gold)}
.trade-symbol{font-family:'Courier New',monospace;font-size:12px;font-weight:700;flex:1}
.trade-dir{font-size:10px;font-weight:900;min-width:44px}.trade-dir.long{color:var(--green)}.trade-dir.short{color:var(--red)}
.trade-pnl{font-family:'Courier New',monospace;font-size:12px;font-weight:700;min-width:75px;text-align:right}
.trade-pnl.pos{color:var(--green)}.trade-pnl.neg{color:var(--red)}
.trade-badge{font-size:9px;font-weight:700;padding:3px 8px;border-radius:10px;text-transform:uppercase}
.badge-win{background:rgba(61,220,132,.15);color:var(--green)}.badge-loss{background:rgba(255,91,91,.15);color:var(--red)}.badge-open{background:rgba(90,122,154,.15);color:var(--muted)}
.pnl-bars{display:flex;align-items:flex-end;gap:8px;height:90px;padding:4px}
.bar-wrap{display:flex;flex-direction:column;align-items:center;gap:4px;flex:1}
.bar{width:100%;border-radius:3px 3px 0 0;min-height:3px}
.bar-label{font-size:8px;color:var(--muted);font-family:'Courier New',monospace;white-space:nowrap}
.oracle-card{display:grid;grid-template-columns:44px 1fr auto;gap:16px;align-items:center;padding:16px 20px;background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:8px}
.oracle-rank{font-family:'Courier New',monospace;font-size:22px;font-weight:700;color:var(--gold)}
.oracle-title{font-size:13px;font-weight:700;color:var(--text);margin-bottom:4px}
.oracle-note{font-size:11px;color:var(--muted)}
.oracle-bet{display:flex;flex-direction:column;align-items:flex-end;gap:7px;min-width:140px}
.bet-tag{font-family:'Courier New',monospace;font-size:13px;font-weight:700;padding:6px 18px;border-radius:20px;text-align:center}
.bet-yes{background:rgba(61,220,132,.15);color:var(--green);border:1px solid rgba(61,220,132,.3)}
.bet-no{background:rgba(255,91,91,.15);color:var(--red);border:1px solid rgba(255,91,91,.3)}
.odds-bar{width:120px;height:5px;background:var(--border);border-radius:3px;overflow:hidden}
.odds-fill{height:100%;border-radius:3px}
.odds-text{font-family:'Courier New',monospace;font-size:10px;color:var(--muted)}
</style>
"""


def build_oracle_cards(opportunities):
    cards = ''
    for i, opp in enumerate(opportunities):
        yes = opp.get('yes', 0)
        no = opp.get('no', 0)
        bet = opp.get('bet', 'YES')
        bc = 'bet-yes' if bet == 'YES' else 'bet-no'
        bcolor = '#3ddc84' if bet == 'YES' else '#ff5b5b'
        bwidth = yes if bet == 'YES' else no
        bleft = '#3ddc84' if bet == 'YES' else '#ff5b5b'
        title = opp.get('title', 'Unknown')[:72]
        note = opp.get('note', '')[:80]
        vol = opp.get('volume', 'N/A')
        num = str(i+1).zfill(2)
        cards += (
            f'<div class="oracle-card" style="border-left:3px solid {bleft}">'
            f'<div class="oracle-rank mono">{num}</div>'
            f'<div class="oracle-info"><div class="oracle-title">{title}</div>'
            f'<div class="oracle-note">&#9889; {note} &middot; Vol: {vol}</div></div>'
            f'<div class="oracle-bet"><span class="bet-tag {bc}">BET {bet}</span>'
            f'<div class="odds-bar"><div class="odds-fill" style="width:{bwidth}%;background:{bcolor}"></div></div>'
            f'<div class="odds-text mono">Yes: {yes}% &middot; No: {no}%</div></div></div>'
        )
    if not cards:
        cards = '<div style="color:#5a7a9a;font-size:13px;padding:20px">No opportunities found</div>'
    return cards


def generate_trading_html(trades):
    crisp_closed = [t for t in trades if t['agent']=='Crisp' and t.get('status')=='CLOSED']
    blade_closed = [t for t in trades if t['agent']=='Blade' and t.get('status')=='CLOSED']
    closed = [t for t in trades if t.get('status')=='CLOSED']
    wins = [t for t in closed if t.get('result')=='WIN']
    losses = [t for t in closed if t.get('result')=='LOSS']
    total_pnl = sum(t['pnl'] for t in closed)
    win_rate = (len(wins)/len(closed)*100) if closed else 0
    pnl_str = f'+${total_pnl:.2f}' if total_pnl >= 0 else f'-${abs(total_pnl):.2f}'
    pnl_cls = 'green' if total_pnl >= 0 else 'red'
    best = max(closed, key=lambda x: x['pnl']) if closed else None
    best_str = f'+${best["pnl"]:.2f}' if best else 'N/A'
    best_label = f'{best["symbol"]} - {best["agent"]}' if best else '--'
    wr_cls = 'green' if win_rate >= 50 else 'red'
    wr_box = 'green' if win_rate >= 50 else 'gold'
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    trade_rows = ''
    for t in trades:
        ac = 'crisp' if t['agent']=='Crisp' else 'blade'
        dc = 'long' if t.get('direction')=='LONG' else 'short'
        pnl = t.get('pnl', 0)
        pc = 'pos' if pnl >= 0 else 'neg'
        pd = f'+${pnl:.2f}' if pnl >= 0 else f'-${abs(pnl):.2f}'
        res = t.get('result','OPEN')
        bc = 'badge-win' if res=='WIN' else ('badge-loss' if res=='LOSS' else 'badge-open')
        trade_rows += (
            f'<div class="trade-row"><span class="trade-agent {ac}">{t["agent"].upper()}</span>'
            f'<span class="trade-symbol mono">{t["symbol"]}</span>'
            f'<span class="trade-dir {dc}">{t.get("direction","")}</span>'
            f'<span class="trade-pnl {pc} mono">{pd}</span>'
            f'<span class="trade-badge {bc}">{res}</span></div>'
        )

    bar_items = ''
    if closed:
        max_abs = max(abs(t['pnl']) for t in closed) or 1
        for t in closed:
            h = int((abs(t['pnl'])/max_abs)*70)
            c = '#3ddc84' if t['pnl'] >= 0 else '#ff5b5b'
            bar_items += (
                f'<div class="bar-wrap"><div class="bar" style="height:{h}px;background:{c}"></div>'
                f'<div class="bar-label mono">{t["symbol"][:6]}</div></div>'
            )
    else:
        bar_items = '<div style="color:#5a7a9a;font-size:12px;padding:20px">No closed trades yet</div>'

    no_trades_msg = '<div style="color:#5a7a9a;font-size:13px;padding:20px">No trades yet -- check back after first session</div>'

    return f'''<!DOCTYPE html><html><head><meta charset="UTF-8">{STYLES}</head><body>
    <div class="header"><span class="title" style="color:var(--blue)">&#9889; Trading Dashboard &mdash; Crisp &amp; <span style="color:var(--gold)">Blade</span></span><span class="time mono">{now}</span></div>
    <div class="stats-row">
      <div class="stat-box green"><div class="stat-label">Overnight P&L</div><div class="stat-value {pnl_cls}">{pnl_str}</div><div class="stat-sub mono">across both agents</div></div>
      <div class="stat-box blue"><div class="stat-label">Trades Taken</div><div class="stat-value blue">{len(closed)}</div><div class="stat-sub mono">Crisp: {len(crisp_closed)} &middot; Blade: {len(blade_closed)}</div></div>
      <div class="stat-box {wr_box}"><div class="stat-label">Win Rate</div><div class="stat-value {wr_cls}">{win_rate:.0f}%</div><div class="stat-sub mono">{len(wins)}W &middot; {len(losses)}L</div></div>
      <div class="stat-box gold"><div class="stat-label">Best Trade</div><div class="stat-value gold">{best_str}</div><div class="stat-sub mono">{best_label}</div></div>
    </div>
    <div class="body-row">
      <div><div class="section-label">Trade Log</div>{trade_rows or no_trades_msg}</div>
      <div><div class="section-label">P&L Per Trade</div><div class="pnl-bars">{bar_items}</div></div>
    </div>
    </body></html>'''


def generate_sports_html(opportunities):
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return f'''<!DOCTYPE html><html><head><meta charset="UTF-8">{STYLES}</head><body>
    <div class="header"><span class="title" style="color:var(--orange)">&#127942; Sports Intelligence &mdash; Top 7 Kalshi Picks</span><span class="time mono">{now}</span></div>
    {build_oracle_cards(opportunities)}
    </body></html>'''


def generate_politics_html(opportunities):
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return f'''<!DOCTYPE html><html><head><meta charset="UTF-8">{STYLES}</head><body>
    <div class="header"><span class="title" style="color:var(--purple)">&#128302; Politics &amp; Finance &mdash; Top 5 Kalshi Picks</span><span class="time mono">{now}</span></div>
    {build_oracle_cards(opportunities)}
    </body></html>'''


def html_to_png(html_file, png_file):
    for cmd in ['chromium','chromium-browser']:
        try:
            subprocess.run([
                cmd,
                '--headless',
                '--no-sandbox',
                '--disable-gpu',
                f'--screenshot={png_file}',
                '--window-size=1150,1000',
                '--hide-scrollbars',
                f'file://{html_file}'
            ], capture_output=True, timeout=30)
            if os.path.exists(png_file):
                return True
        except:
            continue
    return False


if __name__ == '__main__':
    print("Generating morning dashboards...")

    all_trades = parse_trades(CRISP_LOG,'Crisp') + parse_trades(BLADE_LOG,'Blade')
    sports_opps, politics_opps = parse_oracle_report()
    print(f"Sports: {len(sports_opps)} | Politics: {len(politics_opps)}")

    files = [
        ('trading_dashboard.html', 'trading_dashboard.png', generate_trading_html(all_trades)),
        ('sports_dashboard.html', 'sports_dashboard.png', generate_sports_html(sports_opps)),
        ('politics_dashboard.html','politics_dashboard.png',generate_politics_html(politics_opps)),
    ]

    for html_name, png_name, content in files:
        html_path = os.path.join(OUTPUT_DIR, html_name)
        png_path = os.path.join(OUTPUT_DIR, png_name)
        with open(html_path, 'w') as f:
            f.write(content)
        status = 'PNG saved' if html_to_png(html_path, png_path) else 'PNG failed'
        print(f"{html_name}: {status}")

    print(f"\nDone! Files in {OUTPUT_DIR}")

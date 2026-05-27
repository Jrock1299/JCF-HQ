import json
from collections import defaultdict

def safe_load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {}

print("=== TRADELOCKER TRADES ===")
tl = safe_load("/root/.openclaw/dashboard/tradelocker_trades.json")
print(f"Total trades: {len(tl.get('trades',[]))}")
print(f"P&L: {tl.get('pnl','?')}")
print(f"Win rate: {tl.get('win_rate','?')}")
print(f"Balance: {tl.get('balance','?')}")

by_sym = defaultdict(lambda: {"pnl":0,"w":0,"l":0})
for t in tl.get("trades",[]):
    s = t.get("symbol","?")
    by_sym[s]["pnl"] += t.get("pnl",0)
    if t.get("pnl",0) > 0: by_sym[s]["w"] += 1
    else: by_sym[s]["l"] += 1
for s,v in sorted(by_sym.items(), key=lambda x: x[1]["pnl"], reverse=True):
    print(f"  {s}: PnL={v['pnl']:.2f} W={v['w']} L={v['l']}")

print("\n=== ORACLE ===")
op = safe_load("/root/.openclaw/dashboard/oracle_picks.json")
print(f"Bankroll: {op.get('bankroll','?')} | Record: {op.get('record','?')} | PnL: {op.get('total_pnl','?')}")
for p in op.get("picks",[]):
    print(f"  {p.get('pick','?')} | {p.get('odds','?')} | {p.get('result','?')}")

print("\n=== ORACLE RESOLVED ===")
orr = safe_load("/root/.openclaw/dashboard/oracle_resolved.json")
for p in orr.get("picks",[]):
    print(f"  {p.get('pick','?')} | {p.get('result','?')} | pnl: {p.get('pnl','?')}")

print("\n=== BET LOG ===")
bl = safe_load("/root/.openclaw/dashboard/bet_log.json")
print(f"Bankroll: {bl.get('bankroll','?')} | Record: {bl.get('record','?')} | PnL: {bl.get('total_pnl','?')}")

print("\n=== MARKET BIAS ===")
mb = safe_load("/root/.openclaw/dashboard/market_bias.json")
print(f"Summary: {str(mb.get('summary','?'))[:200]}")

print("\n=== AGENT HUB (recent) ===")
ah = safe_load("/root/.openclaw/dashboard/agent_hub.json")
for m in ah.get("messages",[])[-10:]:
    print(f"  {m.get('agent','?')} | {m.get('type','?')} | {str(m.get('message','?'))[:100]}")

print("\n=== AGENT PNL ===")
ap = safe_load("/root/.openclaw/dashboard/agent_pnl.json")
print(json.dumps(ap, indent=2)[:500])

print("\n=== SENTINEL INSIDER INTELLIGENCE ===")
sn = safe_load("/root/.openclaw/dashboard/sentinel_data.json")
if not sn:
    print("  sentinel_data.json not found — run sentinel_sync.py")
else:
    s = sn.get("summary", {})
    print(f"Last updated: {sn.get('last_updated','?')}")
    print(f"Watchlist txs: {s.get('watchlist_txs',0)} | Market scanned: {s.get('total_market_txs',0)}")
    print(f"Discoveries: {s.get('discoveries_found',0)} | Cluster buys: {s.get('cluster_discoveries',0)}")

    # Strong buys on watchlist
    strong_buys = [sg for sg in sn.get("watchlist_signals",[]) if sg.get("signal_type") == "STRONG_BUY"]
    if strong_buys:
        print(f"STRONG BUY signals ({len(strong_buys)}):")
        for sg in strong_buys:
            print(f"  • {sg['symbol']} [{sg['category']}] score={sg['score']} buys={sg['buy_count']} sells={sg['sell_count']}")
            for ins in sg.get("insiders", [])[:3]:
                val = ins.get('value', 0)
                val_str = f"${val/1e6:.1f}M" if val >= 1e6 else f"${val/1e3:.0f}k" if val >= 1e3 else f"${val:.0f}"
                print(f"      {ins.get('name','?')} {ins.get('type','?')} {val_str} {ins.get('date','')}")

    # All watchlist buy signals
    buys = [sg for sg in sn.get("watchlist_signals",[]) if sg.get("signal_type") == "BUY"]
    if buys:
        print(f"BUY signals ({len(buys)}): {', '.join(sg['symbol'] for sg in buys)}")

    # Sell signals
    sells = [sg for sg in sn.get("watchlist_signals",[]) if sg.get("signal_type") == "SELL"]
    if sells:
        print(f"SELL signals ({len(sells)}): {', '.join(sg['symbol'] for sg in sells)}")

    # Top discoveries
    top_disc = sn.get("top_discoveries", [])[:5]
    if top_disc:
        print(f"Top off-watchlist discoveries:")
        for d in top_disc:
            val = d.get('total_value', 0)
            val_str = f"${val/1e6:.1f}M" if val >= 1e6 else f"${val/1e3:.0f}k" if val >= 1e3 else f"${val:.0f}"
            print(f"  • {d['symbol']} [{d.get('signal_type','?')}] score={d['score']} {val_str} ({d.get('buy_count',0)} buys)")

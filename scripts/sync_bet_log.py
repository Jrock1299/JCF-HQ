#!/usr/bin/env python3
"""Regenerate bet_log.json from hq_userdata.json"""
import json

HQ_DATA = "/root/.openclaw/dashboard/hq_userdata.json"
BET_LOG = "/root/.openclaw/dashboard/bet_log.json"

with open(HQ_DATA) as f:
 d = json.load(f)

bets = d.get("my_bets", [])
bankroll_data = d.get("my_bankroll", {})
bankroll = bankroll_data.get("current", bankroll_data.get("amount", 0))

wins = sum(1 for b in bets if b.get("result") == "W")
losses = sum(1 for b in bets if b.get("result") == "L")
total = wins + losses
total_pnl = sum(float(b.get("pnl", 0)) for b in bets if b.get("result") in ("W", "L"))
total_wagered = sum(float(b.get("stake", 0)) for b in bets)
win_rate = f"{round(wins/total*100)}%" if total > 0 else "0%"
roi = f"{round(total_pnl/total_wagered*100, 1)}%" if total_wagered > 0 else "0%"

bet_log = {
 "bankroll": bankroll,
 "record": f"{wins}W - {losses}L",
 "win_rate": win_rate,
 "total_pnl": round(total_pnl, 2),
 "roi": roi,
 "total_wagered": round(total_wagered, 2),
 "bets": bets
}

with open(BET_LOG, "w") as f:
 json.dump(bet_log, f, indent=2)

print(f"Synced {len(bets)} bets to bet_log.json")

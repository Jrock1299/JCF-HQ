#!/bin/bash
# Daily Cost Tracker for OpenRouter usage
# Runs at 23:00 UTC daily via OpenClaw cron
# Appends per-model breakdown with tokens and dollar estimates to daily_cost.log

LOG="/root/.openclaw/logs/daily_cost.log"
mkdir -p "$(dirname "$LOG")"

OR_KEY="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"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
DATE_TODAY=$(date -u +"%Y-%m-%d")

# Fetch account-level usage summary
curl -s -H "Authorization: Bearer ${OR_KEY}" "https://openrouter.ai/api/v1/auth/key" > /tmp/or_account.json 2>/dev/null

# Fetch recent generations (up to 200 for the day)
curl -s -H "Authorization: Bearer ${OR_KEY}" "https://openrouter.ai/api/v1/generation?limit=200" > /tmp/or_generations.json 2>/dev/null

# Process and format output
python3 - "$DATE_TODAY" "$TIMESTAMP" "$LOG" << 'PYEOF'
import json, sys

date_today = sys.argv[1]
timestamp = sys.argv[2]
log_path = sys.argv[3]

lines = []
lines.append(f"=== Daily Cost Report: {date_today} ===")
lines.append(f"Timestamp: {timestamp}")
lines.append("")

daily_spend = 0.0

# Account summary
try:
    with open("/tmp/or_account.json", "r") as f:
        account = json.load(f)
    data = account.get("data", {})
    daily_spend = float(data.get("usage_daily", 0))
    lines.append("Account Summary:")
    lines.append(f"  Daily spend:   ${daily_spend:.4f}")
    lines.append(f"  Weekly spend:  ${float(data.get('usage_weekly', 0)):.4f}")
    lines.append(f"  Monthly spend: ${float(data.get('usage_monthly', 0)):.4f}")
    lines.append("")
except Exception as e:
    lines.append(f"Account Summary: unavailable ({e})")
    lines.append("")

# Per-model breakdown from generations
try:
    with open("/tmp/or_generations.json", "r") as f:
        gens = json.load(f)

    gen_list = gens.get("data", []) if isinstance(gens, dict) else gens if isinstance(gens, list) else []

    models = {}
    total_cost = 0.0
    total_tokens_in = 0
    total_tokens_out = 0

    for g in gen_list:
        model = g.get("model", "unknown")
        cost = float(g.get("total_cost", 0) or g.get("usage", 0) or 0)
        tokens_in = int(g.get("tokens_prompt", 0) or g.get("native_tokens_prompt", 0) or 0)
        tokens_out = int(g.get("tokens_completion", 0) or g.get("native_tokens_completion", 0) or 0)

        if model not in models:
            models[model] = {"calls": 0, "cost": 0.0, "tokens_in": 0, "tokens_out": 0}

        models[model]["calls"] += 1
        models[model]["cost"] += cost
        models[model]["tokens_in"] += tokens_in
        models[model]["tokens_out"] += tokens_out
        total_cost += cost
        total_tokens_in += tokens_in
        total_tokens_out += tokens_out

    if models:
        lines.append("Per-Model Breakdown:")
        lines.append(f"  {'Model':<45} {'Calls':>6} {'Tokens In':>12} {'Tokens Out':>12} {'Cost':>10}")
        lines.append(f"  {'-'*45} {'-'*6} {'-'*12} {'-'*12} {'-'*10}")
        for m, info in sorted(models.items(), key=lambda x: -x[1]["cost"]):
            lines.append(
                f"  {m:<45} {info['calls']:>6} "
                f"{info['tokens_in']:>12,} {info['tokens_out']:>12,} "
                f"${info['cost']:>9.4f}"
            )
        lines.append(f"  {'-'*45} {'-'*6} {'-'*12} {'-'*12} {'-'*10}")
        lines.append(
            f"  {'TOTAL':<45} "
            f"{sum(v['calls'] for v in models.values()):>6} "
            f"{total_tokens_in:>12,} {total_tokens_out:>12,} "
            f"${total_cost:>9.4f}"
        )
    else:
        lines.append("Per-Model Breakdown: no generation data available")

    lines.append("")
except Exception as e:
    lines.append(f"Per-Model Breakdown: unavailable ({e})")
    lines.append("")

# Cost alert
if daily_spend >= 3.0:
    lines.append(f"⚠️  COST ALERT: Daily spend ${daily_spend:.2f} exceeded $3.00 threshold!")
    lines.append("")

lines.append("---")
lines.append("")

with open(log_path, "a") as f:
    f.write("\n".join(lines) + "\n")

print("Daily cost report appended successfully.")
PYEOF

# Cleanup temp files
rm -f /tmp/or_account.json /tmp/or_generations.json

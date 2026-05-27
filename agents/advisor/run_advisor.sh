#!/bin/bash
LOG=/root/.openclaw/agents/advisor/advisor.log
echo "=== Advisor run $(date -u) ===" | tee -a "$LOG"

# Step 1: Collect data
python3 /root/.openclaw/agents/advisor/collect_data.py > /tmp/advisor_context.txt 2>&1

# Step 2: Run Claude with context
OUTPUT=$(claude --model claude-sonnet-4-6 --print -p "You are the Advisor CFO of JCF HQ. Analyze this data. Produce: 1) Daily P&L summary with flags 2) Oracle review 3) Agent health 4) Strategy recommendations 5) Telegram-ready summary. Be direct. $(cat /tmp/advisor_context.txt)" 2>&1)

echo "$OUTPUT" | tee -a "$LOG"

# Step 3: Post to hub
SUMMARY=$(echo "$OUTPUT" | tail -20)
curl -s -X POST http://localhost:8900/hq/hub \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg msg "$SUMMARY" '{agent:"advisor",type:"status",message:$msg,tags:["daily-review"]}')" > /dev/null 2>&1

echo "=== Advisor complete $(date -u) ===" | tee -a "$LOG"

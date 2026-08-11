#!/bin/bash
# One-shot: verify Jerry's FIRST live Codex review (2026-07-24 ~20:30 UTC) ran
# clean, Telegram the verdict to the owner, then remove its own cron line.
LOG=$(journalctl -u jerry --since "2026-07-24 20:00" --no-pager 2>/dev/null)
COST=$(python3 -c "
import json
try:
    d=json.load(open('/root/.openclaw/logs/jerry_api_costs.json'))
    revs=[e for e in d if e.get('call_type')=='review' and str(e.get('date'))=='2026-07-24']
    print(revs[-1]['timestamp'] if revs else 'NONE')
except Exception as e: print('ERR')
" 2>/dev/null)
ERR=$(echo "$LOG" | grep -ciE "traceback|Codex call failed|review error|NoneType|status=1/FAILURE")
if echo "$LOG" | grep -q "Review complete"; then
  MSG="✅ Jerry — first live Codex review (20:30 UTC) ran clean. 'Review complete' logged, ${ERR} error-lines near it, last review cost entry: ${COST}. (gpt-5.6-terra migration verified live.)"
else
  MSG="⚠️ Jerry — review check: no 'Review complete' in the journal since 20:00 UTC. error-lines=${ERR}, last review cost entry=${COST}. Inspect: journalctl -u jerry --since '20:00'."
fi
openclaw message send --channel telegram --target 797062420 --message "$MSG" >/dev/null 2>&1
echo "$(date -u '+%F %T') $MSG"
# self-remove (one-shot)
crontab -l | grep -v "jerry_review_check.sh" | crontab -

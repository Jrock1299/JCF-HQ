#!/bin/bash
# lens_first_fire_check.sh — one-shot verification of Lens's first production fire.
# Lens cron: 55 4 * * 1-5 UTC (run_lens_brain.sh). Expected fire 2026-07-22 04:55 UTC.
# Scheduled via a systemd transient timer for ~05:12 UTC. OBSERVES ONLY — never triggers a run.
set -a; source /root/.openclaw/.env 2>/dev/null; set +a

MB=/root/.openclaw/dashboard/market_bias.json
LOG=/root/.openclaw/agents/lens/bot/lens.log
RESULT=/root/.openclaw/logs/lens_first_fire_check.result.txt
BASE_SHA=aa961dc17b0298489745e17137b35adeab9db1212d225d8fa8ce96cfbb88d73e
LOG_OFFSET=2307                       # lens.log line count captured 2026-07-21 (baseline, pre-fire)
CHAT_ID=797062420                     # TELEGRAM_ALERT_CHAT_ID
THRESH=$(date -u -d '2026-07-22 00:00:00' +%s)

now_sha=$(sha256sum "$MB" 2>/dev/null | cut -d' ' -f1)
mb_epoch=$(stat -c %Y "$MB" 2>/dev/null || echo 0)
mb_mtime=$(date -u -d "@$mb_epoch" '+%Y-%m-%d %H:%M:%S UTC' 2>/dev/null)
log_lines=$(wc -l < "$LOG" 2>/dev/null || echo 0)
new_log=$(tail -n +$((LOG_OFFSET+1)) "$LOG" 2>/dev/null)

# Did the run fire at all?
fired=yes
if [ "$log_lines" -le "$LOG_OFFSET" ] && [ "$now_sha" = "$BASE_SHA" ]; then fired=no; fi

# CHECK 1 — market_bias.json updated (mtime today AND sha256 changed)
if [ "$now_sha" != "$BASE_SHA" ] && [ "$mb_epoch" -ge "$THRESH" ]; then
  c1=PASS; c1m="updated $mb_mtime; sha256 ${now_sha:0:12}… (changed from baseline)"
else
  if [ "$now_sha" = "$BASE_SHA" ]; then reason="sha256 still MATCHES baseline (not rewritten)"; else reason="sha256 changed but mtime $mb_mtime is not from today"; fi
  c1=FAIL; c1m="$reason"
fi

# CHECK 2 — Telegram delivery (only NEW log lines from today's run)
if echo "$new_log" | grep -q '\[lens_brain\] Telegram report sent'; then
  c2=PASS; c2m="'[lens_brain] Telegram report sent' present → chat $CHAT_ID"
elif echo "$new_log" | grep -qiE 'Telegram error|Telegram not configured|Telegram exception'; then
  c2=FAIL; c2m="$(echo "$new_log" | grep -iE 'Telegram error|not configured|Telegram exception' | head -1 | cut -c1-160)"
else
  c2=FAIL; c2m="no Telegram send confirmation in this run's log output"
fi

# CHECK 3 — no run errors (billing / traceback). FREECRYPTO enrichment warnings are non-fatal.
if [ "$fired" = no ]; then
  c3=FAIL; c3m="run did not fire — no new log output and baseline unchanged"
elif echo "$new_log" | grep -qiE 'credit balance is too low|BadRequestError|Error code: [0-9]{3}|Traceback \(most recent'; then
  c3=FAIL; c3m="$(echo "$new_log" | grep -iE 'credit balance|BadRequestError|Error code: [0-9]{3}|Traceback' | head -1 | cut -c1-160)"
else
  c3=PASS; c3m="no billing/traceback errors (enrichment FREECRYPTO warnings ignored)"
fi

verdict=PASS; for c in "$c1" "$c2" "$c3"; do [ "$c" = FAIL ] && verdict=FAIL; done

report="🔎 Lens first-fire check — $(date -u '+%Y-%m-%d %H:%M UTC')
CHECK 1 (market_bias.json updated): $c1 — $c1m
CHECK 2 (Telegram delivery):        $c2 — $c2m
CHECK 3 (no run errors):            $c3 — $c3m
OVERALL: $verdict"
[ "$fired" = no ] && report="$report
NOTE: Lens did NOT fire at 04:55 UTC (log unchanged past line $LOG_OFFSET, market_bias.json still at baseline)."

mkdir -p /root/.openclaw/logs
printf '%s\n' "$report" > "$RESULT"
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${report}" >/dev/null 2>&1
fi

# Heartbeat Configuration

## Schedule
- **Frequency:** Every 8 hours
- **Times:** 00:00 UTC, 08:00 UTC, 16:00 UTC
- **Model:** Claude Haiku 4.5 (cheapest available)

## How It Works
1. **Cron job** runs `/root/.openclaw/workspace/scripts/heartbeat.py` at scheduled times
2. **Script** writes a marker file to `.openclaw/heartbeat-trigger.txt`
3. **Huncho** checks for markers during main session activity
4. **Scan** runs through HEARTBEAT.md checklist:
   - Sub-agents: Any completed tasks needing relay?
   - Scheduled tasks: Anything due/overdue?
   - Trading cycle: If active, is it running?
   - Alerts: System issues, cost warnings, security flags?
5. **Response:** `HEARTBEAT_OK` if clear, or alert text if something needs attention

## Log
Heartbeat execution is logged to: `.openclaw/heartbeat.log`

## Verify
```bash
crontab -l  # Check cron schedule
cat .openclaw/heartbeat.log  # View execution history
```

## Model Choice
Haiku is the cheapest available model (~1/10th cost of Opus), perfect for routine checks that don't need complex reasoning.

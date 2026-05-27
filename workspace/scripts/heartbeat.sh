#!/bin/bash
# Huncho Heartbeat Script - Runs every 8 hours
# Uses cheapest model (Haiku) for cost efficiency

set -e

WORKSPACE="/root/.openclaw/workspace"
LOG_FILE="$WORKSPACE/.openclaw/heartbeat.log"

echo "[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] Heartbeat check started" >> "$LOG_FILE"

# Spawn heartbeat session with Haiku (cheapest model)
openclaw sessions spawn \
  --task "Read HEARTBEAT.md if it exists (workspace context). Follow it strictly. Do not infer or repeat old tasks from prior chats. If nothing needs attention, reply HEARTBEAT_OK." \
  --agentId "main" \
  --mode "run" \
  --model "anthropic/claude-haiku-4-5-20251001" \
  --runTimeoutSeconds 120 \
  2>&1 | tee -a "$LOG_FILE"

echo "[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] Heartbeat check completed" >> "$LOG_FILE"

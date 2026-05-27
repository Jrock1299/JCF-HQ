#!/bin/bash
SESSION=$1
LOG=/root/.openclaw/agents/crisp/bot/crisp.log
echo "$(date): Starting $SESSION session" >> $LOG
cd /root/.openclaw/agents/crisp/bot
python3 /root/.openclaw/agents/crisp/bot/crisp_bot.py $SESSION >> $LOG 2>&1

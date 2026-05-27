#!/bin/bash
SESSION=$1
LOG=/root/.openclaw/agents/blade/bot/blade.log
echo "$(date): Starting Blade $SESSION session" >> $LOG
cd /root/.openclaw/agents/blade/bot
python3 /root/.openclaw/agents/blade/bot/blade_bot.py $SESSION >> $LOG 2>&1

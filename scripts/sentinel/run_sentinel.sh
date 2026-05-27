#!/bin/bash
source /root/.openclaw/.sentinel_env 2>/dev/null
cd /root/.openclaw/scripts/sentinel
/usr/bin/python3 sentinel_sync.py >> /root/.openclaw/logs/sentinel_sync.log 2>&1

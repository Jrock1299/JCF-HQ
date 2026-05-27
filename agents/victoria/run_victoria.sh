#!/bin/bash
source /root/.bashrc
set -a
source /root/.openclaw/.env
set +a
cd /root/.openclaw/agents/victoria
python3 victoria_brain.py >> /root/.openclaw/logs/victoria.log 2>&1

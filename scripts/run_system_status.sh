#!/bin/bash
set -a; source /root/.openclaw/.env 2>/dev/null; set +a
python3 /root/.openclaw/scripts/system_status_report.py

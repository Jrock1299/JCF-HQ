#!/bin/bash
# Cron wrapper: mirror Vault + CLAUDE.md to Google Drive ("JCF HQ Vault").
# Uses the openclaw venv (google-api-python-client lives there). The Python
# script logs to logs/gdrive_sync.log itself; this redirect captures any
# unexpected stderr/bootstrap output too.
/root/.openclaw/venv/bin/python3 /root/.openclaw/scripts/gdrive_sync.py \
    >> /root/.openclaw/logs/gdrive_sync.log 2>&1

#!/bin/bash
# Victoria weekly risk validation — JERRY + CHAD. (Absorbed from Norman 2026-07-25.)
source /root/.bashrc
set -a
source /root/.openclaw/.env
set +a
cd /root/.openclaw/agents/victoria
/root/.openclaw/venv/bin/python3 victoria_validator.py --weekly >> /root/.openclaw/logs/victoria_validation.log 2>&1

#!/bin/bash
# Lens weekly risk validation — BLADE + EDGE. (Absorbed from Norman 2026-07-25.)
# Norman's run_norman.sh equivalent. The .env source block is required for the
# Telegram token; the Codex path needs the gateway on PATH from .bashrc.
source /root/.bashrc
set -a
source /root/.openclaw/.env
set +a
cd /root/.openclaw/agents/lens
/root/.openclaw/venv/bin/python3 lens_validator.py --weekly >> /root/.openclaw/logs/lens_validation.log 2>&1

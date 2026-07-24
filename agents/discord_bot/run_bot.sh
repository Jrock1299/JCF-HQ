#!/usr/bin/env bash
# Launcher for the JCF HQ two-way Discord bot.
# Sources .env (secrets) and runs under the openclaw venv (has discord.py).
set -euo pipefail

cd /root/.openclaw

set -a
# shellcheck disable=SC1091
source /root/.openclaw/.env
set +a

export PYTHONUNBUFFERED=1   # flush prints immediately so pm2 logs are live

exec /root/.openclaw/venv/bin/python /root/.openclaw/agents/discord_bot/bot.py

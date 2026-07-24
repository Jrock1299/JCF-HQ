#!/bin/bash
# Weekly Lens portfolio thesis (Sun 21:00 UTC). Anthropic + web search.
set -a; source /root/.openclaw/.env 2>/dev/null; set +a
cd /root/.openclaw/agents/lens
python3 lens_portfolio_thesis.py

#!/bin/bash
# Weekly multi-agent council (Sun 21:30 UTC). Lens=Anthropic, Jarvis/Norman/synth=Codex.
set -a; source /root/.openclaw/.env 2>/dev/null; set +a
cd /root/.openclaw/scripts
python3 council.py

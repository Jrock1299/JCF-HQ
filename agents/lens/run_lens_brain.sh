#!/bin/bash
source /root/.openclaw/.env
cd /root/.openclaw/agents/lens

# Post to hub: Lens starting
curl -s -X POST http://localhost:8900/hq/hub \
 -H "Content-Type: application/json" \
 -d "{\"agent\":\"lens\",\"type\":\"status\",\"message\":\"Lens Brain starting. Claude AI + web search macro analysis.\",\"tags\":[\"macro\",\"analysis\"]}" > /dev/null 2>&1

# Run Lens Brain (Claude API + web search)
python3 /root/.openclaw/agents/lens/lens_brain.py \
 >> /root/.openclaw/agents/lens/bot/lens.log 2>&1

# Enrich market_bias.json with live crypto prices (FreeCryptoAPI)
python3 /root/.openclaw/scripts/lens_crypto_enrichment.py \
 >> /root/.openclaw/agents/lens/bot/lens.log 2>&1

# Post to hub: Lens complete
curl -s -X POST http://localhost:8900/hq/hub \
 -H "Content-Type: application/json" \
 -d "{\"agent\":\"lens\",\"type\":\"status\",\"message\":\"Lens Brain complete. market_bias.json updated.\",\"tags\":[\"macro\",\"analysis\"]}" > /dev/null 2>&1

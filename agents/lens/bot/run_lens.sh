#!/bin/bash
cd /root/.openclaw/agents/lens

# Post to hub: Lens starting
curl -s -X POST http://localhost:8900/hq/hub \
 -H "Content-Type: application/json" \
 -d "{\"agent\":\"lens\",\"type\":\"status\",\"message\":\"Lens analysis started. Scanning news, assigning bias for all pairs.\",\"tags\":[\"macro\",\"analysis\"]}" > /dev/null 2>&1

# Run the actual Lens agent
/usr/bin/openclaw agent \
 --agent lens \
 --message "Execute your full analysis process as defined in STRATEGY.md. Search news, read context files, assign bias and confidence for all 3 pairs, write market_bias.json, send Telegram report to Jase." \
 >> /root/.openclaw/agents/lens/bot/lens.log 2>&1

# Enrich market_bias.json with live crypto prices (FreeCryptoAPI)
python3 /root/.openclaw/scripts/lens_crypto_enrichment.py \
 >> /root/.openclaw/agents/lens/bot/lens.log 2>&1

# Post to hub: Lens complete
curl -s -X POST http://localhost:8900/hq/hub \
 -H "Content-Type: application/json" \
 -d "{\"agent\":\"lens\",\"type\":\"status\",\"message\":\"Lens analysis complete. market_bias.json updated.\",\"tags\":[\"macro\",\"analysis\"]}" > /dev/null 2>&1
LENSEOF

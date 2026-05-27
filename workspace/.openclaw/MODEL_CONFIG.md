# Model Configuration

## Primary Model
- **Model:** `google/gemini-2.5-flash`
- **Used for:** All tasks including heartbeats, general work
- **Reason:** Fast, cost-efficient, high quality

## Previous Configuration
- Primary was: `anthropic/claude-haiku-4-5-20251001`
- Updated to Gemini Flash on 2026-02-24 20:06 UTC

## System Config
- Updated: `~/.openclaw/openclaw.json`
- Field: `agents.defaults.model.primary`

## Sub-Agents
- **Crisp (trading):** Uses `anthropic/claude-3-5-sonnet-20241022` (trading precision)
- **Other agents:** Inherit primary model unless specified otherwise

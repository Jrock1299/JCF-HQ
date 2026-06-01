#!/usr/bin/env bash
# run_research.sh — Pre-session regime briefing
# Runs strategy_engine.py, asks Codex for a narrative, sends to Telegram and Agent Hub.
#
# Usage:
#   ./run_research.sh            # all instruments
#   ./run_research.sh SPX500_USD # single instrument
#   DEEP=1 ./run_research.sh     # include Monte Carlo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$SCRIPT_DIR/strategy_engine.py"
LOGFILE="$SCRIPT_DIR/run_research.log"
TELEGRAM_UID="797062420"
DASHBOARD="/root/.openclaw/dashboard/strategy_recommendation.json"
NOTES_FILE="$SCRIPT_DIR/pre_session_notes.md"

NOW="$(date -u '+%Y-%m-%d %H:%M UTC')"
echo "======================================" | tee -a "$LOGFILE"
echo "[$NOW] run_research.sh starting"       | tee -a "$LOGFILE"

if [ -n "${1:-}" ]; then
    INSTRUMENTS="$1"
    echo "  Instrument override: $INSTRUMENTS" | tee -a "$LOGFILE"
else
    INSTRUMENTS=""
fi

# ── Run regime engine ────────────────────────────────────────────────────────
echo "  Running strategy_engine.py..." | tee -a "$LOGFILE"
if [ -n "$INSTRUMENTS" ]; then
    python3 "$ENGINE" "$INSTRUMENTS" --monte-carlo 2>&1 | tee -a "$LOGFILE"
else
    python3 "$ENGINE" --monte-carlo 2>&1 | tee -a "$LOGFILE"
fi

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "  ERROR: strategy_engine.py exited with code $EXIT_CODE" | tee -a "$LOGFILE"
    python3 -c "
import sys; sys.path.insert(0,'/root/.openclaw/scripts')
from hub_post import add_hub_message as hub_post
hub_post('strategist','error','strategy_engine.py failed (exit $EXIT_CODE)',tags=['error','strategy'])
" || true
    exit $EXIT_CODE
fi

# ── Narrative + Telegram delivery (all in Python so errors are surfaced) ─────
echo "  Generating Codex narrative and sending to Telegram..." | tee -a "$LOGFILE"
python3 - <<'PYEOF' 2>&1 | tee -a "$LOGFILE"
import json, os, subprocess, sys, datetime

sys.path.insert(0, '/root/.openclaw/scripts')
from telegram_personalities import wrap_message
from hub_post import add_hub_message as hub_post

DASHBOARD = '/root/.openclaw/dashboard/strategy_recommendation.json'
NOTES_FILE = '/root/.openclaw/agents/strategist/pre_session_notes.md'
TELEGRAM_UID = '797062420'

PROMPT_TEMPLATE = """You are JARVIS, the Strategy Architect for JCF HQ.
Voice: calm, precise, intelligent right-hand-man. Composed. Subtly confident.
Three steps ahead but never showy. Warm enough that the trader trusts you.
Economical enough that every sentence carries weight. Brief. Direct. No filler.

You are reading a regime briefing JSON and writing a SHORT pre-session
briefing for the trader. Plain text only — NO markdown.

ANALYTICAL FRAMEWORKS YOU APPLY (silently — don't list them, just use them):

(a) Local regime tag (TRENDING/RANGING/COMPRESSED/VOLATILE) for tactical timing.

(b) MACRO REGIME (macro-regime-detector method) — beyond local price action,
    watch for 1-2 year structural shifts using cross-asset ratios:
      • Concentration (RSP/SPY falling) → narrow leadership, fragility.
      • Broadening (RSP/SPY rising, small-caps participate) → durable risk-on.
      • Contraction (credit spreads widen, yield curve inverts) → risk-off.
      • Inflationary (commodities outperform, yields rise) → tilt commodities.
      • Transitional (signals conflict) → reduce conviction.
    Only mention macro regime when it conflicts with the tactical read.

(c) BREADTH CONTEXT (market-breadth-analyzer method) — healthy rallies have
    broad participation. If breadth signals weakening (composite < 40 on a
    0-100 scale), flag that TRADE recommendations carry extra risk regardless
    of local setup quality. 80+ = Strong, 60-79 = Healthy, 40-59 = Neutral,
    20-39 = Weakening, 0-19 = Critical.

(d) SECTOR ROTATION (sector-analyst method) — cycle position from leadership:
      • Cyclical leading (XLF/XLI/XLY) → Early/Mid cycle, risk-on.
      • Defensive leading (XLP/XLU/XLV) → Late cycle / recession risk.
    When defensives dominate, even a clean ORB setup deserves smaller size.

(e) Always tie the local tactical view back to a single concrete BOTTOM LINE
    — one specific instrument, one specific action.

FORMAT EXACTLY:

📅 {date}

REGIME: [OVERALL_REGIME] — [one-line interpretation]

For each instrument in the JSON, ONE block like:
[INSTRUMENT]: [REGIME] | bias [BULLISH/BEARISH/NEUTRAL] | Lens [BULLISH/BEARISH/NEUTRAL] [CONF%] | ADR [VALUE]
  [one short sentence — what the regime means for that instrument today]

End with:
🧠 LENS SUMMARY: [one-line summary of macro alignment across instruments]
📋 BOTTOM LINE: [ONE sentence — the single most important takeaway this session]

— Jarvis

RULES:
- Each instrument line + interpretation under 2 sentences.
- Concrete language. Cite the regime and bias. No hedging fluff.
- COMPRESSED → mention waiting for expansion.
- VOLATILE → mention size-down or stand-aside.
- If regime is UNKNOWN → say "data unavailable; standing down on that read."
- Plain text only. No markdown, no bold, no asterisks.
- Sign with "— Jarvis" on its own line before the rules — exactly as shown.

JSON:
"""

def call_codex(prompt: str, timeout_s: int = 90) -> str | None:
    """Run a prompt through openclaw infer model. Primary: openai/gpt-5.5. Returns text or None."""
    for model in ('openai/gpt-5.5', 'openrouter/auto'):
        try:
            proc = subprocess.run(
                ['openclaw', 'infer', 'model', 'run',
                 '--model', model, '--prompt', prompt],
                capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            print(f'  [codex] {model}: timeout after {timeout_s}s', file=sys.stderr)
            continue
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or '').strip().splitlines()[-2:]
            print(f'  [codex] {model}: exit {proc.returncode} | {" | ".join(tail)}', file=sys.stderr)
            continue
        text = proc.stdout
        # Strip the metadata header lines emitted by the CLI
        lines = text.splitlines()
        body_start = 0
        for i, ln in enumerate(lines):
            if ln.startswith('model.run via') or ln.startswith('provider:') or ln.startswith('model:') or ln.startswith('outputs:'):
                body_start = i + 1
            else:
                break
        body = '\n'.join(lines[body_start:]).strip()
        if body:
            return body
    return None


with open(DASHBOARD) as f:
    data = json.load(f)

date_str = datetime.datetime.utcnow().strftime('%B %-d')
prompt = PROMPT_TEMPLATE.format(date=date_str) + json.dumps(data, indent=2)

narrative = call_codex(prompt, timeout_s=120)
if not narrative:
    # Fallback raw summary if Codex unavailable
    print('  [codex] all models failed — falling back to raw summary', file=sys.stderr)
    lines = [f"📅 {date_str}", f"REGIME: {data.get('regime','?').upper()}"]
    for inst, r in data.get('instruments', {}).items():
        if r.get('regime', 'unknown') == 'unknown':
            continue
        lines.append(f"{inst}: {r['regime'].upper()} | bias {r.get('bias','neutral').upper()} | Lens {r.get('lens_bias','neutral').upper()} {r.get('lens_confidence',50):.0f}% | ADR {r.get('adr','-')}")
    mc = data.get('monte_carlo', {})
    if mc.get('median_pnl'):
        lines.append(f"MC: median={mc['median_pnl']} ruin={mc['ruin_probability']}")
    narrative = '\n'.join(lines)

with open(NOTES_FILE, 'w') as f:
    f.write(narrative + '\n')
print(f'  Narrative written → {NOTES_FILE}')

# Wrap with Strategist personality
wrapped = wrap_message('strategist', narrative)

# Post to Agent Hub
hub_post('strategist', 'briefing', wrapped, tags=['briefing', 'pre-session'])

# Send to Telegram via openclaw message send (USE --target, the correct flag)
send = subprocess.run([
    'openclaw', 'message', 'send',
    '--channel', 'telegram',
    '--target', TELEGRAM_UID,
    '--message', wrapped,
], capture_output=True, text=True, timeout=30)
if send.returncode == 0:
    print('  Telegram delivered ✓')
else:
    print(f'  Telegram send failed (rc={send.returncode}): {(send.stderr or send.stdout)[:200]}', file=sys.stderr)
PYEOF

echo "[$NOW] run_research.sh complete" | tee -a "$LOGFILE"
echo "======================================" | tee -a "$LOGFILE"

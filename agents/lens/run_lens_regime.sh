#!/usr/bin/env bash
# run_lens_regime.sh — Pre-session regime briefing (absorbed from Jarvis 2026-07-25).
#
# Replaces agents/strategist/run_research.sh. Runs lens_regime.py, asks Codex
# for a narrative, sends to Telegram and the Agent Hub.
#
# SCHEDULING NOTE — why this did NOT merge into Lens's 04:55 thesis run:
#   Lens's macro thesis (lens_brain.py) is a once-daily research product:
#   Anthropic + web search, expensive, and its conclusions hold all day.
#   The regime briefing is price-derived, cheap (OANDA/Binance candles + a
#   Codex narrative), and session-scoped — a 04:55 regime read is ~7 hours
#   stale by the NY open, which is precisely when Blade's NY_PM session and
#   Jerry's afternoon ticks read it. Collapsing both into one 04:55 run would
#   either serve a stale regime to the NY session or triple Lens's Anthropic
#   spend to re-run the thesis twice more. So: ONE daily thesis (04:55) and
#   TWO regime briefings (06:00 pre-London, 12:00 pre-NY), all owned by Lens.
#   The thesis writes market_bias.json; the briefing reads it. One direction,
#   no cycle.
#
# Usage:
#   ./run_lens_regime.sh            # all instruments
#   ./run_lens_regime.sh SPX500_USD # single instrument

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$SCRIPT_DIR/lens_regime.py"
LOGFILE="/root/.openclaw/logs/lens_regime.log"
PYBIN="/root/.openclaw/venv/bin/python3"

NOW="$(date -u '+%Y-%m-%d %H:%M UTC')"
echo "======================================" | tee -a "$LOGFILE"
echo "[$NOW] run_lens_regime.sh starting"     | tee -a "$LOGFILE"

if [ -n "${1:-}" ]; then
    INSTRUMENTS="$1"
    echo "  Instrument override: $INSTRUMENTS" | tee -a "$LOGFILE"
else
    INSTRUMENTS=""
fi

# ── Run regime engine ────────────────────────────────────────────────────────
echo "  Running lens_regime.py..." | tee -a "$LOGFILE"
if [ -n "$INSTRUMENTS" ]; then
    "$PYBIN" "$ENGINE" "$INSTRUMENTS" --monte-carlo 2>&1 | tee -a "$LOGFILE"
else
    "$PYBIN" "$ENGINE" --monte-carlo 2>&1 | tee -a "$LOGFILE"
fi

EXIT_CODE=${PIPESTATUS[0]}
if [ "$EXIT_CODE" -ne 0 ]; then
    echo "  ERROR: lens_regime.py exited with code $EXIT_CODE" | tee -a "$LOGFILE"
    python3 -c "
import sys; sys.path.insert(0,'/root/.openclaw/scripts')
from hub_post import add_hub_message as hub_post
hub_post('lens','error','lens_regime.py failed (exit $EXIT_CODE)',tags=['error','regime'])
" || true
    exit "$EXIT_CODE"
fi

# ── Narrative + Telegram delivery ────────────────────────────────────────────
echo "  Generating Codex narrative and sending to Telegram..." | tee -a "$LOGFILE"
python3 - <<'PYEOF' 2>&1 | tee -a "$LOGFILE"
import json, os, subprocess, sys, datetime

sys.path.insert(0, '/root/.openclaw/scripts')
from telegram_personalities import wrap_message
from hub_post import add_hub_message as hub_post

DASHBOARD = '/root/.openclaw/dashboard/strategy_recommendation.json'
NOTES_FILE = '/root/.openclaw/agents/lens/pre_session_notes.md'
TELEGRAM_UID = '797062420'

PROMPT_TEMPLATE = """You are LENS, the macro and regime desk for JCF HQ.
Voice: analytical, calm, precise. You read the tape and the macro backdrop and
say what matters. Economical — every sentence carries weight. No filler, no
hedging fluff.

You are reading a regime briefing JSON and writing a SHORT pre-session
briefing for the trader. Plain text only — NO markdown.

ANALYTICAL FRAMEWORKS YOU APPLY (silently — don't list them, just use them):

(a) Local regime tag (TRENDING/RANGING/COMPRESSED/VOLATILE) for tactical timing.

(b) MACRO REGIME (macro-regime-detector method) — beyond local price action,
    watch for 1-2 year structural shifts using cross-asset ratios:
      - Concentration (RSP/SPY falling) -> narrow leadership, fragility.
      - Broadening (RSP/SPY rising, small-caps participate) -> durable risk-on.
      - Contraction (credit spreads widen, yield curve inverts) -> risk-off.
      - Inflationary (commodities outperform, yields rise) -> tilt commodities.
      - Transitional (signals conflict) -> reduce conviction.
    Only mention macro regime when it conflicts with the tactical read.

(c) BREADTH CONTEXT (market-breadth-analyzer method) — healthy rallies have
    broad participation. If breadth signals weakening (composite < 40 on a
    0-100 scale), flag that TRADE recommendations carry extra risk regardless
    of local setup quality. 80+ = Strong, 60-79 = Healthy, 40-59 = Neutral,
    20-39 = Weakening, 0-19 = Critical.

(d) SECTOR ROTATION (sector-analyst method) — cycle position from leadership:
      - Cyclical leading (XLF/XLI/XLY) -> Early/Mid cycle, risk-on.
      - Defensive leading (XLP/XLU/XLV) -> Late cycle / recession risk.
    When defensives dominate, even a clean ORB setup deserves smaller size.

(e) CONVERGENCE — each instrument carries a 0-100 multi-timeframe convergence
    score with a direction. High score = timeframes agree; low = conflicted.
    This is an OBSERVATION, never a trade gate. Mention it only where it
    sharpens or contradicts the regime read.

(f) Always tie the local tactical view back to a single concrete BOTTOM LINE
    - one specific instrument, one specific action.

FORMAT EXACTLY:

{date}

REGIME: [OVERALL_REGIME] - [one-line interpretation]

For each instrument in the JSON, ONE block like:
[INSTRUMENT]: [REGIME] | bias [BULLISH/BEARISH/NEUTRAL] | Lens [BULLISH/BEARISH/NEUTRAL] [CONF%] | conv [SCORE]/100 | ADR [VALUE]
  [one short sentence - what the regime means for that instrument today]

End with:
MACRO SUMMARY: [one-line summary of macro alignment across instruments]
BOTTOM LINE: [ONE sentence - the single most important takeaway this session]

- Lens

RULES:
- Each instrument line + interpretation under 2 sentences.
- Concrete language. Cite the regime and bias. No hedging fluff.
- COMPRESSED -> mention waiting for expansion.
- VOLATILE -> mention size-down or stand-aside.
- If regime is UNKNOWN -> say "data unavailable; standing down on that read."
- Plain text only. No markdown, no bold, no asterisks.
- Sign with "- Lens" on its own line before the rules - exactly as shown.

JSON:
"""

def call_codex(prompt: str, timeout_s: int = 90) -> str | None:
    """Run a prompt through openclaw infer model. Primary: openai/gpt-5.6-terra."""
    # `infer model run` is NOT gated by the agents.defaults.models allow-list.
    # Sol would suit regime reasoning but 400s on this Codex OAuth backend, so
    # Terra is the top working tier; gpt-5.5 kept as proven fallback.
    for model in ('openai/gpt-5.6-terra', 'openai/gpt-5.5', 'openrouter/auto'):
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

# Trim the edge map out of the narrative payload — it is dashboard/backtest
# detail, not briefing material, and it bloats the prompt.
slim = dict(data)
slim['instruments'] = {
    k: {kk: vv for kk, vv in v.items() if kk not in ('edge_map', 'active_window')}
    for k, v in data.get('instruments', {}).items()
}

date_str = datetime.datetime.now(datetime.timezone.utc).strftime('%B %-d')
prompt = PROMPT_TEMPLATE.format(date=date_str) + json.dumps(slim, indent=2)

narrative = call_codex(prompt, timeout_s=120)
if not narrative:
    print('  [codex] all models failed — falling back to raw summary', file=sys.stderr)
    lines = [f"{date_str}", f"REGIME: {data.get('regime','?').upper()}"]
    for inst, r in data.get('instruments', {}).items():
        if r.get('regime', 'unknown') == 'unknown':
            continue
        conv = (r.get('convergence') or {}).get('score', '-')
        lines.append(
            f"{inst}: {r['regime'].upper()} | bias {r.get('bias','neutral').upper()} | "
            f"Lens {r.get('lens_bias','neutral').upper()} {r.get('lens_confidence',50):.0f}% | "
            f"conv {conv}/100 | ADR {r.get('adr','-')}"
        )
    mc = data.get('monte_carlo', {})
    if mc.get('median_pnl'):
        lines.append(f"MC: median={mc['median_pnl']} ruin={mc['ruin_probability']}")
    lines.append('- Lens')
    narrative = '\n'.join(lines)

with open(NOTES_FILE, 'w') as f:
    f.write(narrative + '\n')
print(f'  Narrative written -> {NOTES_FILE}')

wrapped = wrap_message('lens', narrative)

hub_post('lens', 'briefing', wrapped, tags=['briefing', 'pre-session', 'regime'])

send = subprocess.run([
    'openclaw', 'message', 'send',
    '--channel', 'telegram',
    '--target', TELEGRAM_UID,
    '--message', wrapped,
], capture_output=True, text=True, timeout=30)
if send.returncode == 0:
    print('  Telegram delivered')
else:
    print(f'  Telegram send failed (rc={send.returncode}): {(send.stderr or send.stdout)[:200]}', file=sys.stderr)
PYEOF

echo "[$NOW] run_lens_regime.sh complete" | tee -a "$LOGFILE"
echo "======================================" | tee -a "$LOGFILE"

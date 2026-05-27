#!/usr/bin/env bash
# run_research.sh — Pre-session strategy analysis
# Runs strategy_engine.py, posts results to Agent Hub, sends Telegram summary.
#
# Usage:
#   ./run_research.sh            # all instruments
#   ./run_research.sh SPX500_USD # single instrument
#   DEEP=1 ./run_research.sh     # include extended Monte Carlo pass

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$SCRIPT_DIR/strategy_engine.py"
LOG_DIR="$SCRIPT_DIR"
LOGFILE="$LOG_DIR/run_research.log"
TELEGRAM_UID="797062420"
HUB_SCRIPT="/root/.openclaw/scripts/hub_post.py"
DASHBOARD="/root/.openclaw/dashboard/strategy_recommendation.json"

# ── Timestamp ────────────────────────────────────────────────────────────────
NOW="$(date -u '+%Y-%m-%d %H:%M UTC')"
echo "======================================" | tee -a "$LOGFILE"
echo "[$NOW] run_research.sh starting"       | tee -a "$LOGFILE"

# ── Instruments ───────────────────────────────────────────────────────────────
if [ -n "${1:-}" ]; then
    INSTRUMENTS="$1"
    echo "  Instrument override: $INSTRUMENTS" | tee -a "$LOGFILE"
else
    INSTRUMENTS=""
fi

# ── Run strategy engine ───────────────────────────────────────────────────────
echo "  Running strategy_engine.py..." | tee -a "$LOGFILE"
if [ -n "$INSTRUMENTS" ]; then
    python3 "$ENGINE" "$INSTRUMENTS" --monte-carlo 2>&1 | tee -a "$LOGFILE"
else
    python3 "$ENGINE" --monte-carlo 2>&1 | tee -a "$LOGFILE"
fi

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "  ERROR: strategy_engine.py exited with code $EXIT_CODE" | tee -a "$LOGFILE"
    # Post error to hub
    python3 -c "
import sys; sys.path.insert(0,'/root/.openclaw/scripts')
from hub_post import add_hub_message as hub_post
hub_post('strategist','error','strategy_engine.py failed (exit $EXIT_CODE)',tags=['error','strategy'])
"
    exit $EXIT_CODE
fi

# ── Parse recommendation and build summary ────────────────────────────────────
SUMMARY=$(python3 - <<'PYEOF'
import json, sys
try:
    with open('/root/.openclaw/dashboard/strategy_recommendation.json') as f:
        data = json.load(f)

    regime = data.get('regime', 'unknown').upper()
    lines  = [f"STRATEGY UPDATE | Regime: {regime}"]

    for inst, rec in data.get('instruments', {}).items():
        score   = rec.get('score', 0)
        result  = rec.get('recommendation', 'SKIP')
        strat   = rec.get('strategy', 'orb').upper()
        bias    = rec.get('bias', '')
        emoji   = "✅" if result == 'TRADE' else "⛔"
        lines.append(f"  {emoji} {inst}: {score}/100 → {strat} {bias}")

    mc = data.get('monte_carlo', {})
    if mc.get('median_pnl'):
        lines.append(f"MC: median={mc['median_pnl']} | 5th%={mc['worst_case_5pct']} | ruin={mc['ruin_probability']}")

    print('\n'.join(lines))
except Exception as e:
    print(f"Summary error: {e}")
PYEOF
)

echo "  Summary:" | tee -a "$LOGFILE"
echo "$SUMMARY"   | tee -a "$LOGFILE"

# ── Post data summary to Agent Hub ────────────────────────────────────────────
python3 -c "
import sys; sys.path.insert(0,'/root/.openclaw/scripts')
from hub_post import add_hub_message as hub_post
msg = '''$SUMMARY'''
hub_post('strategist', 'strategy', msg.strip(), tags=['strategy','analysis','pre-session'])
" 2>&1 | tee -a "$LOGFILE"

# ── Call Claude Code for narrative insights ────────────────────────────────────
NOTES_FILE="$SCRIPT_DIR/pre_session_notes.md"
echo "  Generating Claude narrative insights..." | tee -a "$LOGFILE"
claude --print "$(cat <<'CLAUDE_PROMPT'
You are the Strategy Architect for JCF HQ. Read the strategy_recommendation.json below and produce a pre-session briefing formatted EXACTLY as a clean Telegram message using this structure:

📊 PRE-SESSION BRIEFING | [Month Day]

[REGIME EMOJI] REGIME: [REGIME NAME] — [Mode e.g. Preservation Mode / Trend Mode / Caution]

For each instrument in the JSON, output a block like:
━━━ [INSTRUMENT NAME] ━━━━━━━━━━━━━
Score: [X]/100 | [ACTION EMOJI + label e.g. ⛔ WATCH ONLY / 👀 BEST SETUP TODAY / ⛔ HARD AVOID / ✅ TRADE]
Bias: [Bullish/Bearish/Neutral] ([timeframe context if available])
ADR: [value] [⚠️ Abnormal if applicable]
Strategy: [strategy_name]
Key Level: [price and brief label if available]
[FVG line if FVG data present, e.g.: FVG: [price] ([context])]
[Warning line if applicable, e.g.: ⚠️ [condition]]
[Alert line if there is a specific trigger, e.g.: 🎯 Alert: [what to watch for]]

End with:
━━━━━━━━━━━━━━━━━━━━━
🧠 LENS: [one-line summary of macro bias across instruments]
📋 BOTTOM LINE: [ONE sentence — the single most important thing to focus on this session]

Rules:
- Use ⛔ HARD AVOID for volatile/skip instruments (regime VOLATILE or score <40)
- Use ⛔ WATCH ONLY for marginal setups (score 40-69)
- Use 👀 BEST SETUP TODAY for the highest-scoring instrument
- Use ✅ TRADE for score ≥70 with clean conditions
- Emoji usage is functional not decorative — only use where specified above
- Skip instrument lines that have no data
- BOTTOM LINE should name one specific instrument and one specific action
CLAUDE_PROMPT
)

$(python3 -c "import json; data=json.load(open('/root/.openclaw/dashboard/strategy_recommendation.json')); print(json.dumps(data, indent=2))" 2>/dev/null || echo 'No data available')" > "$NOTES_FILE" 2>&1 || \
    echo "  Claude narrative failed (non-fatal)" | tee -a "$LOGFILE"

if [ -f "$NOTES_FILE" ] && [ -s "$NOTES_FILE" ]; then
    echo "  Narrative written → $NOTES_FILE" | tee -a "$LOGFILE"
    # Post narrative to hub
    NARRATIVE=$(cat "$NOTES_FILE")
    python3 -c "
import sys; sys.path.insert(0,'/root/.openclaw/scripts')
from hub_post import add_hub_message as hub_post
msg = '''$NARRATIVE'''
hub_post('strategist', 'strategy', msg.strip(), tags=['strategy','narrative','pre-session'])
" 2>&1 | tee -a "$LOGFILE"

    # ── Send Claude narrative briefing to Telegram ────────────────────────────
    openclaw message send \
        --channel telegram \
        --to "$TELEGRAM_UID" \
        --message "$NARRATIVE" 2>&1 | tee -a "$LOGFILE" || \
        echo "  Telegram send failed (non-fatal)" | tee -a "$LOGFILE"
else
    # Fallback: send raw summary if Claude narrative unavailable
    TELEGRAM_MSG="[STRATEGIST] $NOW\n$SUMMARY"
    openclaw message send \
        --channel telegram \
        --to "$TELEGRAM_UID" \
        --message "$TELEGRAM_MSG" 2>&1 | tee -a "$LOGFILE" || \
        echo "  Telegram send failed (non-fatal)" | tee -a "$LOGFILE"
fi

echo "[$NOW] run_research.sh complete" | tee -a "$LOGFILE"
echo "======================================" | tee -a "$LOGFILE"

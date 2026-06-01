"""
chart_analysis.py — Chart analysis skill for Huncho.

Analyzes trading chart images and returns a structured read
in Blade's stoic military voice, delivered through Huncho.

Usage (from Huncho's agent context):
    from chart_analysis import analyze_chart

    # Image file path (downloaded from Telegram by the gateway)
    result = analyze_chart('/tmp/photo_123.jpg')
    result = analyze_chart('/tmp/photo_123.jpg', context='SPX500 1H London open')

Usage (CLI test):
    python3 chart_analysis.py /path/to/chart.png
    python3 chart_analysis.py /path/to/chart.png "XAUUSD M15 Asia session"
    python3 chart_analysis.py --test            # synthetic 1x1 PNG end-to-end test
"""

import base64
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, '/root/.openclaw/scripts')
from telegram_personalities import wrap_message

INFER_TIMEOUT_MS = 55000      # per-model provider timeout (55s)
SUBPROCESS_TIMEOUT_S = 60     # per-attempt wall clock (must exceed INFER_TIMEOUT_MS)

# Default image model (moonshot/kimi-k2.5) is currently suspended for billing.
# Rotate through known-working multimodal models. Total worst case:
# len(MODEL_FALLBACKS) * SUBPROCESS_TIMEOUT_S = 2 * 60 = 120s, fits the wrapper budget.
MODEL_FALLBACKS = [
    'codex/gpt-5.4',
    'codex/gpt-5.5',
]

ANALYSIS_PROMPT = """\
You are a professional technical analyst. Analyze this trading chart and provide a structured read.

METHODOLOGY (apply silently — do not list steps in the output):
1. TREND — direction, strength, and duration. Look at the slope of recent highs/lows,
   not just the last bar.
2. KEY LEVELS — horizontal support/resistance from prior swings, trendlines if drawn,
   confluence zones (level coinciding with MA, prior consolidation, round number).
3. MOVING-AVERAGE ALIGNMENT — note the slope and stack of any 20/50/200-period MAs
   visible. Stacked + sloped = trending; flat / interwoven = ranging.
4. VOLUME / VOLATILITY — note breakouts confirmed by volume vs failed on no-volume.
   Spikes near key levels matter more than absolute level.
5. PATTERNS — recognize reversal (double top/bottom, head-and-shoulders), continuation
   (flag, pennant, triangle), and ORB structure if session open is visible.
6. PROBABILISTIC SCENARIOS — develop 2–3 scenarios with probabilities summing to ~100%
   (typically 40-60% base, 20-40% counter-case, 5-15% alternative). Each scenario must
   have a specific price target AND an invalidation level — the price that, if reached,
   negates the thesis.

Cover these points in order:
1. INSTRUMENT & TIMEFRAME — identify from chart labels if visible
2. TREND DIRECTION — overall bias: BULLISH, BEARISH, or RANGING
3. KEY LEVELS — support and resistance levels visible on the chart
4. SMA POSITION — where price sits relative to any moving averages visible
5. ORB SETUP — if this looks like a session open, is the opening range clean or choppy?
6. ENTRY BIAS — LONG, SHORT, or STAND DOWN
7. INVALIDATION — what price level or condition would make this read wrong
8. CONFIDENCE — HIGH, MEDIUM, or LOW with a brief reason

Respond in this EXACT format (plain text, no markdown):

Instrument: [value or "not visible"]
Timeframe: [value or "not visible"]

Trend: [BULLISH/BEARISH/RANGING]
Key levels: S: [support] / R: [resistance]
SMA position: [above/below/at moving averages]
ORB setup: [CLEAN/CHOPPY/N/A]

Entry bias: [LONG/SHORT/STAND DOWN]
Invalidation: [level or condition]
Confidence: [HIGH/MEDIUM/LOW] — [one-line reason]

Be concise. Military report format. No fluff. No markdown."""

NY_OPEN_LABEL = 'NY OPEN MANUAL ASSIST'
DEFAULT_LABEL = 'CHART READ'


def _extract_description(result: dict) -> str:
    """Pull the description text out of `openclaw infer image describe --json`.

    Current shape: {"ok": true, ..., "outputs": [{"text": "...", ...}]}.
    Legacy shapes also accepted: top-level `description` or `text`.
    """
    outputs = result.get('outputs')
    if isinstance(outputs, list) and outputs:
        first = outputs[0] or {}
        for key in ('text', 'description'):
            v = first.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    for key in ('description', 'text'):
        v = result.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ''


def _invoke_infer(image_path: str, prompt: str, debug: bool = False):
    """Call openclaw infer image describe across the fallback model list.

    On success: (description_str, None).
    On failure: (None, diagnostic_str).
    """
    last_error = None
    for model in MODEL_FALLBACKS:
        cmd = [
            'openclaw', 'infer', 'image', 'describe',
            '--file', image_path,
            '--prompt', prompt,
            '--model', model,
            '--json',
            '--timeout-ms', str(INFER_TIMEOUT_MS),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            last_error = f'{model}: subprocess timeout after {SUBPROCESS_TIMEOUT_S}s'
            if debug:
                print(f'[chart_analysis] {last_error}', file=sys.stderr)
            continue
        except Exception as e:
            last_error = f'{model}: {type(e).__name__}: {e}'
            if debug:
                print(f'[chart_analysis] {last_error}', file=sys.stderr)
            continue

        if proc.returncode != 0:
            err_tail = (proc.stderr or proc.stdout or '').strip().splitlines()[-3:]
            last_error = f'{model}: exit {proc.returncode} | ' + ' | '.join(err_tail)
            if debug:
                print(f'[chart_analysis] {last_error}', file=sys.stderr)
            continue

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            last_error = f'{model}: bad JSON: {e}'
            if debug:
                print(f'[chart_analysis] {last_error} | stdout={proc.stdout[:200]}', file=sys.stderr)
            continue

        description = _extract_description(result)
        if description and len(description) >= 20:
            return description, None

        last_error = f'{model}: empty/short description (len={len(description)})'
        if debug:
            print(f'[chart_analysis] {last_error}', file=sys.stderr)

    return None, last_error


def analyze_chart(image_path: str, context: str = None, ny_open: bool = False,
                  debug: bool = False) -> str:
    """Analyze a chart image and return a formatted Telegram message.

    Args:
        image_path: Path to the chart image file.
        context:    Optional context (e.g. "SPX500 1H London open").
        ny_open:    If True, labels the read as NY Open manual assist.
        debug:      If True, print diagnostic info to stderr.

    Returns:
        Formatted message string ready to send via Telegram,
        wrapped in Huncho's voice with Blade's analysis inside.
    """
    if not os.path.isfile(image_path):
        if debug:
            print(f'[chart_analysis] image not found: {image_path}', file=sys.stderr)
        return wrap_message('huncho',
            "Aye, I never got that image. Telegram dropped it. Send it again. — H")

    prompt = ANALYSIS_PROMPT
    if context:
        prompt += f'\n\nADDITIONAL CONTEXT FROM TRADER: {context}'

    description, err = _invoke_infer(image_path, prompt, debug=debug)
    if description is None:
        if debug:
            print(f'[chart_analysis] all attempts failed: {err}', file=sys.stderr)
        return wrap_message('huncho',
            "Aye, my guy couldn't get a read on that one. "
            "Send it again — full screenshot, no compression. — H")

    label = NY_OPEN_LABEL if ny_open else DEFAULT_LABEL
    blade_read = f'\U0001f52a BLADE — {label}\n\n{description}'

    huncho_intro = (
        "Aye, got my guy lookin' at that chart for you. "
        "Here's what he came back with:\n\n"
        f"{blade_read}"
    )

    return wrap_message('huncho', huncho_intro)


# 1x1 white PNG, base64 — sufficient to exercise the infer pipeline end-to-end
_TEST_PNG_B64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8'
    '/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=='
)


def _run_self_test() -> int:
    """Write a synthetic image, run the full pipeline, print diagnostics. Returns exit code."""
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as fh:
        fh.write(base64.b64decode(_TEST_PNG_B64))
        path = fh.name
    print(f'[chart_analysis] --test using {path}', file=sys.stderr)
    try:
        out = analyze_chart(path, context='self-test', debug=True)
        print(out)
        return 0
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == '--test':
        sys.exit(_run_self_test())

    if len(sys.argv) < 2:
        print('Usage: python3 chart_analysis.py <image_path> [context]')
        print('       python3 chart_analysis.py --test')
        sys.exit(1)

    path = sys.argv[1]
    ctx = sys.argv[2] if len(sys.argv) > 2 else None
    print(analyze_chart(path, context=ctx, debug=True))

"""
h4_read.py — Text-based 4H technical read for Blade + Edge.

Pulls H4 + D1 candles directly via Jarvis's data fetchers, computes structural
context (EMA stack, ATR/ADR, BB squeeze, recent swing high/low, distance to
key MAs), and asks Codex to write a concise technical interpretation.

Methodology baked into the prompt (per technical-analyst skill):
  • Trend: direction, strength, duration
  • Key levels: support/resistance from prior swings + round numbers
  • MA alignment: 20/50/200 H4 stack
  • Volume / volatility: ATR trend, BB squeeze
  • 2-4 probabilistic scenarios summing to ~100%, each with invalidation level

This is OBSERVATION ONLY. Blade and Edge log the read but never gate on it.

Usage:
    from h4_read import generate_h4_read
    read = generate_h4_read('SPX500_USD')
    # read = {'trend': 'bullish', 'bias': 'bullish', 'confidence': 65,
    #         'key_levels': {...}, 'narrative': '...', 'scenarios': [...],
    #         'ma_position': 'above', 'regime_hint': 'trending', 'generated_at': ...}
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, '/root/.openclaw/scripts')
sys.path.insert(0, '/root/.openclaw/agents/strategist')
from strategy_engine import (
    fetch_candles, calc_indicators, calc_adr, ema_alignment,
    bb_squeeze_ratio, detect_regime, ADR_NORMAL,
)
from output_sanitizer import strip_cli_noise

CACHE_DIR = '/tmp/h4_reads'
CACHE_TTL_SECS = 1800  # reuse the read for up to 30 min within a session window

H4_READ_PROMPT = """You are a technical analyst writing a SHORT pre-session
4-hour chart read. Plain text only, no markdown.

INPUT DATA:
{data_json}

ANALYTICAL METHOD (silently — don't list, just apply):
• Trend: direction, strength, duration from EMA stack + recent HH/LL structure.
• Key levels: most relevant prior swing high/low and round number near price.
• MA alignment: where price sits relative to 20/50/200-period H4 MAs and slopes.
• Volatility regime: ATR trend (expanding vs contracting) and BB compression.
• 2-3 probabilistic scenarios summing to ~100% (typical: 40-60% base case,
  20-40% counter-case, 5-20% alternative). Each must have an INVALIDATION
  level that would negate the thesis.

OUTPUT — exactly this structure, plain text:

TREND: [BULLISH/BEARISH/RANGING] — [strength & duration in one phrase]
KEY LEVELS: S: [price] / R: [price]
MA POSITION: [above/below/at] H4 [20/50/200] EMAs — [alignment word]
VOLATILITY: [expanding/contracting/squeezed] — [one phrase]
BIAS: [BULLISH/BEARISH/NEUTRAL] [confidence%]
SCENARIOS:
  • [probability%] [BASE/BULL/BEAR/ALT case]: [one sentence] | invalidation: [price]
  • [probability%] [BASE/BULL/BEAR/ALT case]: [one sentence] | invalidation: [price]
INVALIDATION (overall): [the level that flips the whole read]

Be concrete. Cite actual numbers from the input. No hedging fluff."""


def _build_data_block(instrument: str) -> dict:
    """Fetch H4 + D1 data, compute indicators, return a flat dict for the prompt."""
    h4   = fetch_candles(instrument, 'H4', 100)
    d1   = fetch_candles(instrument, 'D',  60)
    if not h4 or not d1:
        return {'error': f'no candles for {instrument}'}

    ind_h4 = calc_indicators(h4)
    ind_d1 = calc_indicators(d1)
    adr_val = calc_adr(d1, period=10)
    align_h4 = ema_alignment(ind_h4)
    align_d1 = ema_alignment(ind_d1)
    squeeze  = round(bb_squeeze_ratio(ind_h4), 3)
    regime   = detect_regime(h4, d1, ind_h4, adr_val, instrument)

    last = h4[-1]
    # Key MAs (last value)
    ema20  = ind_h4['ema20'][-1]
    ema50  = ind_h4['ema50'][-1]
    e_d_50 = ind_d1['ema50'][-1] if ind_d1.get('ema50') else None

    # Recent swing high/low over last ~30 H4 (~5 days)
    window = h4[-30:]
    swing_high = max(c['high'] for c in window)
    swing_low  = min(c['low']  for c in window)

    # Prior day H/L
    pdh = d1[-2]['high'] if len(d1) >= 2 else None
    pdl = d1[-2]['low']  if len(d1) >= 2 else None

    atr_vals = [v for v in ind_h4['atr14'][-20:] if v is not None]
    atr_now  = round(atr_vals[-1], 4) if atr_vals else None
    atr_avg  = round(sum(atr_vals)/len(atr_vals), 4) if atr_vals else None
    atr_expanding = bool(atr_now and atr_avg and atr_now > atr_avg * 1.1)

    return {
        'instrument':       instrument,
        'h4_close':         round(last['close'], 4),
        'h4_time':          last['time'],
        'ema20_h4':         round(ema20, 4) if ema20 else None,
        'ema50_h4':         round(ema50, 4) if ema50 else None,
        'ema50_d1':         round(e_d_50, 4) if e_d_50 else None,
        'ema_align_h4':     align_h4,
        'ema_align_d1':     align_d1,
        'recent_swing_high': round(swing_high, 4),
        'recent_swing_low':  round(swing_low,  4),
        'prior_day_high':    round(pdh, 4) if pdh else None,
        'prior_day_low':     round(pdl, 4) if pdl else None,
        'atr14_h4_now':      atr_now,
        'atr14_h4_avg20':    atr_avg,
        'atr_expanding':     atr_expanding,
        'bb_squeeze_ratio':  squeeze,    # <1.0 = compression, >1.0 = expansion
        'adr10_d1':          round(adr_val, 2) if adr_val else None,
        'adr_normal':        ADR_NORMAL.get(instrument, {}),
        'regime_engine':     regime,
    }


def _call_codex(prompt: str, timeout_s: int = 60):
    """Call openclaw infer model with primary + fallback."""
    for model in ('openai/gpt-5.5', 'openrouter/auto'):
        try:
            proc = subprocess.run(
                ['openclaw', 'infer', 'model', 'run',
                 '--model', model, '--prompt', prompt],
                capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            logging.warning(f'h4_read codex timeout on {model}')
            continue
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-2:]
            logging.warning(f'h4_read {model} exit {proc.returncode}: {" | ".join(tail)}')
            continue
        # Strip CLI metadata + transport noise from ANYWHERE in the output.
        # The old leading-header walk broke on the first unrecognised line, so
        # any noise emitted BEFORE the known prefixes (e.g. OpenRouter's
        # `[provider-transport-fetch]` lines) passed straight through into the
        # read. Same defect that leaked debug output into Lens's Telegram
        # briefings on 2026-07-30.
        body, noise = strip_cli_noise(proc.stdout)
        if noise:
            logging.warning(f'h4_read {model}: filtered {len(noise)} debug line(s): '
                            f'{noise[0][:160]}')
        if body:
            return body
        logging.warning(f'h4_read {model}: output was entirely CLI noise')
    return None


def _parse_bias(text: str):
    """Extract bias + confidence from the BIAS line."""
    bias, conf = 'neutral', 50
    for line in text.splitlines():
        if line.strip().upper().startswith('BIAS:'):
            tokens = line.split(':', 1)[1].strip().split()
            if tokens:
                bias = tokens[0].lower().rstrip(',')
                for tok in tokens[1:]:
                    tok = tok.rstrip(',%').replace('%', '')
                    try:
                        conf = int(tok)
                        break
                    except ValueError:
                        continue
            break
    return bias, conf


def _cache_path(instrument: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f'h4_{instrument}.json')


def _try_cache(instrument: str):
    path = _cache_path(instrument)
    try:
        with open(path) as f:
            cached = json.load(f)
        ts = datetime.fromisoformat(cached['generated_at'])
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age < CACHE_TTL_SECS:
            return cached
    except Exception:
        return None
    return None


def _write_cache(instrument: str, read: dict):
    try:
        with open(_cache_path(instrument), 'w') as f:
            json.dump(read, f, indent=2)
    except Exception:
        pass


def generate_h4_read(instrument: str, force_refresh: bool = False) -> dict:
    """Return a structured 4H read for the instrument.

    Returns:
        {
          'instrument':   str,
          'narrative':    str,         # the Codex-written read
          'bias':         'bullish'|'bearish'|'neutral',
          'confidence':   int,         # 0-100
          'data':         dict,        # raw indicator/level snapshot
          'generated_at': iso8601 str,
          'error':        str (only if generation failed),
        }
    """
    if not force_refresh:
        cached = _try_cache(instrument)
        if cached:
            return cached

    data = _build_data_block(instrument)
    if 'error' in data:
        return {'instrument': instrument, 'error': data['error'],
                'bias': 'neutral', 'confidence': 50,
                'generated_at': datetime.now(timezone.utc).isoformat()}

    prompt = H4_READ_PROMPT.format(data_json=json.dumps(data, indent=2))
    narrative = _call_codex(prompt, timeout_s=90)
    if not narrative:
        # Fallback: hand-built deterministic read from the data
        narrative = _fallback_read(data)

    bias, conf = _parse_bias(narrative)
    out = {
        'instrument':   instrument,
        'narrative':    narrative,
        'bias':         bias,
        'confidence':   conf,
        'data':         data,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
    _write_cache(instrument, out)
    return out


def _fallback_read(d: dict) -> str:
    """Deterministic minimal read if the LLM call fails."""
    align = d.get('ema_align_h4', 'neutral')
    bias  = align if align != 'neutral' else 'neutral'
    return (
        f"TREND: {align.upper()} — derived from H4 EMA alignment (fallback, no LLM).\n"
        f"KEY LEVELS: S: {d.get('recent_swing_low')} / R: {d.get('recent_swing_high')}\n"
        f"MA POSITION: H4 close {d.get('h4_close')} vs EMA50 {d.get('ema50_h4')}\n"
        f"VOLATILITY: {'expanding' if d.get('atr_expanding') else 'contracting'} — "
        f"BB squeeze ratio {d.get('bb_squeeze_ratio')}\n"
        f"BIAS: {bias.upper()} 50%\n"
        f"SCENARIOS:\n"
        f"  • 60% BASE case: range continues between {d.get('recent_swing_low')} "
        f"and {d.get('recent_swing_high')} | invalidation: clean H4 close beyond either\n"
        f"INVALIDATION (overall): break of recent swing range with momentum"
    )


def summarize_h4_for_log(read: dict) -> dict:
    """Compact form for embedding in trade logs / learning records."""
    return {
        'trend':      read.get('data', {}).get('ema_align_h4', 'neutral'),
        'bias':       read.get('bias', 'neutral'),
        'confidence': read.get('confidence', 50),
        'swing_high': read.get('data', {}).get('recent_swing_high'),
        'swing_low':  read.get('data', {}).get('recent_swing_low'),
        'regime':     read.get('data', {}).get('regime_engine'),
        'generated_at': read.get('generated_at'),
    }


if __name__ == '__main__':
    inst = sys.argv[1] if len(sys.argv) > 1 else 'SPX500_USD'
    r = generate_h4_read(inst, force_refresh=True)
    print(r.get('narrative', r.get('error', 'no read')))

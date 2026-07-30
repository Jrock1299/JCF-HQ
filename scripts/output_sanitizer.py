#!/usr/bin/env python3
"""output_sanitizer.py — keep machine debug output out of human channels.

Written 2026-07-30 after Lens delivered two Telegram briefings whose first
lines were raw transport logs:

    [provider-transport-fetch] [model-fetch] start provider=openrouter ...
    [provider-transport-fetch] [model-fetch] response provider=openrouter ...
    model.run via local
    provider: openrouter
    ...

The proximate bug was a header-stripping loop in `run_lens_regime.sh` that
`break`s on the first line it doesn't recognise — so noise that arrives
*before* the four known metadata prefixes stops the strip dead and the whole
stdout, transport logs included, becomes "the narrative".

Fixing that one parser is necessary but not sufficient. Any of the ~20 scripts
that shell out to a model CLI can grow the same defect, and the failure mode is
silent: nothing errors, Jase just gets a garbage message. So the guarantee is
enforced at the DESTINATION instead — `telegram_personalities.wrap_message()`
sanitises every body it wraps, and any new sender gets the protection for free.

Design notes:
  - CONSERVATIVE BY DEFAULT. A false positive silently deletes a line of a real
    report, which is worse than the leak it prevents. Every rule below either
    matches a known machine-log shape or requires several independent debug
    signals on one line. Prose never matches.
  - Sanitising is not error suppression. `strip_cli_noise` returns what it
    removed, so callers log the noise to the run log where it belongs.
  - If a message sanitises down to nothing, the sender must say so plainly
    rather than deliver an empty bubble — see `sanitize_outbound`.
"""
from __future__ import annotations

import re

__all__ = [
    'is_noise_line',
    'strip_cli_noise',
    'sanitize_outbound',
    'NOISE_NOTICE',
]

# Shown instead of an empty message when a body was entirely machine noise.
NOISE_NOTICE = ('Report unavailable — the narrative step returned no usable '
                'output. Nothing was inferred. See the run log for detail.')

# ── ANSI / control ────────────────────────────────────────────────────────────
_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')

# ── Rule 1: bracketed transport/provider tags at line start ───────────────────
# Matches "[provider-transport-fetch] ...", "[openai-transport] [responses] ..."
# Requires the tag to be lower-kebab-case AND the line to carry a debug payload
# (a second bracket tag, or a key=value pair). A prose line that happens to open
# with "[Note] something" has neither.
_BRACKET_TAG = r'\[[a-z][a-z0-9]*(?:-[a-z0-9]+)+\]'
_BRACKET_NOISE_RE = re.compile(
    rf'^\s*{_BRACKET_TAG}\s*(?:{_BRACKET_TAG}|\S+\s+)*?\S*[a-zA-Z_][\w.]*=\S'
)
_BRACKET_PAIR_RE = re.compile(rf'^\s*{_BRACKET_TAG}\s*{_BRACKET_TAG}')

# ── Rule 2: known CLI metadata headers ────────────────────────────────────────
# Emitted by `openclaw infer model run`. These are exact-shape lines, not prose.
_META_RE = re.compile(
    r'^\s*(?:'
    r'model\.run\s+via\b'
    r'|provider:\s*\S+\s*$'
    r'|model:\s*\S+\s*$'
    r'|outputs:\s*\d+\s*$'
    r'|usage:\s*\{'
    r'|tokens?:\s*\d+\s*$'
    r')',
    re.IGNORECASE,
)

# ── Rule 3: tracebacks and raw exception echoes ───────────────────────────────
_TRACEBACK_RE = re.compile(
    r'^\s*(?:'
    r'Traceback \(most recent call last\):'
    r'|File "[^"]+", line \d+'
    r'|\w+(?:\.\w+)*(?:Error|Exception|Warning): '
    r'|Error: No text output returned for provider'
    r')'
)

# ── Rule 4: dense key=value structured-log lines ──────────────────────────────
# Machine logs pack many `k=v` tokens onto one line. Real report lines rarely
# carry more than one or two (e.g. Lens's fallback "MC: median=-12.5 ruin=0.03",
# which stays well under the threshold). Four is deliberately generous.
_KV_RE = re.compile(r'(?:^|\s)[a-zA-Z_][\w.]*=[^\s=]')
_KV_THRESHOLD = 4

# Tokens that mark a line as transport chatter regardless of density.
_HARD_TOKENS = (
    'provider-transport-fetch',
    'model-fetch',
    'openai-transport',
    'openclaw-openai-responses-transport',
    'anthropic-transport',
)


def is_noise_line(line: str) -> bool:
    """True if `line` is machine debug output rather than report content."""
    stripped = _ANSI_RE.sub('', line).strip()
    if not stripped:
        return False  # blank lines are formatting, preserved by strip_cli_noise

    low = stripped.lower()
    if any(tok in low for tok in _HARD_TOKENS):
        return True
    if _META_RE.match(stripped):
        return True
    if _TRACEBACK_RE.match(stripped):
        return True
    if _BRACKET_PAIR_RE.match(stripped) or _BRACKET_NOISE_RE.match(stripped):
        return True
    if len(_KV_RE.findall(stripped)) >= _KV_THRESHOLD:
        return True
    return False


def strip_cli_noise(text: str) -> tuple[str, list[str]]:
    """Remove machine debug lines from `text`.

    Unlike the leading-header strip it replaces, this scans EVERY line — noise
    that arrives before, between or after the real body is removed either way.

    Returns `(clean_text, removed_lines)`. Callers should log `removed_lines`
    rather than discard them: the noise is still diagnostic, it just belongs in
    the run log, not on Jase's phone.
    """
    if not text:
        return '', []

    kept: list[str] = []
    removed: list[str] = []
    for line in _ANSI_RE.sub('', text).splitlines():
        (removed if is_noise_line(line) else kept).append(line)

    # Collapse the blank-line runs that removals leave behind, and trim edges.
    out: list[str] = []
    for line in kept:
        if not line.strip() and (not out or not out[-1].strip()):
            continue
        out.append(line.rstrip())
    while out and not out[-1].strip():
        out.pop()

    return '\n'.join(out).strip(), removed


def sanitize_outbound(text: str, notice: str = NOISE_NOTICE) -> str:
    """Notification-layer guard. Never returns machine noise, never returns ''.

    This is the last line of defence before a message leaves for Telegram or
    Discord. If the body was entirely noise, `notice` is returned instead —
    an honest "no usable output" beats either an empty bubble or a transport
    dump, and it keeps Critical Rule #9 intact (a failed read is reported as a
    failed read, never dressed up as content).
    """
    clean, _removed = strip_cli_noise(text or '')
    return clean if clean else notice


if __name__ == '__main__':  # pragma: no cover — quick self-check
    LEAKED = """[provider-transport-fetch] [model-fetch] start provider=openrouter api=openai-completions model=openrouter/auto method=POST url=https://openrouter.ai/api/v1/chat/completions timeoutMs=undefined proxy=none policy=custom
[provider-transport-fetch] [model-fetch] response provider=openrouter api=openai-completions model=openrouter/auto status=200 elapsedMs=1084 contentType=text/event-stream
model.run via local
provider: openrouter
model: openrouter/auto
outputs: 1
July 30

REGIME: RANGING - Directional conviction is low; favor range discipline.

SPX500_USD: UNKNOWN | bias NEUTRAL | Lens NEUTRAL 0% | conv 0/100 | ADR N/A
  Data unavailable; standing down on that read.

BTC_USD: RANGING | bias NEUTRAL | Lens BEARISH 62% | conv 46.2/100 | ADR 1492.9
  Trade range edges only; weak convergence argues against chasing upside.

MACRO SUMMARY: Cross-asset alignment is unavailable.
BOTTOM LINE: Stand aside on BTC_USD until price reaches a defined range edge.

- Lens"""

    clean, removed = strip_cli_noise(LEAKED)
    assert clean.startswith('July 30'), clean[:80]
    assert clean.endswith('- Lens')
    assert len(removed) == 6, removed
    assert 'provider-transport-fetch' not in clean
    assert 'SPX500_USD: UNKNOWN' in clean
    assert 'MC: median=-12.5 ruin=0.03' == strip_cli_noise('MC: median=-12.5 ruin=0.03')[0]
    assert sanitize_outbound('[model-fetch] a=1 b=2 c=3 d=4') == NOISE_NOTICE
    assert sanitize_outbound('') == NOISE_NOTICE
    # Prose must survive untouched.
    prose = 'Blade made $18.40 across 2 trades. Edge is flat.\nBOTTOM LINE: stand aside.'
    assert strip_cli_noise(prose)[0] == prose
    print('output_sanitizer self-check OK')
    print(f'  removed {len(removed)} noise lines, kept {len(clean.splitlines())}')

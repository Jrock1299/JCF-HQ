#!/usr/bin/env python3
"""openrouter_catalog.py — pull OpenRouter's LIVE model catalog and build the menu.

Prices and model availability change constantly. Nothing here is hardcoded from
memory: every model id, price and capability flag comes from
GET https://openrouter.ai/api/v1/models at run time.

  python3 openrouter_catalog.py                 # print the filtered menu
  python3 openrouter_catalog.py --write         # refresh dashboard/openrouter_menu.json
  python3 openrouter_catalog.py --ceiling 0.5   # different $/M output ceiling

FILTERS (see FILTER_NOTES for the reasoning):
  • Anthropic excluded entirely — Jase does not want Claude as a fallback, and
    Lens keeps its own direct Anthropic key separately.
  • openrouter/* meta-models excluded — auto-routers report a -1000000 pricing
    sentinel and pick the model themselves. The brief is explicit that model
    selection stays under Jase's control, not a black box.
  • Above the $/M-output ceiling excluded (default $1.00, see below).
  • Non-text output (image/audio-only) excluded.

RANKING: free first, then cheapest output price, then cheapest input.
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CATALOG_URL = 'https://openrouter.ai/api/v1/models'
MENU_PATH = Path('/root/.openclaw/dashboard/openrouter_menu.json')

# $/M output tokens. Chosen from the live distribution rather than by feel:
# the paid median sits at ~$1.56/M and p25 at ~$0.60, so $1.00 sits just below
# the median — it keeps ~145 models (plenty of choice across ~36 families)
# while excluding every premium tier (GPT/Opus-class run $10-$600/M).
DEFAULT_CEILING = 1.00

EXCLUDED_PREFIXES = ('anthropic/', 'openrouter/')


def fetch_catalog(url: str = CATALOG_URL) -> list[dict]:
    """GET the live catalog. Public endpoint — no API key required."""
    req = urllib.request.Request(url, headers={'User-Agent': 'JCF-HQ/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())['data']


def _price(model: dict, key: str) -> float:
    """Price in $ per MILLION tokens. Returns -1 for the auto-router sentinel."""
    try:
        v = float((model.get('pricing') or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0.0
    return v * 1_000_000


def build_menu(models: list[dict], ceiling: float = DEFAULT_CEILING) -> list[dict]:
    rows = []
    for m in models:
        mid = m.get('id', '')
        if mid.startswith(EXCLUDED_PREFIXES):
            continue
        arch = m.get('architecture') or {}
        if 'text' not in (arch.get('output_modalities') or ['text']):
            continue
        out, inp = _price(m, 'completion'), _price(m, 'prompt')
        if out < 0 or inp < 0:          # auto-router sentinel
            continue
        if out > ceiling:
            continue
        sp = m.get('supported_parameters') or []
        rows.append({
            'id': mid,
            'name': m.get('name', ''),
            'in_per_m': round(inp, 4),
            'out_per_m': round(out, 4),
            'context': m.get('context_length') or 0,
            'structured_outputs': 'structured_outputs' in sp,
            'tools': 'tools' in sp,
            'reasoning': bool(m.get('reasoning')),
            'free': (out == 0 and inp == 0),
        })
    rows.sort(key=lambda r: (not r['free'], r['out_per_m'], r['in_per_m']))
    return rows


def summarize(rows: list[dict]) -> dict:
    fams = {}
    for r in rows:
        fams[r['id'].split('/')[0]] = fams.get(r['id'].split('/')[0], 0) + 1
    return {
        'total': len(rows),
        'free': sum(1 for r in rows if r['free']),
        'paid': sum(1 for r in rows if not r['free']),
        'families': dict(sorted(fams.items(), key=lambda z: -z[1])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ceiling', type=float, default=DEFAULT_CEILING,
                    help='max $/M output tokens (default %(default)s)')
    ap.add_argument('--write', action='store_true', help='write the menu JSON')
    ap.add_argument('--limit', type=int, default=40, help='rows to print')
    args = ap.parse_args()

    try:
        models = fetch_catalog()
    except Exception as e:
        print(f'[or-catalog] catalog fetch failed: {e}', file=sys.stderr)
        return 1

    rows = build_menu(models, args.ceiling)
    s = summarize(rows)

    print(f'[or-catalog] {len(models)} models live | {s["total"]} pass '
          f'(≤${args.ceiling}/M out, no Anthropic, no auto-routers)')
    print(f'[or-catalog] free={s["free"]} paid={s["paid"]} '
          f'across {len(s["families"])} families\n')
    print(f'{"model id":52}{"in $/M":>9}{"out $/M":>9}{"ctx":>11}{"str":>5}{"tool":>5}')
    for r in rows[:args.limit]:
        print(f'{r["id"]:52}{r["in_per_m"]:>9.3f}{r["out_per_m"]:>9.3f}'
              f'{r["context"]:>11,}{"Y" if r["structured_outputs"] else "-":>5}'
              f'{"Y" if r["tools"] else "-":>5}')

    if args.write:
        MENU_PATH.write_text(json.dumps({
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'source': CATALOG_URL,
            'ceiling_usd_per_m_output': args.ceiling,
            'excluded_prefixes': list(EXCLUDED_PREFIXES),
            'summary': s,
            'models': rows,
        }, indent=2))
        print(f'\n[or-catalog] menu written → {MENU_PATH}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

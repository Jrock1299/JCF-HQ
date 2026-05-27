"""
naomi_brain.py — Etsy copywriter for JCF HQ.

Reads a Forge-built product and writes a complete Etsy listing
with SEO-optimised titles, description, tags, pricing, and
social copy — all backed by live Etsy/keyword research.

Usage:
    python3 naomi_brain.py --product ai_ops_dashboard
    python3 naomi_brain.py --product sports_bankroll_manager

    from naomi_brain import write_listing
    result = write_listing(product_name, product_spec, build_path)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import requests

# ── Paths & constants ──────────────────────────────────────────────────────────

FORGE_DIR       = Path('/root/.openclaw/agents/forge')
SPECS_PATH      = FORGE_DIR / 'data' / 'product_specs.json'
BUILDS_DIR      = FORGE_DIR / 'builds'
LOG_PATH        = Path('/root/.openclaw/logs/naomi_api_costs.json')
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

MODEL           = 'claude-sonnet-4-6'
MAX_TOKENS      = 4096

TELEGRAM_TOKEN  = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT   = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID', '')

# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Naomi, an elite Etsy copywriter for JCF HQ. You write listings \
that convert browsers into buyers.

PROCESS:
1. Analyse the product — what it does, who it's for, what problem it solves
2. Search Etsy for competing products — what are they charging, how are they \
   describing similar items, what tags are they using
3. Search for trending keywords in this product category
4. Write copy that stands out from competitors

ETSY LISTING STRUCTURE:
- Title: Front-load the most searchable keywords. Include the product type, \
  key feature, and who it's for. Max 140 characters.
- Description: Start with a hook (the problem it solves). Then features as \
  benefits (not just a feature list). Include a "What's included" section \
  listing all theme variants. End with a call to action.
- Tags: 13 tags, each max 20 characters. Mix of broad ("dashboard template") \
  and specific ("AI API cost tracker"). No duplicate words across tags.

PRICING TIERS:
- Basic ($15–20): single theme
- Standard ($25–30): all 3 themes
- Premium ($40–50): all themes + custom colour builder + Excel/Sheets version \
  (if applicable)

TONE: Professional but approachable. Not salesy or corporate. Think "helpful \
friend who builds cool things."

OUTPUT FORMAT (valid JSON only, no markdown):
{
  "titles": {
    "primary": "string max 140 chars",
    "variation_1": "string max 140 chars",
    "variation_2": "string max 140 chars"
  },
  "description": "full listing description as a single string with newlines",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7",
           "tag8", "tag9", "tag10", "tag11", "tag12", "tag13"],
  "pricing": {
    "basic":    {"price": 19.99, "includes": "what the basic tier contains"},
    "standard": {"price": 29.99, "includes": "what the standard tier contains"},
    "premium":  {"price": 49.99, "includes": "what the premium tier contains"}
  },
  "social_caption": "Instagram/Twitter caption with hashtags",
  "screenshot_guide": [
    "Description of screenshot 1",
    "Description of screenshot 2",
    "Description of screenshot 3",
    "Description of screenshot 4",
    "Description of screenshot 5"
  ]
}"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    depth, start, last = 0, -1, None
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    last = json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    pass
    return last


def _save_cost(module: str, input_tokens: int, output_tokens: int,
               web_searches: int = 0) -> float:
    cost = round((input_tokens * 3 / 1_000_000) + (output_tokens * 15 / 1_000_000), 6)
    entry = {
        'date':          datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'module':        module,
        'input_tokens':  input_tokens,
        'output_tokens': output_tokens,
        'web_searches':  web_searches,
        'cost_usd':      cost,
    }
    costs = _load_json(LOG_PATH, [])
    costs.append(entry)
    try:
        LOG_PATH.write_text(json.dumps(costs, indent=2))
    except Exception as e:
        print(f'[naomi] cost log error: {e}')
    return cost


def _send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print(f'[naomi] Telegram not configured — skipping')
        return
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT, 'text': text},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as e:
        print(f'[naomi] Telegram error: {e}')


def _build_prompt(product_spec: dict, html_preview: str) -> str:
    features = '\n'.join(f'  - {f}' for f in product_spec.get('features', []))
    themes   = ', '.join(product_spec.get('themes', []))
    has_excel = product_spec.get('type', 'html') in ('xlsx', 'both')
    has_cb    = product_spec.get('include_custom_builder', False)

    return f"""Write a complete Etsy listing for this digital product.

PRODUCT DETAILS:
  Name:        {product_spec.get('display_name', product_spec.get('name', ''))}
  Type:        HTML Dashboard Template
  Description: {product_spec.get('description', '')}

FEATURES:
{features}

WHAT'S INCLUDED:
  Themes:        {themes}
  Custom builder: {"Yes — buyers can pick any colour scheme" if has_cb else "No"}
  Excel version: {"Yes" if has_excel else "No"}

HTML FILE PREVIEW (first 2000 chars of the actual product):
{html_preview[:2000]}

INSTRUCTIONS:
1. Search Etsy for similar dashboard templates and digital planners to understand \
   competition, pricing, and what keywords/tags competitors use.
2. Search for trending Etsy keywords in "digital download", "spreadsheet template", \
   "dashboard template", and any category-specific terms.
3. Write the full listing optimised to rank in Etsy search and convert buyers.
4. Output ONLY the JSON — no markdown, no prose."""


# ── Main function ──────────────────────────────────────────────────────────────

def write_listing(
    product_name: str,
    product_spec: dict = None,
    build_path: str | Path = None,
) -> dict:
    """
    Write a complete Etsy listing for a Forge-built product.

    Args:
        product_name: key matching product_specs.json (e.g. 'ai_ops_dashboard')
        product_spec: optional — loaded from specs file if None
        build_path:   optional — path to the primary HTML file

    Returns:
        Full listing dict saved to builds/{product_name}/listing.json
    """
    # ── Load spec ──────────────────────────────────────────────────────────────
    if product_spec is None:
        specs = _load_json(SPECS_PATH, [])
        product_spec = next((s for s in specs if s.get('name') == product_name), None)
    if product_spec is None:
        raise ValueError(f"Product '{product_name}' not found in {SPECS_PATH}")

    display_name = product_spec.get('display_name', product_name)

    # ── Find HTML file ─────────────────────────────────────────────────────────
    if build_path is None:
        # Try dark_techy first, then first available theme folder
        candidates = [
            BUILDS_DIR / product_name / 'dark_techy' / 'index.html',
            BUILDS_DIR / product_name / 'clean_minimal' / 'index.html',
            BUILDS_DIR / product_name / 'earthy_pastel' / 'index.html',
        ]
        build_path = next((p for p in candidates if p.exists()), None)

    html_preview = ''
    if build_path and Path(build_path).exists():
        html_preview = Path(build_path).read_text(encoding='utf-8')
        print(f'[naomi] Loaded HTML preview: {len(html_preview):,} chars from {build_path}')
    else:
        print(f'[naomi] No built HTML found for {product_name} — writing from spec only')

    # ── Call Claude ────────────────────────────────────────────────────────────
    client   = anthropic.Anthropic()
    prompt   = _build_prompt(product_spec, html_preview)
    messages = [{'role': 'user', 'content': prompt}]

    print(f'[naomi] Calling {MODEL} with web search for {display_name}...')

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
        messages=messages,
    )

    web_searches = sum(
        1 for b in response.content
        if getattr(b, 'type', '') in ('tool_use', 'server_tool_use')
        and 'web_search' in getattr(b, 'name', '')
    ) or sum(
        1 for b in response.content
        if 'web_search' in getattr(b, 'type', '')
    )

    total_in  = response.usage.input_tokens
    total_out = response.usage.output_tokens

    print(f'[naomi] Turn 1: {total_in}in + {total_out}out | {web_searches} searches')

    result_text = next(
        (b.text for b in response.content if getattr(b, 'type', '') == 'text'),
        '',
    )
    result = _extract_json(result_text)

    # ── Fallback turn ──────────────────────────────────────────────────────────
    if result is None and result_text:
        print('[naomi] No JSON in turn 1 — requesting JSON-only follow-up...')
        response2 = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
            messages=messages + [
                {'role': 'assistant', 'content': response.content},
                {'role': 'user',      'content':
                 'Output ONLY the JSON now — no prose, no markdown. Start with { and end with }.'},
            ],
        )
        total_in  += response2.usage.input_tokens
        total_out += response2.usage.output_tokens
        result_text = next(
            (b.text for b in response2.content if getattr(b, 'type', '') == 'text'), '',
        )
        result = _extract_json(result_text)

    cost = _save_cost('naomi', total_in, total_out, web_searches)
    print(f'[naomi] Total: {total_in}in + {total_out}out | {web_searches} searches | ${cost:.4f}')

    if result is None:
        print('[naomi] No parseable JSON — returning empty result')
        result = {
            'titles':          {'primary': '', 'variation_1': '', 'variation_2': ''},
            'description':     '',
            'tags':            [],
            'pricing':         {},
            'social_caption':  '',
            'screenshot_guide': [],
        }

    # ── Attach metadata ────────────────────────────────────────────────────────
    result['_meta'] = {
        'product_name':  product_name,
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'input_tokens':  total_in,
        'output_tokens': total_out,
        'web_searches':  web_searches,
        'cost_usd':      cost,
        'model':         MODEL,
    }

    # ── Save ───────────────────────────────────────────────────────────────────
    out_path = BUILDS_DIR / product_name / 'listing.json'
    _save_json(out_path, result)
    print(f'[naomi] Saved listing → {out_path}')

    # ── Telegram ───────────────────────────────────────────────────────────────
    primary  = result.get('titles', {}).get('primary', '')
    pricing  = result.get('pricing', {})
    b_price  = pricing.get('basic',    {}).get('price', '?')
    s_price  = pricing.get('standard', {}).get('price', '?')
    p_price  = pricing.get('premium',  {}).get('price', '?')
    n_tags   = len(result.get('tags', []))

    _send_telegram(
        f"NAOMI — LISTING READY\n"
        f"Product: {display_name}\n"
        f"Primary title: {primary[:100]}\n"
        f"Price tiers: ${b_price} / ${s_price} / ${p_price}\n"
        f"Tags: {n_tags} written\n"
        f"Full listing saved to builds/{product_name}/listing.json\n"
        f"Ready for Jase to post on Etsy"
    )

    return result


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description='Naomi — Etsy Listing Writer')
    parser.add_argument('--product', required=True,
                        help='Product name (key in product_specs.json)')
    args = parser.parse_args()

    result = write_listing(args.product)

    print('\n=== LISTING SUMMARY ===')
    titles  = result.get('titles', {})
    pricing = result.get('pricing', {})
    tags    = result.get('tags', [])

    print(f'Primary title:   {titles.get("primary", "")}')
    print(f'Variation 1:     {titles.get("variation_1", "")}')
    print(f'Variation 2:     {titles.get("variation_2", "")}')
    print()
    print(f'Tags ({len(tags)}): {", ".join(tags)}')
    print()
    for tier, info in pricing.items():
        print(f'  {tier.capitalize()}: ${info.get("price")} — {info.get("includes", "")[:80]}')
    print()
    print(f'Social caption:')
    print(f'  {result.get("social_caption", "")[:200]}')
    print()
    print(f'API cost: ${result.get("_meta", {}).get("cost_usd", 0):.4f}')


if __name__ == '__main__':
    main()

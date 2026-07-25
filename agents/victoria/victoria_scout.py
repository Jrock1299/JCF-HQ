"""
victoria_scout.py — Weekly skills/tools/MCP scouting. (Absorbed from Lucy.)

Lucy was retired 2026-07-25; this is her research scout, moved into Victoria's
codebase and run as an additional weekly output alongside the CFO tribunal.

Searches GitHub, Reddit, HackerNews, Product Hunt, Anthropic docs, and MCP
registries for external tools, skills, APIs, and MCP servers that can elevate
JCF HQ operations.

The findings are also handed to Victoria's weekly tribunal so she can rule on
them in her own voice — a scout reports, the CFO decides whether to spend.

Output:
    dashboard/victoria_scout.json   — latest week's findings
    logs/victoria_scout_history.json — rolling 52-week archive

    (dashboard/lucy_research.json is FROZEN as Lucy's archived final record.
     Nothing reads it; it is retained as history, not updated.)

Usage:
    python3 victoria_scout.py --research
    python3 victoria_scout.py --research --focus "MCP servers"
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/root/.openclaw/scripts')
from telegram_personalities import wrap_message

# ── Paths & constants ─────────────────────────────────────────────────────────

OUTPUT_PATH  = Path('/root/.openclaw/dashboard/victoria_scout.json')
HISTORY_PATH = Path('/root/.openclaw/logs/victoria_scout_history.json')

for _p in (OUTPUT_PATH.parent, HISTORY_PATH.parent):
    _p.mkdir(parents=True, exist_ok=True)

# Same routing Lucy used and Victoria's brain already uses: GPT-5.6 Terra,
# whitelisted in agents.defaults.models; gpt-5.5 as the proven fallback.
# The '-codex' suffixed ids are runtime-bound and rejected as --model overrides.
PRIMARY_MODEL  = 'openai/gpt-5.6-terra'
FALLBACK_MODEL = 'openai/gpt-5.5'

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT  = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID', '')

# ── Env loader ────────────────────────────────────────────────────────────────

def _load_env():
    try:
        with open('/etc/environment') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass

_load_env()
if not TELEGRAM_TOKEN:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
if not TELEGRAM_CHAT:
    TELEGRAM_CHAT = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID', '')

# ── System prompt ─────────────────────────────────────────────────────────────
# Ported from Lucy verbatim except the framing line: the scouting is now
# Victoria's, and she reports findings as a procurement brief, not a wishlist.

SYSTEM_PROMPT = """\
You are the scouting desk for JCF HQ, reporting to Victoria (CFO). Your \
mission is to find external tools, skills, APIs, MCP servers, and resources \
that can elevate JCF HQ across four categories:

1. TRADING & INVESTING — Claude Code skills for technical analysis, backtesting, \
   market data, options, screeners. New APIs for market data, news, economic \
   calendars. MCP servers connecting to trading/financial platforms. Open source \
   trading tools worth integrating.

2. AUTOMATION & AGENTS — Claude Code skills that improve agent workflows. Tools \
   that reduce API costs or improve reliability. Better orchestration patterns \
   or scheduling tools.

3. DASHBOARD & UI — Claude Code skills for React/frontend design. Component \
   libraries, chart libraries, UI frameworks. Dashboard templates or inspiration.

4. GENERAL PRODUCTIVITY — Anything that makes operations more seamless. Dev \
   tools, monitoring, logging improvements. Useful Claude Code skills from any category.

SEARCH STRATEGY:
- Search GitHub for repos tagged with Claude Code skills, MCP servers, trading tools
- Search Reddit (r/ClaudeAI, r/LocalLLaMA, r/algotrading) for new tools and skills
- Search HackerNews for trending developer tools and AI agent frameworks
- Check Anthropic docs and MCP registries for new/updated servers
- Look at Product Hunt for recently launched dev tools

SCORING:
- priority HIGH: Directly usable, high impact for JCF HQ operations
- priority MEDIUM: Useful but needs adaptation, or nice-to-have
- install_ready: true ONLY if it's a direct Claude Code skill that can be git cloned \
  and installed immediately (has a SKILL.md in a skills/ directory)

RULES:
- Maximum 10 findings, minimum 3
- Only include HIGH or MEDIUM priority finds
- Be specific about URLs — real GitHub repos, real documentation links
- For each find, explain specifically WHY it matters for JCF HQ (trading agents, \
dashboard, automation, etc.)
- Victoria pays the bills. Where a find has a cost or a maintenance burden, say so.

OUTPUT FORMAT (valid JSON only, no markdown):
{
  "date": "YYYY-MM-DD",
  "week_focus": "one line describing what you prioritized this week",
  "findings": [
    {
      "category": "TRADING|AUTOMATION|DASHBOARD|PRODUCTIVITY",
      "name": "tool/skill name",
      "url": "github or source url",
      "description": "2-3 sentences on what it does",
      "relevance": "1-2 sentences on why it matters for JCF HQ specifically",
      "priority": "HIGH|MEDIUM",
      "install_ready": true or false
    }
  ],
  "top_pick": "name of the single best find this week",
  "summary": "3-4 sentence executive summary of the week's research"
}"""

CORE_QUERIES = [
    'claude code skills trading',
    'claude code skills finance',
    'MCP server trading',
    'claude code skills new this week',
    'anthropic MCP registry',
]

ROTATING_QUERIES = [
    'claude code skills backtesting',
    'claude code skills react dashboard',
    'MCP server financial data',
    'open source algo trading python 2026',
    'claude code agent orchestration',
    'anthropic tool use examples new',
    'claude code skills automation',
    'MCP server broker API',
]

# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print('[victoria-scout] Telegram not configured — skipping')
        return
    try:
        import requests
        r = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT, 'text': text},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as e:
        print(f'[victoria-scout] Telegram error: {e}')


def _run_agent(prompt, model=PRIMARY_MODEL, timeout=120):
    """Run a prompt through the openclaw gateway agent. Returns response text or None."""
    cmd = [
        'openclaw', 'agent',
        '--agent', 'main',
        '--model', model,
        '--message', prompt,
        '--json',
        '--timeout', str(timeout),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
        if proc.returncode != 0:
            print(f'[victoria-scout] Agent call failed ({model}): {proc.stderr[:200]}')
            return None
        result = json.loads(proc.stdout)
        payloads = result.get('result', {}).get('payloads', [])
        return payloads[0].get('text', '') if payloads else None
    except subprocess.TimeoutExpired:
        print(f'[victoria-scout] Agent call timed out ({model})')
        return None
    except Exception as e:
        print(f'[victoria-scout] Agent call error ({model}): {e}')
        return None


# ── Search query builder ──────────────────────────────────────────────────────

def _pick_rotating_queries(count=3) -> list:
    week_num = datetime.now(timezone.utc).isocalendar()[1]
    start = (week_num * count) % len(ROTATING_QUERIES)
    picked = []
    for i in range(count):
        picked.append(ROTATING_QUERIES[(start + i) % len(ROTATING_QUERIES)])
    return picked


# ── Main function ─────────────────────────────────────────────────────────────

def research_tools(focus: str = None, send_telegram: bool = True) -> dict:
    """
    Research tools, skills, APIs, and MCP servers for JCF HQ.

    Args:
        focus:         Optional topic to prioritize (e.g. 'MCP servers').
        send_telegram: False when called from the weekly tribunal, which folds
                       the findings into its own message instead of sending two.

    Returns:
        Research dict with scored findings.
    """
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    rotating = _pick_rotating_queries(3)
    all_queries = CORE_QUERIES + rotating

    focus_line = f'\nSPECIAL FOCUS THIS WEEK: {focus}' if focus else ''

    prompt = f"""{SYSTEM_PROMPT}

TODAY'S DATE: {today}{focus_line}

SEARCH QUERIES TO USE (use web_search for each):
{chr(10).join(f'- {q}' for q in all_queries)}

After searching, compile your findings into the JSON format specified above.
Output ONLY the JSON — no markdown, no prose. Start with {{ end with }}."""

    print(f'[victoria-scout] Starting skills & tools research...')
    print(f'[victoria-scout] Queries: {len(all_queries)} ({len(CORE_QUERIES)} core + {len(rotating)} rotating)')
    if focus:
        print(f'[victoria-scout] Focus: {focus}')

    result = None
    used_model = None

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        print(f'[victoria-scout] Trying model: {model}')
        text = _run_agent(prompt, model=model, timeout=180)
        if text is None:
            print(f'[victoria-scout] No response from {model} — trying fallback')
            continue

        result = _extract_json(text)
        if result is not None:
            used_model = model
            break

        print(f'[victoria-scout] No JSON in response from {model} — requesting JSON-only follow-up')
        followup = (
            'Your previous response did not contain valid JSON. '
            'Output ONLY the JSON now — no markdown, no prose. Start with { end with }.\n\n'
            f'Previous response excerpt:\n{text[:500]}'
        )
        text2 = _run_agent(followup, model=model, timeout=60)
        if text2:
            result = _extract_json(text2)
            if result is not None:
                used_model = model
                break

    if result is None:
        print('[victoria-scout] No parseable JSON returned from any model')
        result = {
            'date':       today,
            'week_focus': focus or 'research failed',
            'findings':   [],
            'top_pick':   'none',
            'summary':    'Research failed to return parseable JSON.',
        }
        used_model = 'none'

    # ── Attach metadata ───────────────────────────────────────────────────────
    result['_meta'] = {
        'timestamp':   datetime.now(timezone.utc).isoformat(),
        'focus':       focus,
        'model':       used_model,
        'queries':     all_queries,
        'absorbed_from': 'lucy (retired 2026-07-25)',
    }

    # ── Save outputs ──────────────────────────────────────────────────────────
    _save_json(OUTPUT_PATH, result)
    print(f'[victoria-scout] Saved research → {OUTPUT_PATH}')

    history = _load_json(HISTORY_PATH, [])
    if not isinstance(history, list):
        history = []
    history.append(result)
    _save_json(HISTORY_PATH, history[-52:])

    if send_telegram:
        _send_telegram(format_telegram(result))

    return result


def format_telegram(result: dict) -> str:
    """Render findings for Telegram, in Victoria's voice."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    findings      = result.get('findings', [])
    high_finds    = [f for f in findings if f.get('priority') == 'HIGH']
    med_finds     = [f for f in findings if f.get('priority') == 'MEDIUM']
    install_ready = [f for f in findings if f.get('install_ready')]

    lines = [
        'THE SCOUTING REPORT',
        f'Week of: {result.get("date", today)}',
        f'Focus: {result.get("week_focus", "general")}',
        '',
        f'My pick: {result.get("top_pick", "nothing worth the coin")}',
        '',
        f'Brought before me: {len(findings)} '
        f'({len(high_finds)} HIGH / {len(med_finds)} MEDIUM)',
        f'{len(install_ready)} could be installed today.',
    ]

    if high_finds:
        lines.append('')
        for f in high_finds:
            lines.append(f'• {f.get("name", "?")} [{f.get("category", "?")}]')
            lines.append(f'  {f.get("description", "")[:80]}')

    lines.append('')
    lines.append('Full ledger: victoria_scout.json')
    lines.append('')
    lines.append('— Victoria')

    return wrap_message('victoria', '\n'.join(lines))


def summarize_for_tribunal(result: dict) -> str:
    """Compact text block for the weekly tribunal prompt."""
    findings = result.get('findings', [])
    if not findings:
        return 'SCOUTING REPORT: no findings this week.'
    lines = [
        f'SCOUTING REPORT ({result.get("date","?")}) — '
        f'{len(findings)} findings, top pick: {result.get("top_pick","?")}',
        f'  Focus: {result.get("week_focus","")}',
    ]
    for f in findings[:10]:
        lines.append(
            f"  [{f.get('priority','?')}] {f.get('name','?')} ({f.get('category','?')})"
            f"{' [INSTALL-READY]' if f.get('install_ready') else ''}"
        )
        lines.append(f"      {f.get('relevance','')[:160]}")
    if result.get('summary'):
        lines.append(f"  Summary: {result['summary'][:400]}")
    return '\n'.join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description='Victoria — Weekly Scouting Desk')
    parser.add_argument('--research', action='store_true', help='Run weekly research')
    parser.add_argument('--focus', default=None, metavar='TOPIC',
                        help='Focus the research on a specific area (e.g. "MCP servers")')
    parser.add_argument('--no-telegram', action='store_true', help='Skip the Telegram send')
    args = parser.parse_args()

    if not args.research:
        parser.print_help()
        return

    result = research_tools(focus=args.focus, send_telegram=not args.no_telegram)

    findings = result.get('findings', [])
    print(f'\n=== SCOUTING RESULTS ({len(findings)} findings) ===')
    print(f'Focus: {result.get("week_focus", "")}')
    print(f'Top pick: {result.get("top_pick", "")}')
    print()
    for f in findings:
        pri = f.get('priority', '?')
        rdy = ' [INSTALL-READY]' if f.get('install_ready') else ''
        print(f'  [{pri}] {f.get("name", "?")} ({f.get("category", "?")}){rdy}')
        print(f'        {f.get("description", "")[:90]}')
        print(f'        URL: {f.get("url", "?")}')
        print()
    print(f'Summary: {result.get("summary", "")}')


if __name__ == '__main__':
    main()

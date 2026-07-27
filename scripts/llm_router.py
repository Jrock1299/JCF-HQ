#!/usr/bin/env python3
"""llm_router.py — one routing layer for every JCF HQ agent that calls a model.

Chain per job type:

    Codex (primary, free, subscription back Aug 23)
      -> assigned OpenRouter model for that job
      -> 2nd OpenRouter choice
      -> Anthropic (final safety net only)

Model selection per job is EXPLICIT. OpenRouter's own `models` array is used
for in-request failover between our two chosen ids, but we never hand the
choice to `openrouter/auto` — Jase wants control over which models run, not a
black box that defaults everything to one provider.

Every call logs which model actually served it (logs/llm_router_spend.json) so
cost is attributable per agent, per job, per model. A daily OpenRouter spend
ceiling halts routing and fires one Telegram alert.

    from llm_router import route
    text, meta = route('report_writing', system_prompt, user_message, agent='victoria')
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/root/.openclaw/scripts')

LOGS = Path('/root/.openclaw/logs')
SPEND_LOG = LOGS / 'llm_router_spend.json'
MENU_PATH = Path('/root/.openclaw/dashboard/openrouter_menu.json')

OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
CODEX_MODEL = 'openai/gpt-5.6-terra'
ANTHROPIC_MODEL = 'claude-sonnet-4-6'

# ── Guardrail ─────────────────────────────────────────────────────────────────
# $2.00/day. Rationale: the assigned primaries are all FREE tier, so normal
# operation should spend $0. This ceiling exists to catch a runaway loop or a
# silent fall-through to paid models — at the assigned paid rates ($0.03-$0.40
# per M output) $2/day is thousands of reports, i.e. it never binds in normal
# use but caps a bug hard. Override with OPENROUTER_DAILY_CEILING_USD.
DAILY_CEILING_USD = float(os.getenv('OPENROUTER_DAILY_CEILING_USD', '2.00'))

# ══════════════════════════════════════════════════════════════════════════════
# JOB → MODEL MAP
# ══════════════════════════════════════════════════════════════════════════════
# Every id, price and capability below was taken from the LIVE catalog on
# 2026-07-27 via scripts/openrouter_catalog.py. Re-run that to refresh prices,
# then revisit these picks.
#
# Variety is deliberate: 8 distinct model families across 4 jobs, so no single
# provider carries the whole system. Where quality is comparable the tie goes
# to a different family than the job above it.

JOBS: dict[str, dict] = {
    'report_writing': {
        'description': 'Victoria daily/weekly, Council synthesis — reasoning + '
                       'clean structure, moderate length, large input payload.',
        'primary': 'nvidia/nemotron-3-super-120b-a12b:free',
        'fallback': 'deepseek/deepseek-v3.2',
        'second_fallback': 'qwen/qwen3.5-flash-02-23',
        'why': ('120B MoE (12B active) is the largest FREE model that also '
                'advertises structured_outputs + tools, with 262k context for '
                "Victoria's large payloads. DeepSeek V3.2 ($0.269/$0.400) is a "
                'genuinely different reasoning lineage as first paid backstop; '
                'Qwen3.5 Flash ($0.065/$0.260, 1M ctx) is cheaper still and a '
                'third family again.'),
    },
    'quick_summary': {
        'description': 'Tier-1 glances, short summaries — cheapest capable, '
                       'speed matters, output is short.',
        'primary': 'google/gemma-4-26b-a4b-it:free',
        'fallback': 'inclusionai/ling-2.6-flash',
        'second_fallback': 'mistralai/mistral-nemo',
        'why': ('Gemma 4 26B-A4B activates only ~4B params — fast, free, and '
                'still structured_outputs + tools at 262k ctx. Ling 2.6 Flash '
                '($0.010/$0.030) and Mistral Nemo ($0.019/$0.030) are the two '
                'cheapest paid models in the entire filtered pool, from two '
                'more families.'),
    },
    'heavy_analysis': {
        'description': 'Regime reasoning, strategy logic — best reasoning '
                       'available inside the cheap tier, long context.',
        'primary': 'nvidia/nemotron-3-ultra-550b-a55b:free',
        'fallback': 'deepseek/deepseek-v4-flash',
        'second_fallback': 'z-ai/glm-4.7-flash',
        'why': ('Nemotron 3 Ultra is 550B total / 55B active at 1M context and '
                'costs nothing — the strongest free reasoner in the pool. '
                'DeepSeek V4 Flash ($0.140/$0.280, 1M ctx) and GLM-4.7-Flash '
                '($0.060/$0.400, 202k) keep two more families in reserve.'),
    },
    'structured_output': {
        'description': 'Code-ish / tool-use / strict-JSON tasks.',
        'primary': 'openai/gpt-oss-20b:free',
        'fallback': 'qwen/qwen3.5-9b',
        'second_fallback': 'nvidia/nemotron-nano-9b-v2:free',
        'why': ('gpt-oss-20b is purpose-built for tool use and constrained '
                'output and is free. Qwen3.5-9B ($0.100/$0.150, 262k) is a '
                'strong code family; Nemotron Nano 9B is free again as the '
                'last hop. All three advertise structured_outputs AND tools — '
                'non-negotiable for this job.'),
    },
}

DEFAULT_JOB = 'report_writing'


# ══════════════════════════════════════════════════════════════════════════════
# Spend tracking + guardrail
# ══════════════════════════════════════════════════════════════════════════════

def _load_spend() -> list:
    try:
        return json.loads(SPEND_LOG.read_text())
    except Exception:
        return []


def _today() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def spend_today() -> float:
    return round(sum(e.get('cost_usd', 0.0) for e in _load_spend()
                     if e.get('date') == _today()), 6)


def _model_prices(model_id: str) -> tuple[float, float]:
    """($/M input, $/M output) for a model id, from the cached live menu."""
    try:
        menu = json.loads(MENU_PATH.read_text())
        for m in menu.get('models', []):
            if m['id'] == model_id:
                return m['in_per_m'], m['out_per_m']
    except Exception:
        pass
    return 0.0, 0.0


def _record(agent: str, job: str, model: str, provider: str,
            in_tok: int, out_tok: int, ok: bool, note: str = '') -> float:
    pin, pout = _model_prices(model)
    cost = round((in_tok / 1e6) * pin + (out_tok / 1e6) * pout, 6) if provider == 'openrouter' else 0.0
    entry = {
        'date': _today(),
        'ts': datetime.now(timezone.utc).isoformat(),
        'agent': agent, 'job': job, 'provider': provider, 'model': model,
        'input_tokens': in_tok, 'output_tokens': out_tok,
        'cost_usd': cost, 'ok': ok, 'note': note,
    }
    log = _load_spend()
    log.append(entry)
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        SPEND_LOG.write_text(json.dumps(log[-5000:], indent=2))
    except Exception as e:
        print(f'[router] spend log write failed: {e}')
    return cost


def _alert_ceiling(spent: float) -> None:
    """One Telegram alert per day when the ceiling trips."""
    marker = LOGS / f'.or_ceiling_alerted_{_today()}'
    if marker.exists():
        return
    msg = (f'🚨 OpenRouter daily spend ceiling hit\n\n'
           f'Spent today: ${spent:.4f}\nCeiling: ${DAILY_CEILING_USD:.2f}\n\n'
           f'OpenRouter routing is HALTED for the rest of the UTC day. Agents '
           f'fall straight through to the Anthropic safety net.\n\n'
           f'The assigned primaries are all free-tier, so any real spend means '
           f'something fell through — check logs/llm_router_spend.json.')
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')
    if token and chat:
        try:
            import requests
            requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                          json={'chat_id': chat, 'text': msg}, timeout=15)
        except Exception as e:
            print(f'[router] ceiling alert failed: {e}')
    print(f'[router] {msg}')
    try:
        marker.write_text(datetime.now(timezone.utc).isoformat())
    except Exception:
        pass


def ceiling_ok() -> bool:
    spent = spend_today()
    if spent >= DAILY_CEILING_USD:
        _alert_ceiling(spent)
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# Providers
# ══════════════════════════════════════════════════════════════════════════════

def _call_codex(system: str, user: str, timeout: int = 300) -> str | None:
    if os.getenv('JCF_FORCE_CODEX_UNAVAILABLE') == '1':
        print('[router] Codex forced unavailable (test mode)')
        return None
    combined = f'{system}\n\n=== TASK ===\n\n{user}'
    tmp = None
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.txt', prefix='router_',
                                         dir='/tmp', delete=False, encoding='utf-8') as fh:
            fh.write(combined)
            tmp = fh.name
        proc = subprocess.run(
            ['openclaw', 'agent', '--agent', 'main', '--model', CODEX_MODEL,
             '--message-file', tmp, '--json', '--timeout', str(timeout)],
            capture_output=True, text=True, timeout=timeout + 60)
        if proc.returncode != 0:
            print(f'[router] codex unavailable: {proc.stderr[:160]}')
            return None
        payloads = json.loads(proc.stdout).get('result', {}).get('payloads', [])
        return payloads[0].get('text', '') if payloads else None
    except Exception as e:
        print(f'[router] codex error: {e}')
        return None
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _call_openrouter(models: list[str], system: str, user: str,
                     timeout: int = 300) -> tuple[str | None, dict]:
    """Call OpenRouter with an EXPLICIT model list.

    `models` is our own ordered shortlist — OpenRouter fails over between
    exactly these ids and nothing else. This is in-request failover, not
    auto-selection.
    """
    key = os.getenv('OPENROUTER_API_KEY')
    if not key:
        return None, {'error': 'OPENROUTER_API_KEY not set'}
    body = {
        'model': models[0],
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': user}],
    }
    if len(models) > 1:
        body['models'] = models          # explicit shortlist, in our order
    req = urllib.request.Request(
        OPENROUTER_URL, method='POST',
        data=json.dumps(body).encode(),
        headers={
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://github.com/Jrock1299/JCF-HQ',
            'X-Title': 'JCF HQ',
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return None, {'error': f'HTTP {e.code}: {e.read().decode()[:200]}'}
    except Exception as e:
        return None, {'error': str(e)}

    choices = data.get('choices') or []
    text = choices[0].get('message', {}).get('content') if choices else None
    usage = data.get('usage') or {}
    return text, {
        'served_by': data.get('model', models[0]),
        'input_tokens': usage.get('prompt_tokens', 0),
        'output_tokens': usage.get('completion_tokens', 0),
    }


def _call_anthropic(system: str, user: str) -> tuple[str | None, dict]:
    try:
        import anthropic
    except ImportError:
        return None, {'error': 'anthropic SDK not installed'}
    try:
        r = anthropic.Anthropic().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=8192,
            system=system, messages=[{'role': 'user', 'content': user}])
        return (r.content[0].text if r.content else None), {
            'served_by': ANTHROPIC_MODEL,
            'input_tokens': r.usage.input_tokens,
            'output_tokens': r.usage.output_tokens,
        }
    except Exception as e:
        return None, {'error': str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# The chain
# ══════════════════════════════════════════════════════════════════════════════

def route(job: str, system: str, user: str, agent: str = 'unknown',
          timeout: int = 300) -> tuple[str | None, dict]:
    """Run the fallback chain for a job type. Returns (text, meta)."""
    cfg = JOBS.get(job) or JOBS[DEFAULT_JOB]
    if job not in JOBS:
        print(f'[router] unknown job {job!r} — using {DEFAULT_JOB}')
        job = DEFAULT_JOB

    # 1. Codex — primary, free while the subscription lasts.
    text = _call_codex(system, user, timeout)
    if text:
        _record(agent, job, CODEX_MODEL, 'codex', 0, 0, True)
        return text, {'provider': 'codex', 'model': CODEX_MODEL, 'hop': 1}

    # 2 + 3. OpenRouter — our two explicit picks, in our order.
    shortlist = [cfg['fallback'], cfg['second_fallback']]
    shortlist = [cfg['primary']] + shortlist
    if not os.getenv('OPENROUTER_API_KEY'):
        print('[router] OPENROUTER_API_KEY not set — skipping OpenRouter hops')
    elif not ceiling_ok():
        print('[router] daily OpenRouter ceiling reached — skipping to Anthropic')
    else:
        text, meta = _call_openrouter(shortlist, system, user, timeout)
        if text:
            cost = _record(agent, job, meta.get('served_by', shortlist[0]),
                           'openrouter', meta.get('input_tokens', 0),
                           meta.get('output_tokens', 0), True)
            return text, {'provider': 'openrouter', 'model': meta.get('served_by'),
                          'hop': 2, 'cost_usd': cost,
                          'shortlist': shortlist}
        print(f'[router] openrouter failed: {meta.get("error", "?")[:160]}')

    # 4. Anthropic — final safety net only.
    text, meta = _call_anthropic(system, user)
    if text:
        _record(agent, job, ANTHROPIC_MODEL, 'anthropic',
                meta.get('input_tokens', 0), meta.get('output_tokens', 0), True)
        return text, {'provider': 'anthropic', 'model': ANTHROPIC_MODEL, 'hop': 4}

    _record(agent, job, 'none', 'none', 0, 0, False, 'all hops failed')
    return None, {'provider': None, 'error': 'all hops failed'}


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--show', action='store_true', help='print the job->model map')
    ap.add_argument('--spend', action='store_true', help='spend summary')
    ap.add_argument('--test', metavar='JOB', help='run a live probe for a job')
    a = ap.parse_args()

    if a.show or not any(vars(a).values()):
        print(f'Daily OpenRouter ceiling: ${DAILY_CEILING_USD:.2f}\n')
        for name, c in JOBS.items():
            print(f'── {name}')
            print(f'   {c["description"]}')
            for label, key in (('primary        ', 'primary'),
                               ('fallback 1     ', 'fallback'),
                               ('fallback 2     ', 'second_fallback')):
                pin, pout = _model_prices(c[key])
                tag = 'FREE' if (pin == 0 and pout == 0) else f'${pin:.3f}/${pout:.3f} per M'
                print(f'   {label} {c[key]:46} {tag}')
            print()
    if a.spend:
        log = _load_spend()
        print(f'spend today: ${spend_today():.6f} / ${DAILY_CEILING_USD:.2f}')
        by = {}
        for e in log:
            k = (e['provider'], e['model'])
            by[k] = by.get(k, 0) + e.get('cost_usd', 0)
        for (p, m), c in sorted(by.items(), key=lambda z: -z[1]):
            print(f'  {p:12} {m:48} ${c:.6f}')
    if a.test:
        t, meta = route(a.test, 'You are a test harness.',
                        'Reply with exactly: ROUTER OK', agent='cli-test')
        print(f'\nresult: {t!r}\nmeta: {json.dumps(meta, indent=2)}')
    return 0


if __name__ == '__main__':
    sys.exit(_cli())

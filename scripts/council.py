#!/usr/bin/env python3
"""
council.py — Multi-agent investment council for JCF HQ.

Lens, Jarvis, and Norman each INDEPENDENTLY research and take a position on
(a) existing holdings — deepen conviction or flag an exit, and (b) new scouting
— opportunities not yet held. Independent notes are written first (real debate,
not groupthink); a synthesis pass then produces a final verdict. Output is
written to dashboard/council.json (agent notes + verdict + full transcript) and
delivered via Telegram + Discord (#council-theses).

Weekly, same day as the Lens portfolio thesis (Sunday). Models: Lens = Anthropic
claude-sonnet-4-6 + web search; Jarvis / Norman / synthesis = Codex gpt-5.6-terra.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/root/.openclaw/scripts')
sys.path.insert(0, '/root/.openclaw/agents/lens')
from lens_portfolio_thesis import gather_holdings           # reuse the holdings reader
try:
    from discord_notify import notify as discord_notify
except Exception:
    discord_notify = None

DASH  = Path('/root/.openclaw/dashboard')
OUT   = DASH / 'council.json'
CODEX_MODEL = 'openai/gpt-5.6-terra'
TG_MAX = 4000
TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')

PERSONAS = {
    'lens':   "You are Lens, JCF HQ's macro analyst. Ground your view in current "
              "facts via web search — macro regime, sector rotation, catalysts.",
    'jarvis': "You are Jarvis, JCF HQ's calm regime/technical strategist. Judge "
              "positioning by market regime, trend, and technical structure.",
    'norman': "You are Norman, JCF HQ's cold, brutally honest risk validator. "
              "Default to skepticism; your job is to flag weak positions and risk.",
}


def _run_codex(system, user, timeout=300):
    combined = f"{system}\n\n=== TASK ===\n\n{user}"
    tmp = None
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.txt', prefix='council_',
                                         dir='/tmp', delete=False, encoding='utf-8') as fh:
            fh.write(combined); tmp = fh.name
        proc = subprocess.run(
            ['openclaw', 'agent', '--agent', 'main', '--model', CODEX_MODEL,
             '--message-file', tmp, '--json', '--timeout', str(timeout)],
            capture_output=True, text=True, timeout=timeout + 60)
        if proc.returncode != 0:
            print(f'[council] codex failed: {proc.stderr[:200]}'); return None
        payloads = json.loads(proc.stdout).get('result', {}).get('payloads', [])
        return payloads[0].get('text', '') if payloads else None
    except Exception as e:
        print(f'[council] codex error: {e}'); return None
    finally:
        if tmp:
            try: os.remove(tmp)
            except OSError: pass


def _run_lens(system, user):
    try:
        import anthropic
        r = anthropic.Anthropic().messages.create(
            model='claude-sonnet-4-6', max_tokens=4096, system=system,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
            messages=[{'role': 'user', 'content': user}])
        return ''.join(b.text for b in r.content
                       if getattr(b, 'type', '') == 'text' and getattr(b, 'text', ''))
    except Exception as e:
        print(f'[council] lens(anthropic) error: {e}'); return None


def _holdings_context(holdings):
    total = sum((x['value'] or 0) for x in holdings) or 1.0
    rows = [f"  {x['symbol']} [{x['account']}] ${(x['value'] or 0):,.0f} "
            f"({100*(x['value'] or 0)/total:.1f}%)" for x in
            sorted(holdings, key=lambda z: -(z['value'] or 0))]
    return f"CURRENT HOLDINGS (${total:,.0f} across connected accounts):\n" + "\n".join(rows)


def _note_prompt(ctx):
    return (ctx + "\n\nWrite your INDEPENDENT council note (do not assume other "
            "agents' views). Cover BOTH:\n"
            "(a) EXISTING HOLDINGS — for the notable ones, deepen conviction or "
            "flag an exit, with your reason.\n"
            "(b) NEW SCOUTING — 1-3 opportunities NOT yet held that fit your lens.\n"
            "Be concise and specific. Plain text, ~1500 chars max.")


def run_council():
    holdings = gather_holdings()
    ctx = _holdings_context(holdings)
    prompt = _note_prompt(ctx)

    # --- Independent notes (no shared context) ---
    notes = {}
    notes['lens']   = _run_lens(PERSONAS['lens'], prompt) or '(Lens note unavailable)'
    notes['jarvis'] = _run_codex(PERSONAS['jarvis'], prompt) or '(Jarvis note unavailable)'
    notes['norman'] = _run_codex(PERSONAS['norman'], prompt) or '(Norman note unavailable)'

    # --- Synthesis pass ---
    synth_sys = ("You are the JCF HQ Council chair. Combine three independent agent "
                 "notes into ONE final verdict. Where they agree, state the shared "
                 "conviction; where they conflict, adjudicate and explain. End with a "
                 "clear action list: HOLD/ADD/TRIM/EXIT per relevant name, plus top "
                 "scouting picks. Plain text.")
    synth_user = (ctx + "\n\n=== INDEPENDENT NOTES ===\n\n"
                  f"[LENS]\n{notes['lens']}\n\n[JARVIS]\n{notes['jarvis']}\n\n"
                  f"[NORMAN]\n{notes['norman']}\n\nWrite the final Council verdict.")
    verdict = _run_codex(synth_sys, synth_user) or '(Synthesis unavailable)'

    result = {
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'notes': notes,                       # independent per-agent (the debate)
        'verdict': verdict,                   # synthesized final call
        'transcript': [                       # ordered full debate for the expand view
            {'agent': 'lens', 'note': notes['lens']},
            {'agent': 'jarvis', 'note': notes['jarvis']},
            {'agent': 'norman', 'note': notes['norman']},
            {'agent': 'council', 'note': verdict},
        ],
        '_meta': {'models': {'lens': 'claude-sonnet-4-6',
                             'jarvis': CODEX_MODEL, 'norman': CODEX_MODEL,
                             'synthesis': CODEX_MODEL}},
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(f'[council] wrote {OUT}')
    _deliver(result)
    return result


def _deliver(result):
    body = (f"🏛️ JCF HQ COUNCIL — {result['date']}\n\n"
            f"🌐 LENS\n{result['notes']['lens']}\n\n"
            f"♟️ JARVIS\n{result['notes']['jarvis']}\n\n"
            f"⚠️ NORMAN\n{result['notes']['norman']}\n\n"
            f"⚖️ VERDICT\n{result['verdict']}")
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        import requests
        for i in range(0, len(body), TG_MAX):
            try:
                requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
                              json={'chat_id': TELEGRAM_CHAT_ID, 'text': body[i:i + TG_MAX]}, timeout=15)
            except Exception as e:
                print(f'[council] Telegram error: {e}'); break
    else:
        print('[council] Telegram not configured — skipping')
    # Discord: #council-theses (DISCORD_WEBHOOK_COUNCIL_THESES). No-op until Jase
    # provides the webhook — the integration point is wired and ready.
    if discord_notify:
        try:
            print('[council] Discord:', discord_notify('council', body, channels=['COUNCIL_THESES']))
        except Exception as e:
            print(f'[council] Discord skipped: {e}')


if __name__ == '__main__':
    run_council()

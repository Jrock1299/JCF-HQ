#!/usr/bin/env python3
"""
council.py — Multi-agent investment council for JCF HQ.

Lens, Victoria, and Huncho each INDEPENDENTLY research and take a position on
(a) existing holdings — deepen conviction or flag an exit, and (b) new scouting
— opportunities not yet held. Independent notes are written first (real debate,
not groupthink); a synthesis pass then produces a final verdict. Output is
written to dashboard/council.json (agent notes + verdict + full transcript) and
delivered via Telegram + Discord (#council-theses).

Weekly, same day as the Lens portfolio thesis (Sunday). Lens uses its own direct
Anthropic key + web search; Victoria / Huncho / synthesis route through
scripts/llm_router.py (Codex -> free OpenRouter picks -> Anthropic safety net).

Roster rebuilt 2026-07-27: Jarvis and Norman were retired 2026-07-25 but were
still being convened. See PERSONAS below for why Huncho took the third seat.
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

# ── Council roster (rebuilt 2026-07-27) ───────────────────────────────────────
# Was: Lens + Jarvis + Norman. Jarvis and Norman were RETIRED 2026-07-25, so
# two thirds of the council were ghosts — their personas still ran, but no
# retired agent owns any data or duty any more, and the roster contradicted
# the consolidation everywhere else in the system.
#
# Now the two live agents plus one deliberately different third seat:
#
#   Lens     — macro//external view, with web search. Unchanged.
#   Victoria — CFO. Owns the books, the balances and the risk validation for
#              Jerry + Chad, so she inherits Norman's skeptic role naturally
#              and speaks from data she actually holds.
#   Huncho   — the orchestrator, and the third perspective chosen on purpose.
#              A two-agent council is a conversation, not a council: with only
#              Lens and Victoria, macro-vs-books ties have no tiebreaker. Huncho
#              already owns execution and sizing across the fleet, so he
#              contributes the "can we actually run this" view neither of the
#              other two covers — and he is live, not a revived ghost.
PERSONAS = {
    'lens':     "You are Lens, JCF HQ's macro analyst. Ground your view in current "
                "facts via web search — macro regime, sector rotation, catalysts.",
    'victoria': "You are Victoria, JCF HQ's CFO and Chief of Staff — gothic-queen "
                "energy, owns the operation, never coddles. You hold the books: "
                "balances, realised P&L, and the risk validation for Jerry and "
                "Chad. Judge positions on what the data actually supports, and "
                "refuse to grade anything whose feed is stale or absent.",
    'huncho':   "You are Huncho, JCF HQ's orchestrator — NY mob-boss energy, "
                "terse and knowing. You own execution: position sizing, risk "
                "rails, and whether the fleet can actually run a plan. Judge "
                "each idea on executability and concentration, not narrative.",
}


def _run_codex(system, user, timeout=300, job='report_writing', agent='council'):
    """Council model call via the shared router (scripts/llm_router.py).

    Codex -> assigned free OpenRouter model -> 2nd pick -> Anthropic.
    Name kept for call-site compatibility.
    """
    from llm_router import route
    text, meta = route(job, system, user, agent=agent, timeout=timeout)
    if text:
        print(f"[council] {agent} served by {meta.get('provider')}:{meta.get('model')}")
    return text


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
    notes['lens']     = _run_lens(PERSONAS['lens'], prompt) or '(Lens note unavailable)'
    notes['victoria'] = _run_codex(PERSONAS['victoria'], prompt,
                                   agent='council:victoria') or '(Victoria note unavailable)'
    notes['huncho']   = _run_codex(PERSONAS['huncho'], prompt,
                                   agent='council:huncho') or '(Huncho note unavailable)'

    # --- Synthesis pass ---
    synth_sys = ("You are the JCF HQ Council chair. Combine three independent agent "
                 "notes into ONE final verdict. Where they agree, state the shared "
                 "conviction; where they conflict, adjudicate and explain. End with a "
                 "clear action list: HOLD/ADD/TRIM/EXIT per relevant name, plus top "
                 "scouting picks. Plain text.")
    synth_user = (ctx + "\n\n=== INDEPENDENT NOTES ===\n\n"
                  f"[LENS]\n{notes['lens']}\n\n[VICTORIA]\n{notes['victoria']}\n\n"
                  f"[HUNCHO]\n{notes['huncho']}\n\nWrite the final Council verdict.")
    verdict = _run_codex(synth_sys, synth_user,
                         agent='council:synthesis') or '(Synthesis unavailable)'

    result = {
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'notes': notes,                       # independent per-agent (the debate)
        'verdict': verdict,                   # synthesized final call
        'transcript': [                       # ordered full debate for the expand view
            {'agent': 'lens', 'note': notes['lens']},
            {'agent': 'victoria', 'note': notes['victoria']},
            {'agent': 'huncho', 'note': notes['huncho']},
            {'agent': 'council', 'note': verdict},
        ],
        '_meta': {'roster': list(PERSONAS),
                  'routing': 'scripts/llm_router.py (job=report_writing)',
                  'models': {'lens': 'claude-sonnet-4-6 (direct, own key)'}},
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(f'[council] wrote {OUT}')
    _deliver(result)
    return result


TIER2_PATH = DASH / 'council_v2.json'


def build_two_tier(result):
    """Council report through the SHARED two-tier module (scripts/agent_report.py).

    Was: all four full agent notes concatenated into one Telegram message —
    the densest wall in the system, with the actual verdict buried at the
    bottom. Now the verdict leads, each agent gets one headline, and the full
    debate transcript moves to Tier 2 where it can be expanded per section.
    """
    from agent_report import Report

    verdict = (result.get('verdict') or '').strip()
    r = Report(agent='council', kind='council', date=result.get('date', ''))

    # The decision is whatever the chair concluded — take its leading lines.
    lines = [l.strip(' -•\t') for l in verdict.split('\n') if l.strip()]
    if lines:
        r.decide(*lines[:3])
    else:
        r.decide('No verdict produced — synthesis unavailable.')

    # One headline per agent: their stance, not their essay. Skip markdown
    # titles, separators and "(unavailable)" placeholders — a heading is not
    # a position.
    def _stance(note: str) -> str:
        for raw in str(note).split('\n'):
            line = raw.strip().strip('*_# ').strip()
            if len(line) < 25:
                continue
            if line.startswith(('---', '===', '|')):
                continue
            if line.lower().startswith(('lens //', 'victoria //', 'huncho //',
                                        'jarvis //', 'norman //')):  # incl. archived
                continue
            if 'unavailable' in line.lower():
                continue
            return line
        return ''

    for agent, note in (result.get('notes') or {}).items():
        stance = _stance(note)
        if stance:
            r.headline(f'{agent.capitalize()}: {stance}')

    r.section('Decision', body=verdict, collapsed=False)
    r.section('Reasoning',
              rows=[{'agent': t.get('agent'), 'note': t.get('note')}
                    for t in (result.get('transcript') or [])])
    return r


def _deliver(result):
    try:
        report_obj = build_two_tier(result)
        body = report_obj.tier1()
        report_obj.write_tier2(TIER2_PATH)
        print(f'[council] Tier 2 written → {TIER2_PATH}')
    except Exception as e:
        print(f'[council] two-tier build failed ({e}); falling back to long form')
        body = (f"🏛️ JCF HQ COUNCIL — {result['date']}\n\n"
                + "\n\n".join(f"{a.upper()}\n{n}" for a, n in result['notes'].items())
                + f"\n\n⚖️ VERDICT\n{result['verdict']}")
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

#!/usr/bin/env python3
"""
Hub Collaboration — gathers multi-agent context and synthesises a unified
response via Claude, then posts it back to the Agent Hub and Telegram.

Usage:
    python3 hub_collab.py "Should we add GBP/JPY to Blade's instruments?"
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import requests

# ── Paths ──────────────────────────────────────────────────────────────────
MARKET_BIAS_PATH  = '/root/.openclaw/dashboard/market_bias.json'
ORACLE_PICKS_PATH = '/root/.openclaw/dashboard/oracle_picks.json'
HUB_PATH          = '/root/.openclaw/dashboard/agent_hub.json'
ADVISOR_LOG       = '/root/.openclaw/agents/advisor/advisor.log'
BLADE_LOG         = '/root/.openclaw/agents/blade/bot/blade.log'
CRISP_LOG         = '/root/.openclaw/agents/crisp/bot/crisp.log'
LENS_LOG          = '/root/.openclaw/agents/lens/bot/lens.log'

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID   = os.environ.get('TELEGRAM_ALERT_CHAT_ID') or '797062420'


# ── Helpers ────────────────────────────────────────────────────────────────

def tail_log(path, n=60):
    """Return last n lines of a log file, or an unavailable notice."""
    try:
        with open(path, 'r', errors='replace') as f:
            lines = f.readlines()
        return ''.join(lines[-n:]).strip() or '[empty log]'
    except Exception as e:
        return f'[unavailable: {e}]'


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def add_hub_message(agent, msg_type, message, tags=None):
    data = load_json(HUB_PATH) or {"messages": [], "max_messages": 500}
    msg = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "type": msg_type,
        "message": message,
        "tags": tags or [],
    }
    data["messages"].append(msg)
    cap = data.get("max_messages", 500)
    if len(data["messages"]) > cap:
        data["messages"] = data["messages"][-cap:]
    with open(HUB_PATH, 'w') as f:
        json.dump(data, f, indent=2)


def send_telegram(text):
    try:
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        requests.post(
            url,
            json={
                'chat_id': CHAT_ID,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
            },
            timeout=10,
        )
    except Exception as e:
        print(f'[collab] telegram error: {e}')


# ── Context gathering ──────────────────────────────────────────────────────

def gather_lens_context():
    bias = load_json(MARKET_BIAS_PATH)
    if not bias:
        return "=== LENS (Market Bias) ===\n[market_bias.json unavailable]"
    pairs_text = '\n'.join(
        f"  {p['symbol']}: {p['bias'].upper()} {p.get('confidence', '?')}% — {p.get('note', '')}"
        for p in bias.get('pairs', [])
    )
    return (
        f"=== LENS (Market Bias) ===\n"
        f"Last updated: {bias.get('last_updated', 'unknown')}\n"
        f"Summary: {bias.get('summary', '')}\n"
        f"Pairs:\n{pairs_text}\n"
        f"Priorities: {bias.get('priorities', '')}"
    )


def gather_oracle_context():
    oracle = load_json(ORACLE_PICKS_PATH)
    if not oracle:
        return "=== ORACLE (Sports Picks) ===\n[oracle_picks.json unavailable]"
    pending = [p for p in oracle.get('picks', []) if p.get('result') == 'pending']
    pending_text = '\n'.join(
        f"  {p['pick']} ({p.get('league','?')}) stake:${p.get('stake',0)} date:{str(p.get('date',''))[:10]}"
        for p in pending[:8]
    ) or '  (none pending)'
    return (
        f"=== ORACLE (Sports Picks) ===\n"
        f"Record: {oracle.get('record', 'N/A')} | Win Rate: {oracle.get('win_rate', 'N/A')}\n"
        f"Balance: ${oracle.get('balance', 0)} (started ${oracle.get('bankroll', 0)})\n"
        f"Total PnL: ${oracle.get('total_pnl', 0)}\n"
        f"Pending picks ({len(pending)}):\n{pending_text}"
    )


def gather_advisor_context():
    log = tail_log(ADVISOR_LOG, 80)
    return f"=== ADVISOR (Latest Analysis) ===\n{log}"


def gather_blade_context():
    log = tail_log(BLADE_LOG, 40)
    return f"=== BLADE (Forex — Recent Activity) ===\n{log}"


def gather_crisp_context():
    log = tail_log(CRISP_LOG, 40)
    return f"=== CRISP (Crypto — Recent Activity) ===\n{log}"


def gather_hub_context():
    hub = load_json(HUB_PATH)
    if not hub:
        return "=== AGENT HUB (Recent Activity) ===\n[unavailable]"
    recent = hub.get('messages', [])[-20:]
    lines = '\n'.join(
        f"  [{m.get('agent','?')}][{m.get('type','?')}] {m.get('message','')[:120]}"
        for m in recent
    )
    return f"=== AGENT HUB (Recent Activity) ===\n{lines}"


def gather_all_context():
    return '\n\n'.join([
        gather_lens_context(),
        gather_oracle_context(),
        gather_advisor_context(),
        gather_blade_context(),
        gather_crisp_context(),
        gather_hub_context(),
    ])


# ── Prompt ─────────────────────────────────────────────────────────────────

def build_prompt(question, context):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return f"""You are the unified intelligence layer for JCF HQ — a multi-agent trading and sports betting platform run by Jase. You synthesise perspectives from all active agents to answer operator questions with data-driven, actionable insight.

Active agents:
- Lens: macro analyst — HTF bias, session structure, forex/crypto market context
- Oracle: sports analyst — generates picks, manages bankroll (7W-5L, 58.3% WR)
- Advisor: CFO — daily performance reviews, risk flags, strategic recommendations
- Blade: forex trading agent — ORB strategy on TradeLocker (SPX500, DE30, XAU/USD, GBP/JPY)
- Crisp: crypto trading agent — ORB/momentum on Phemex (BTC, ETH, SOL, XRP)

QUESTION FROM JASE:
{question}

CURRENT AGENT CONTEXT:
{context}

INSTRUCTIONS:
- Answer Jase's question directly — lead with the answer, not the reasoning
- Draw on each relevant agent's live data to support your response
- Flag any risks, conflicts, or opportunities surfaced by the data
- Give a clear recommendation if the question calls for one
- Keep the response under 400 words — Jase reads this on a dashboard
- Use plain prose, not markdown headers or bullet walls
- End with exactly: "— Agent Collab [{ts}]"

Synthesise now:"""


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: hub_collab.py <question>")
        sys.exit(1)

    question = ' '.join(sys.argv[1:]).strip()
    print(f'[collab] Question: {question}')
    print('[collab] Gathering agent context...')

    context = gather_all_context()
    prompt = build_prompt(question, context)

    print('[collab] Calling Claude...')
    try:
        result = subprocess.run(
            ['claude', '--print', '--model', 'claude-sonnet-4-6'],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )
        response = result.stdout.strip()
        if not response:
            stderr_snippet = result.stderr[:300] if result.stderr else '(none)'
            response = f'[collab] Claude returned no output. stderr: {stderr_snippet}'
    except subprocess.TimeoutExpired:
        response = '[collab] Timed out waiting for Claude response (120s).'
    except FileNotFoundError:
        response = '[collab] claude CLI not found in PATH.'
    except Exception as e:
        response = f'[collab] Unexpected error calling Claude: {e}'

    print(f'[collab] Response: {len(response)} chars')

    # Post full response to hub as type "collab" from advisor
    hub_message = f'Q: {question}\n\n{response}'
    add_hub_message(
        agent='advisor',
        msg_type='collab',
        message=hub_message,
        tags=['collab', 'synthesis'],
    )
    print('[collab] Posted to Agent Hub.')

    # Telegram — truncate to 1000 chars to avoid API limits
    tg_text = (
        f'🤝 <b>Agent Collab</b>\n'
        f'<i>Q: {question}</i>\n\n'
        f'{response[:1000]}{"..." if len(response) > 1000 else ""}'
    )
    send_telegram(tg_text)
    print('[collab] Telegram sent. Done.')


if __name__ == '__main__':
    main()

"""
fanout.py — #ask-the-team individual named-agent fan-out.

Jase asks a question; the relevant agents each answer IN THEIR OWN VOICE, and
the bot posts each reply under that agent's name+avatar (via the interaction
webhook with per-message identity override — see bot.py). This is the
"individual named agents" design Jase chose (not a single synthesized answer).

Pipeline:
  1. Gather live agent context (reuses scripts/hub_collab.py gatherers).
  2. Route the question to the most relevant agents (keyword scoring, capped).
  3. Generate each selected agent's short reply via the Codex gateway.
  4. Drop any agent that opts out ("(nothing to add)").

Returns a list of (agent_id, reply_text) for the bot to deliver.
"""
import os
import sys

sys.path.insert(0, '/root/.openclaw/scripts')
sys.path.insert(0, os.path.dirname(__file__))

from agent_llm import run_agent

# Reuse the existing hub context gatherers where available.
try:
    import hub_collab
    _GATHER = hub_collab.gather_all_context
except Exception:                                   # pragma: no cover
    _GATHER = lambda: '[context unavailable]'

MAX_AGENTS = int(os.getenv('DISCORD_ASK_MAX_AGENTS', '3'))
OPT_OUT = '(nothing to add)'

# agent id -> (domain keywords, persona). ids match discord_notify._DISPLAY.
AGENTS = {
    'lens': (
        ['macro', 'bias', 'forex', 'gold', 'xau', 'btc', 'crypto', 'spx',
         'dxy', 'dollar', 'market', 'trend', 'session', 'oil', 'index',
         'indices', 'us100', 'nasdaq', 'sentiment', 'risk-on', 'risk off'],
        "You are Lens, JCF HQ's macro analyst. You read higher-timeframe bias, "
        "session structure, and cross-asset context (forex, crypto, indices, "
        "gold, oil). Data-driven and concise — lead with the read."),
    'strategist': (
        ['regime', 'environment', 'positioning', 'outlook', 'backdrop',
         'macro regime', 'rotation', 'breadth', 'exposure', 'should we'],
        "You are Jarvis, the calm right-hand-man. You give the regime/positioning "
        "read — composed, three steps ahead, never showy. Brief. Direct. No "
        "filler. Sign off '— Jarvis'."),
    'norman': (
        ['risk', 'size', 'sizing', 'position size', 'drawdown', 'r:r', 'stop',
         'heat', 'blow up', 'ruin', 'validate', 'edge', 'overfit', 'variance'],
        "You are Norman, the risk validator. Cold, calculated, brutally honest "
        "— never cruel. You speak in short declarative lines about risk, sizing, "
        "and whether an edge is real. Sign off '— Norman'."),
    'victoria': (
        ['pnl', 'p&l', 'performance', 'cost', 'budget', 'ops', 'portfolio',
         'net worth', 'account', 'cash', 'finance', 'cfo', 'review', 'spend'],
        "You are Victoria, CFO + Chief of Staff, gothic-queen energy. You own "
        "the operation and never coddle. You speak to money, performance, cost, "
        "and operational reality."),
    'blade': (
        ['blade', 'orb', 'breakout', 'spx500', 'de30', 'chf', 'gbp', 'jpy',
         'london', 'ny_pm', 'asia', 'instrument', 'pair', 'session'],
        "You are Blade, the ORB breakout trading agent. Stoic, military, terse. "
        "You speak only to your setups, instruments, and execution. Facts, no "
        "flourish."),
    'jerry': (
        ['jerry', 'stock', 'stocks', 'option', 'options', 'alpaca', 'equity',
         'equities', 'ticker', 'earnings', 'watchlist'],
        "You are Jerry, the stocks + options paper trader. Professional money "
        "manager voice — measured, specific about tickers and setups."),
    'tao': (
        ['tao', 'bittensor', 'subnet', 'stake', 'staking', 'dca', 'compound'],
        "You are Tao, the Bittensor staking agent. Zen, patient, long-horizon. "
        "You speak to allocation and staking, not short-term trades."),
    'lucy': (
        ['skill', 'tool', 'mcp', 'research', 'new agent', 'build', 'feature',
         'automation', 'integrate'],
        "You are Lucy, the research scout. You surface tools, skills, MCPs, and "
        "build ideas. Curious and practical."),
}

# Sensible default answerers when nothing scores.
DEFAULT_AGENTS = ['strategist', 'lens']


def route(question: str, max_agents: int = MAX_AGENTS) -> list:
    """Score agents by keyword hits; return up to max_agents ids (>=1)."""
    q = question.lower()
    scored = []
    for aid, (kws, _) in AGENTS.items():
        score = sum(1 for k in kws if k in q)
        if score:
            scored.append((score, aid))
    scored.sort(reverse=True)
    picked = [aid for _, aid in scored[:max_agents]]
    if not picked:
        picked = DEFAULT_AGENTS[:max_agents]
    return picked


def _agent_reply(aid: str, question: str, context: str) -> str | None:
    persona = AGENTS[aid][1]
    task = (
        f"Operator (Jase) asked in the team channel:\n\"{question}\"\n\n"
        f"Live system context you may draw on:\n{context}\n\n"
        f"Answer in your own voice, <=90 words, focused only on your domain. "
        f"Lead with your answer. If this question is genuinely outside your "
        f"lane and you'd add nothing, reply with exactly: {OPT_OUT}"
    )
    out = run_agent(persona, task, timeout=120)
    if not out:
        return None
    if OPT_OUT in out.lower():
        return None
    return out.strip()


def answer(question: str, max_agents: int = MAX_AGENTS) -> list:
    """Return [(agent_id, reply_text), ...] from the relevant agents."""
    context = ''
    try:
        context = _GATHER()
    except Exception as e:
        context = f'[context error: {e}]'
    replies = []
    for aid in route(question, max_agents):
        txt = _agent_reply(aid, question, context)
        if txt:
            replies.append((aid, txt))
    return replies


if __name__ == '__main__':
    q = ' '.join(sys.argv[1:]) or "Should we add GBP/JPY back to Blade's instruments?"
    print(f"Q: {q}\nRouted to: {route(q)}\n")
    for aid, txt in answer(q):
        print(f"--- {aid} ---\n{txt}\n")

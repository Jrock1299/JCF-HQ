"""
discord_notify.py — shared Discord webhook poster for JCF HQ agents.

Posts a message to one or more Discord channel webhooks with a per-agent
username + optional avatar. Runs ALONGSIDE Telegram (never replaces it), and
no-ops gracefully when a webhook env var is unset — so it is safe to wire into
an agent before its webhook exists.

Config (all in /root/.openclaw/.env, gitignored):
  DISCORD_WEBHOOK_<CHANNEL>   one per channel, e.g.
     DISCORD_WEBHOOK_LENS, DISCORD_WEBHOOK_VICTORIA, DISCORD_WEBHOOK_STOCK_NEWS,
     DISCORD_WEBHOOK_BLADE_SIGNALS, DISCORD_WEBHOOK_JERRY_PAPER,
     DISCORD_WEBHOOK_ALERTS, DISCORD_WEBHOOK_AGENT_HUB, ...
  DISCORD_AVATAR_BASE (optional)   PUBLIC base URL serving <agent>.png avatars,
     e.g. https://your-host/agents/  — unset => posts with username only.
     (GitHub raw won't work: the JCF-HQ repo is private.)

Usage:
  from discord_notify import notify
  notify('lens', report_text)                 # -> agent's default channel(s)
  notify('blade', text, channels=['BLADE_SIGNALS','ALERTS'])  # explicit
"""
import os
import time

try:
    import requests
except ImportError:                     # pragma: no cover
    requests = None

DISCORD_MAX = 2000                       # Discord message content hard limit

# agent id -> display username shown in Discord (emoji matches Telegram voice)
_DISPLAY = {
    'lens': '🌐 Lens', 'victoria': '🧛‍♀️ Victoria', 'norman': '⚠️ Norman',
    'jarvis': '♟️ Jarvis', 'strategist': '♟️ Jarvis', 'lucy': '🔍 Lucy',
    'tao': '☯️ Tao', 'huncho': '👑 Huncho', 'blade': '🔪 Blade',
    'jerry': '📊 Jerry', 'edge': '📡 Edge',
}
# display-alias -> portrait file stem (hq-app/public/agents/<stem>.png)
_AVATAR_STEM = {'jarvis': 'strategist'}
# agent id -> default channel env-suffix(es) it posts to
_ROUTES = {
    'lens': ['LENS'], 'victoria': ['VICTORIA'], 'norman': ['NORMAN'],
    'jarvis': ['JARVIS'], 'strategist': ['JARVIS'], 'lucy': ['LUCY'],
    'tao': ['TAO'], 'huncho': ['HUNCHO', 'AGENT_HUB'],
    'blade': ['BLADE_SIGNALS'], 'jerry': ['JERRY_PAPER'],
}


def _webhook(channel_suffix: str) -> str:
    return os.getenv(f'DISCORD_WEBHOOK_{channel_suffix.upper()}', '').strip()


def _avatar_url(agent: str):
    base = os.getenv('DISCORD_AVATAR_BASE', '').strip()
    if not base:
        return None
    stem = _AVATAR_STEM.get(agent, agent)
    return base.rstrip('/') + f'/{stem}.png'


def _chunks(text: str, n: int = DISCORD_MAX):
    """Split at newlines under n chars; hard-split any single overlong line."""
    out, cur = [], ''
    for line in (text or '').split('\n'):
        while len(line) > n:
            if cur:
                out.append(cur); cur = ''
            out.append(line[:n]); line = line[n:]
        cand = cur + ('\n' if cur else '') + line
        if len(cand) > n:
            if cur:
                out.append(cur)
            cur = line
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out or ['']


def post_webhook(webhook_url: str, content: str, username=None,
                 avatar_url=None, timeout: int = 15):
    """Post content (chunked to 2000) to one webhook. Returns (sent, total)."""
    if requests is None or not webhook_url:
        return (0, 0)
    parts = _chunks(content)
    sent = 0
    for part in parts:
        payload = {'content': part}
        if username:
            payload['username'] = username
        if avatar_url:
            payload['avatar_url'] = avatar_url
        try:
            r = requests.post(webhook_url, json=payload, timeout=timeout)
            if r.status_code == 429:                      # rate limited -> retry once
                try:
                    retry = float(r.json().get('retry_after', 1))
                except Exception:
                    retry = 1.0
                time.sleep(retry + 0.25)
                r = requests.post(webhook_url, json=payload, timeout=timeout)
            if r.status_code in (200, 204):
                sent += 1
            else:
                print(f'[discord] {r.status_code}: {r.text[:150]}')
        except Exception as e:
            print(f'[discord] post error: {e}')
        time.sleep(0.3)                                    # gentle pacing
    return (sent, len(parts))


def notify(agent: str, content: str, channels=None) -> dict:
    """Post an agent's message to its designated Discord channel(s).

    Best-effort and non-fatal: any channel whose webhook env var is unset is
    silently skipped. `channels` overrides the default route (list of channel
    env-suffixes). Returns {channel: status} for logging.
    """
    agent = (agent or '').lower()
    username = _DISPLAY.get(agent, agent.upper())
    avatar = _avatar_url(agent)
    targets = channels if channels is not None else _ROUTES.get(agent, [agent.upper()])
    results = {}
    for ch in targets:
        wh = _webhook(ch)
        if not wh:
            results[ch] = 'skipped (no webhook)'
            continue
        sent, total = post_webhook(wh, content, username=username, avatar_url=avatar)
        results[ch] = f'{sent}/{total} chunks'
    return results

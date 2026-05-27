#!/usr/bin/env python3
"""
odds_api_keys.py — Dual Odds API key rotation utility.

Maintains two Odds API keys and automatically rotates between them based on
remaining request quota. Keys persist in odds_api_keys.json so all scripts
share a single consistent view of available quota.

Monthly budget (free tier, 500 req/key):
  - Oracle:   5 sports x 1x/day  =  5 req/day  = 150/month
  - Resolver: 5 sports x 2x/day  = 10 req/day  = 300/month
  - /events checks: FREE (0 credits)
  - Total: ~450/month per key → ~900/month combined with 100-req buffer

Usage:
    from odds_api_keys import make_odds_request, check_events, BASE_URL, refresh_quotas
"""

import json
import os
import sys
import requests

KEYS_FILE = '/root/.openclaw/dashboard/odds_api_keys.json'
BASE_URL  = 'https://api.the-odds-api.com/v4'
TIMEOUT   = 15


# ── Environment ───────────────────────────────────────────────────────────────

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


# ── Keys file I/O ─────────────────────────────────────────────────────────────

def load_keys() -> dict:
    with open(KEYS_FILE) as f:
        return json.load(f)


def save_keys(data: dict):
    with open(KEYS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


# ── Key selection ─────────────────────────────────────────────────────────────

def get_active_key() -> str | None:
    """
    Return the key with the most remaining requests that is above its reserve threshold.
    Returns None if both keys are at or below their reserve (effectively exhausted).
    """
    data = load_keys()
    available = sorted(
        [k for k in data['keys'] if k['remaining'] > k['reserve']],
        key=lambda k: k['remaining'],
        reverse=True,
    )
    return available[0]['key'] if available else None


def update_quota(api_key: str, remaining: int):
    """Persist the remaining count for a key after an API response."""
    data = load_keys()
    for k in data['keys']:
        if k['key'] == api_key:
            k['remaining'] = remaining
            break
    save_keys(data)


def quota_status() -> str:
    """Return a human-readable one-line quota summary (for logging)."""
    data = load_keys()
    parts = [f'{k["label"]}: {k["remaining"]} remaining' for k in data['keys']]
    return ' | '.join(parts)


def refresh_quotas():
    """
    Refresh remaining counts for ALL keys using GET /sports/ (costs 0 credits per key).
    Call this at script startup to catch monthly resets automatically.
    """
    data = load_keys()
    changed = False
    for k in data['keys']:
        try:
            r = requests.get(
                f'{BASE_URL}/sports/',
                params={'apiKey': k['key']},
                timeout=10,
            )
            remaining_str = r.headers.get('x-requests-remaining')
            if remaining_str is not None:
                fresh = int(remaining_str)
                if fresh != k['remaining']:
                    print(f'[quota] {k["label"]}: {k["remaining"]} → {fresh} (refreshed)')
                    k['remaining'] = fresh
                    changed = True
                else:
                    print(f'[quota] {k["label"]}: {fresh} remaining')
        except Exception as e:
            print(f'[quota] Could not refresh {k["label"]}: {e}')
    if changed:
        save_keys(data)


# ── Telegram alert ────────────────────────────────────────────────────────────

def _send_telegram_alert(msg: str):
    _load_env()
    token   = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_ALERT_CHAT_ID', '797062420')
    if not token:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': msg},
            timeout=10,
        )
    except Exception:
        pass


# ── Core request function ─────────────────────────────────────────────────────

def make_odds_request(url: str, params: dict | None = None) -> tuple:
    """
    Make an Odds API request using the best available key with automatic rotation.

    - Selects the key with the most remaining requests above its reserve.
    - On 401/429 (quota hit), marks that key as 0 remaining and retries with the other.
    - Updates quota counts from x-requests-remaining response header after every call.
    - Sends a Telegram alert and returns (None, None) if both keys are exhausted.

    Args:
        url:    Full Odds API URL (build with BASE_URL, e.g. f'{BASE_URL}/sports/{sport}/odds/')
        params: Query params WITHOUT apiKey — injected automatically.

    Returns:
        (response_json, api_key_used) — or (None, None) if both keys exhausted.
    """
    if params is None:
        params = {}

    key = get_active_key()
    if key is None:
        msg = '[odds-keys] Both Odds API keys are exhausted. Oracle paused until monthly quota resets.'
        print(msg)
        _send_telegram_alert(msg)
        return None, None

    call_params = {**params, 'apiKey': key}

    try:
        r = requests.get(url, params=call_params, timeout=TIMEOUT)
    except Exception as e:
        print(f'[odds-keys] Request error: {e}')
        return None, None

    # Key exhausted mid-month — mark it 0 and rotate to the other key immediately
    if r.status_code in (401, 429):
        print(f'[odds-keys] Key …{key[-6:]} hit quota limit (HTTP {r.status_code}) — rotating')
        update_quota(key, 0)
        key = get_active_key()
        if key is None:
            msg = '[odds-keys] Both Odds API keys are exhausted. Oracle paused until monthly quota resets.'
            print(msg)
            _send_telegram_alert(msg)
            return None, None
        call_params = {**params, 'apiKey': key}
        try:
            r = requests.get(url, params=call_params, timeout=TIMEOUT)
        except Exception as e:
            print(f'[odds-keys] Retry error after rotation: {e}')
            return None, None

    # Always update quota from the authoritative response header
    remaining_str = r.headers.get('x-requests-remaining')
    if remaining_str is not None:
        try:
            update_quota(key, int(remaining_str))
        except ValueError:
            pass

    if r.status_code == 200:
        return r.json(), key

    print(f'[odds-keys] HTTP {r.status_code}: {r.text[:120]}')
    return None, None


# ── /events optimisation ──────────────────────────────────────────────────────

def check_events(sport: str) -> bool:
    """
    Check if a sport has upcoming events using the /events endpoint (FREE — 0 credits).
    Returns True if events exist → proceed to /odds.
    Returns False if no events → skip /odds call and save 1 credit.
    Falls back to True on any error (conservative: attempt /odds anyway).
    """
    url = f'{BASE_URL}/sports/{sport}/events/'
    data, _ = make_odds_request(url, {'dateFormat': 'iso'})
    if data is None:
        # Can't confirm; assume there might be games rather than skip
        return True
    if len(data) == 0:
        print(f'[odds-keys] {sport}: no upcoming events — skipping /odds call (saved 1 credit)')
        return False
    return True

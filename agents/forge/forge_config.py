"""
forge_config.py — Constants, theme specs, paths, and shared helpers for Forge.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Paths ──────────────────────────────────────────────────────────────────────

FORGE_DIR      = Path('/root/.openclaw/agents/forge')
BUILDS_DIR     = FORGE_DIR / 'builds'
TEMPLATES_DIR  = FORGE_DIR / 'templates'
DATA_DIR       = FORGE_DIR / 'data'
LOG_PATH       = FORGE_DIR / 'forge.log'
BUILD_LOG_PATH = DATA_DIR / 'build_log.json'
SPECS_PATH     = DATA_DIR / 'product_specs.json'
API_COSTS_PATH = Path('/root/.openclaw/logs/forge_api_costs.json')

# ── Models ─────────────────────────────────────────────────────────────────────

BUILD_MODEL    = 'claude-sonnet-4-6'
REVIEW_MODEL   = 'claude-sonnet-4-6'
MAX_TOKENS_BUILD  = 16384
MAX_TOKENS_REVIEW = 2048

# ── Telegram ───────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID', '')
TG_MAX           = 4000

# ── Theme specifications ───────────────────────────────────────────────────────

THEME_SPECS = {
    'dark_techy': {
        'name':         'Dark/Techy',
        'bg':           '#0a0a0f',
        'card_bg':      '#12121a',
        'accent':       '#00d4ff',
        'accent_alt':   '#7c3aed',
        'text':         '#e2e8f0',
        'text_muted':   '#64748b',
        'border':       '#1e293b',
        'font_heading': 'JetBrains Mono, monospace',
        'font_body':    'Inter, sans-serif',
        'style_notes':  'Neon accents, glowing borders, matrix energy, monospace numbers',
    },
    'clean_minimal': {
        'name':         'Clean/Minimal',
        'bg':           '#ffffff',
        'card_bg':      '#f8fafc',
        'accent':       '#3b82f6',
        'accent_alt':   '#10b981',
        'text':         '#1e293b',
        'text_muted':   '#94a3b8',
        'border':       '#e2e8f0',
        'font_heading': 'Inter, sans-serif',
        'font_body':    'Inter, sans-serif',
        'style_notes':  'Lots of whitespace, single accent, no visual noise, clean shadows',
    },
    'earthy_pastel': {
        'name':         'Earthy/Pastel',
        'bg':           '#faf7f2',
        'card_bg':      '#ffffff',
        'accent':       '#c2703e',
        'accent_alt':   '#7c8c5e',
        'text':         '#3d3028',
        'text_muted':   '#8b7d6b',
        'border':       '#e8ddd0',
        'font_heading': 'Playfair Display, serif',
        'font_body':    'Lato, sans-serif',
        'style_notes':  'Warm cream, terracotta, dusty rose, olive, rounded corners, soft shadows',
    },
}

# ── Custom color builder presets ───────────────────────────────────────────────

CUSTOM_PALETTES = {
    'midnight_purple': {'accent': '#8b5cf6', 'bg': '#0f0a1a'},
    'ocean_blue':      {'accent': '#0ea5e9', 'bg': '#0c1929'},
    'forest_green':    {'accent': '#22c55e', 'bg': '#0a1a0f'},
    'rose_gold':       {'accent': '#f472b6', 'bg': '#1a0f14'},
    'monochrome':      {'accent': '#a0a0a0', 'bg': '#111111'},
    'sunset_orange':   {'accent': '#f97316', 'bg': '#1a0f0a'},
    'arctic_ice':      {'accent': '#67e8f9', 'bg': '#0a1419'},
    'royal_gold':      {'accent': '#eab308', 'bg': '#14120a'},
    'neon_pink':       {'accent': '#ec4899', 'bg': '#1a0a14'},
    'sage':            {'accent': '#86efac', 'bg': '#f0fdf4'},
    'lavender':        {'accent': '#a78bfa', 'bg': '#faf5ff'},
    'coral':           {'accent': '#fb7185', 'bg': '#fff1f2'},
}


# ── Logging ────────────────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(LOG_PATH)
        fh.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        ))
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
            datefmt='%H:%M:%S',
        ))
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


# ── Telegram ───────────────────────────────────────────────────────────────────

def _tg_chunk(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': text},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f'[forge] Telegram error: {e}')
        return False


def send_telegram(text: str) -> None:
    if len(text) <= TG_MAX:
        _tg_chunk(text)
        return
    chunks, current = [], ''
    for line in text.split('\n'):
        candidate = current + ('\n' if current else '') + line
        if len(candidate) > TG_MAX:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    for chunk in chunks:
        _tg_chunk(chunk)


# ── API cost tracking ──────────────────────────────────────────────────────────

def save_api_cost(module: str, input_tokens: int, output_tokens: int) -> float:
    cost_usd = round(
        (input_tokens  * 3  / 1_000_000) +
        (output_tokens * 15 / 1_000_000),
        6,
    )
    entry = {
        'date':          datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'module':        module,
        'input_tokens':  input_tokens,
        'output_tokens': output_tokens,
        'cost_usd':      cost_usd,
    }
    try:
        costs = json.loads(API_COSTS_PATH.read_text()) if API_COSTS_PATH.exists() else []
        costs.append(entry)
        API_COSTS_PATH.write_text(json.dumps(costs, indent=2))
    except Exception as e:
        print(f'[forge] cost log error: {e}')
    return cost_usd


# ── JSON helpers ───────────────────────────────────────────────────────────────

def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        print(f'[forge] JSON load error {path}: {e}')
    return default


def save_json(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str))
    except Exception as e:
        print(f'[forge] JSON save error {path}: {e}')


def extract_json(text: str) -> dict | None:
    if not text or not text.strip():
        return None
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    code_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass
    brace_depth, json_start, last_complete = 0, -1, None
    for i, ch in enumerate(text):
        if ch == '{':
            if brace_depth == 0:
                json_start = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and json_start != -1:
                try:
                    last_complete = json.loads(text[json_start:i + 1])
                except json.JSONDecodeError:
                    pass
    return last_complete


# ── Ensure dirs exist ──────────────────────────────────────────────────────────

for _d in (BUILDS_DIR, TEMPLATES_DIR, DATA_DIR, API_COSTS_PATH.parent):
    _d.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

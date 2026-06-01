"""
agent_config.py — Shared config loader for JCF HQ agents.

Reads /root/.openclaw/dashboard/agent_strategies.json. Falls back to the
defaults dict the caller provides if the file or key is missing. Non-breaking
by design — agents keep their hardcoded constants as the fallback.

Usage:
    from agent_config import load_strategy
    cfg = load_strategy('blade', {'RISK_PCT': 0.01, 'SL_BUFFER_POINTS': 3, ...})
    RISK_PCT = cfg['RISK_PCT']
"""

import json
import logging
import os

CONFIG_PATH = '/root/.openclaw/dashboard/agent_strategies.json'


def load_strategy(agent_name: str, defaults: dict) -> dict:
    """Return a dict with the agent's config — central file overrides, defaults fill gaps."""
    cfg = dict(defaults)
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            override = data.get(agent_name, {}) or {}
            for k, v in override.items():
                if k.startswith('_'):
                    continue
                cfg[k] = v
    except Exception as e:
        logging.warning(f"agent_config: could not load {CONFIG_PATH}: {e}")
    return cfg

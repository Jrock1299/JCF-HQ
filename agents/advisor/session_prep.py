#!/usr/bin/env python3
"""
Session Prep Agent — fires 7 minutes before each trading session open.
Sends Jase a Telegram briefing with ORB candle, ADR, Lens bias, news risk, and grade.

Usage: python3 session_prep.py [LONDON|NY|NY_PM]
"""

import sys
import json
import os
import requests
import logging
from datetime import datetime, timezone, timedelta
from statistics import mean

# ─── oandapyV20 ────────────────────────────────────────────────────────────────
try:
    from oandapyV20 import API
    from oandapyV20.endpoints.instruments import InstrumentsCandles
except ImportError:
    print("ERROR: oandapyV20 not installed. Run: pip3 install oandapyV20")
    sys.exit(1)

# ─── Config ────────────────────────────────────────────────────────────────────
AUTH_FILE        = '/root/.openclaw/agents/main/agent/auth-profiles.json'
MARKET_BIAS_PATH = '/root/.openclaw/dashboard/market_bias.json'
BOT_TOKEN        = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID          = '797062420'
LOG_FILE         = '/root/.openclaw/agents/advisor/session_prep.log'

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# ─── Session → instruments ─────────────────────────────────────────────────────
SESSION_INSTRUMENTS = {
    'LONDON': ['DE30_EUR', 'XAU_USD', 'SPX500_USD'],
    'NY':     ['SPX500_USD', 'XAU_USD', 'BTC_USD'],
    'NY_PM':  ['SPX500_USD'],
}

# Display labels
DISPLAY_NAMES = {
    'DE30_EUR':   'GER40',
    'XAU_USD':    'XAU/USD',
    'SPX500_USD': 'SPX500',
    'BTC_USD':    'BTC/USD',
}

# News currency relevance (ForexFactory `country` field)
NEWS_CURRENCIES = {
    'SPX500_USD': ['USD'],
    'DE30_EUR':   ['EUR', 'USD'],
    'XAU_USD':    ['USD'],
    'BTC_USD':    [],   # crypto — no forex calendar relevance
}

# Lens bias symbol aliases (maps to market_bias.json pair symbols)
LENS_KEYS = {
    'SPX500_USD': ['SPX500', 'US100', 'SPX500_USD', 'NAS100'],
    'DE30_EUR':   ['DE30', 'GER40', 'DE30_EUR', 'DAX'],
    'XAU_USD':    ['XAU/USD', 'XAU_USD', 'GOLD', 'XAUUSD'],
    'BTC_USD':    ['BTC/USD', 'BTC/USDT', 'BTC_USD', 'BTCUSD', 'BTC'],
}


# ─── OANDA ─────────────────────────────────────────────────────────────────────
def get_oanda_client():
    with open(AUTH_FILE) as f:
        auth = json.load(f)
    creds = auth['profiles']['oanda:default']
    return API(access_token=creds['key'], environment='practice')


def get_candles(client, instrument, granularity, count):
    try:
        r = InstrumentsCandles(instrument, params={
            'granularity': granularity,
            'count': count,
            'price': 'M'
        })
        client.request(r)
        return r.response['candles']
    except Exception as e:
        logging.error(f"get_candles({instrument},{granularity},{count}): {e}")
        return []


def get_last_15m_candle(client, instrument):
    """Returns the last completed 15m candle — this IS the ORB candle at session open."""
    candles = get_candles(client, instrument, 'M15', 4)
    completed = [c for c in candles if c.get('complete', False)]
    if not completed:
        # Fallback: take the most recent candle regardless
        completed = candles
    c = completed[-1]
    return {
        'open':  float(c['mid']['o']),
        'high':  float(c['mid']['h']),
        'low':   float(c['mid']['l']),
        'close': float(c['mid']['c']),
        'time':  c.get('time', ''),
    }


def get_10day_adr(client, instrument):
    """10-day Average Daily Range."""
    candles = get_candles(client, instrument, 'D', 13)
    completed = [c for c in candles if c.get('complete', False)]
    if len(completed) < 5:
        return None
    last10 = completed[-10:]
    ranges = [float(c['mid']['h']) - float(c['mid']['l']) for c in last10]
    return mean(ranges)


# ─── Lens bias ─────────────────────────────────────────────────────────────────
def get_lens_bias(instrument):
    """Returns (bias, confidence) from market_bias.json. Handles both formats."""
    keys = LENS_KEYS.get(instrument, [instrument])
    try:
        with open(MARKET_BIAS_PATH) as f:
            data = json.load(f)
    except Exception as e:
        logging.warning(f"market_bias.json read error: {e}")
        return 'neutral', 50

    # Dict format: {"XAU/USD": {"bias": ..., "confidence": ...}}
    for key in keys:
        entry = data.get(key)
        if entry and isinstance(entry, dict) and 'bias' in entry:
            conf = float(entry.get('confidence', 50))
            if conf <= 1.0:
                conf *= 100
            return entry['bias'].lower(), conf

    # Array format: {"pairs": [{"symbol": "XAU/USD", "bias": ..., "confidence": ...}]}
    for pair in data.get('pairs', []):
        sym = pair.get('symbol', '')
        if any(k.upper() in sym.upper() or sym.upper() in k.upper() for k in keys):
            conf = float(pair.get('confidence', 50))
            if conf <= 1.0:
                conf *= 100
            return pair.get('bias', 'neutral').lower(), conf

    return 'neutral', 50


# ─── News ──────────────────────────────────────────────────────────────────────
def get_news_events(instrument, hours_ahead=2):
    """
    Fetches high/medium-impact news for the next N hours from ForexFactory.
    Returns list of dicts: {title, time_utc, impact, country}
    """
    currencies = NEWS_CURRENCIES.get(instrument, [])
    if not currencies:
        return []

    try:
        url = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        events = r.json()
    except Exception as e:
        logging.warning(f"News fetch error: {e}")
        return []

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours_ahead)
    hits = []

    for evt in events:
        if evt.get('impact') not in ('High', 'Medium'):
            continue
        if evt.get('country') not in currencies:
            continue

        date_str = evt.get('date', '')
        if not date_str:
            continue

        try:
            # Date is ISO 8601 with offset: "2026-03-20T14:00:00-04:00"
            from datetime import datetime as dt
            # Python 3.7+ fromisoformat handles ±HH:MM offsets
            event_time = dt.fromisoformat(date_str).astimezone(timezone.utc)
        except Exception:
            continue

        if now <= event_time <= cutoff:
            hits.append({
                'title':    evt.get('title', 'Unknown'),
                'time_utc': event_time.strftime('%H:%M UTC'),
                'impact':   evt.get('impact', 'High'),
                'country':  evt.get('country', ''),
            })

    # Sort by time, cap at 3
    hits.sort(key=lambda x: x['time_utc'])
    return hits[:3]


# ─── Grade ─────────────────────────────────────────────────────────────────────
def calculate_grade(adr, bias, confidence, news_events):
    """
    A = TRADE    — strong aligned bias, no news
    B = CAUTION  — mixed signals or medium news
    C = SKIP     — high news risk or weak/neutral bias
    Note: ORB range excluded — can only be calculated after the first 15m candle closes.
    """
    has_high_news = any(e['impact'] == 'High' for e in news_events)
    has_med_news  = any(e['impact'] == 'Medium' for e in news_events)

    bias_strong = bias in ('bullish', 'bearish') and confidence >= 60
    bias_ok     = bias in ('bullish', 'bearish') and confidence >= 45

    if has_high_news:
        return 'C', 'SKIP (news risk)'
    if bias_strong:
        if has_med_news:
            return 'B', 'CAUTION (med news)'
        return 'A', 'TRADE'
    if bias_ok:
        return 'B', 'CAUTION'
    return 'C', 'SKIP'


# ─── Formatting helpers ─────────────────────────────────────────────────────────
def fmt_price(instrument, price):
    if instrument == 'BTC_USD':
        return f'{price:,.0f}'
    if instrument in ('DE30_EUR', 'SPX500_USD'):
        return f'{price:.1f}'
    return f'{price:.2f}'


def fmt_pts(instrument, val):
    if instrument == 'BTC_USD':
        return f'{val:,.0f}'
    if instrument in ('DE30_EUR', 'SPX500_USD'):
        return f'{val:.1f}'
    return f'{val:.1f}'


def bias_emoji(bias, confidence):
    if bias == 'bullish':
        return '🟢' if confidence >= 65 else '🟡'
    if bias == 'bearish':
        return '🔴' if confidence >= 65 else '🟡'
    return '⚪'


def grade_emoji(grade):
    return {'A': '🟢', 'B': '🟡', 'C': '🔴'}.get(grade, '⚪')


def adr_tag(instrument, adr):
    """Flags abnormally high ADR (>1.5× typical) or low ADR (<0.5× typical)."""
    # Typical daily ranges per instrument (approximate)
    TYPICAL = {'SPX500_USD': 50, 'DE30_EUR': 250, 'XAU_USD': 30, 'BTC_USD': 2000}
    typical = TYPICAL.get(instrument, 0)
    if not adr or adr == 0 or typical == 0:
        return ''
    ratio = adr / typical
    if ratio > 1.5:
        return '⚠️ Abnormal'
    if ratio < 0.5:
        return '⚠️ Compressed'
    return ''


# ─── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    try:
        r = requests.post(url, data={
            'chat_id':    CHAT_ID,
            'text':       text,
            'parse_mode': 'Markdown',
        }, timeout=10)
        result = r.json()
        if not result.get('ok'):
            logging.error(f"Telegram error: {result}")
        return result
    except Exception as e:
        logging.error(f"Telegram send failed: {e}")
        return {}


# ─── Build message ─────────────────────────────────────────────────────────────
def build_prep_message(session):
    instruments = SESSION_INSTRUMENTS[session]
    client = get_oanda_client()

    now = datetime.now(timezone.utc)
    date_str = now.strftime('%b %d, %H:%M UTC')

    session_labels = {
        'LONDON': 'LONDON SESSION PREP',
        'NY':     'NY SESSION PREP',
        'NY_PM':  'NY PM SESSION PREP',
    }

    lines = [f'📊 *{session_labels[session]} | {date_str}*', '']

    for instrument in instruments:
        display = DISPLAY_NAMES.get(instrument, instrument)
        lines.append(f'*{display}:*')

        # 10-day ADR
        adr = None
        try:
            adr = get_10day_adr(client, instrument)
            if adr:
                tag = adr_tag(instrument, adr)
                tag_str = f' {tag}' if tag else ''
                lines.append(f'  ADR (10d): `{fmt_pts(instrument, adr)}pts`{tag_str}')
            else:
                lines.append('  ADR (10d): N/A')
        except Exception as e:
            logging.error(f"ADR fetch failed for {instrument}: {e}")
            lines.append('  ADR (10d): N/A')

        # Lens bias
        bias, confidence = get_lens_bias(instrument)
        b_emoji = bias_emoji(bias, confidence)
        lines.append(f'  Lens: {bias.capitalize()} {confidence:.0f}% {b_emoji}')

        # News
        news = get_news_events(instrument)
        if news:
            for evt in news:
                impact_tag = '🚨' if evt['impact'] == 'High' else '⚠️'
                lines.append(f'  News: {evt["title"]} {evt["time_utc"]} {impact_tag}')
        else:
            lines.append('  News: None next 2hrs')

        # Grade
        grade, verdict = calculate_grade(adr, bias, confidence, news)
        lines.append(f'  Grade: *{grade}* — {verdict} {grade_emoji(grade)}')

        lines.append('')  # blank line between instruments

    return '\n'.join(lines).rstrip()


# ─── Entry point ───────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: session_prep.py [LONDON|NY|NY_PM]")
        sys.exit(1)

    session = sys.argv[1].upper().replace('-', '_')
    if session not in SESSION_INSTRUMENTS:
        print(f"Unknown session '{session}'. Must be: LONDON, NY, NY_PM")
        sys.exit(1)

    logging.info(f"=== Session prep starting: {session} ===")

    try:
        msg = build_prep_message(session)
    except Exception as e:
        logging.error(f"Build failed: {e}", exc_info=True)
        send_telegram(f'⚠️ Session prep error ({session}): {e}')
        sys.exit(1)

    logging.info(f"Sending {session} prep to Telegram")
    result = send_telegram(msg)

    if result.get('ok'):
        logging.info("Sent successfully.")
        print("Sent.")
    else:
        logging.error(f"Send failed: {result}")
        print(f"Send failed: {result}")
        sys.exit(1)


if __name__ == '__main__':
    main()

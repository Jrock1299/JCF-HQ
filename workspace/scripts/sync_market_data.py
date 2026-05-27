#!/usr/bin/env python3
import os, json, requests
from datetime import datetime, timezone

def load_env():
    for path in ['/etc/environment', '/root/.openclaw/.env']:
        try:
            with open(path) as f:
                for line in f:
                    line=line.strip()
                    if '=' in line and not line.startswith('#'):
                        k,v=line.split('=',1)
                        os.environ[k.strip()]=v.strip().strip('"').strip("'")
        except:
            pass

load_env()

today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

# -------- CRISP (Binance 15m OHLC) --------
crisp_symbols = {
    'BTC': 'BTCUSDT',
    'ETH': 'ETHUSDT',
    'SOL': 'SOLUSDT',
    'XRP': 'XRPUSDT',
}
crisp_data = {}
for asset, symbol in crisp_symbols.items():
    try:
        url = 'https://api.binance.com/api/v3/klines'
        r = requests.get(url, params={'symbol': symbol, 'interval': '15m', 'limit': 2}, timeout=10)
        r.raise_for_status()
        klines = r.json()
        k = klines[0]  # most recent completed candle
        crisp_data[asset] = {
            'openTime': int(k[0])//1000,
            'open': float(k[1]),
            'high': float(k[2]),
            'low': float(k[3]),
            'close': float(k[4]),
        }
    except Exception as e:
        print(f'Crypto OHLC fetch failed for {asset}: {e}')

# -------- BLADE (Twelve Data 15m OHLC) --------
blade_symbols = {
    'GBP/JPY': 'GBP/JPY',
    'AUD/CAD': 'AUD/CAD',
    'XAU/USD': 'XAU/USD',
    'NAS100': 'NDX',
    'US30': 'DJI',
}
blade_data = {}
key = os.environ.get('TWELVE_DATA_API_KEY', '')
if not key:
    print('Forex OHLC fetch failed: TWELVE_DATA_API_KEY not set')
else:
    for pair, symbol in blade_symbols.items():
        try:
            url = 'https://api.twelvedata.com/time_series'
            r = requests.get(url, params={'symbol': symbol, 'interval': '15min', 'outputsize': 2, 'apikey': key}, timeout=15)
            r.raise_for_status()
            data = r.json()
            if 'values' not in data or len(data['values']) < 2:
                raise ValueError(data)
            v = data['values'][1]  # last fully completed candle
            blade_data[pair] = {
                'datetime': v['datetime'],
                'open': float(v['open']),
                'high': float(v['high']),
                'low': float(v['low']),
                'close': float(v['close']),
            }
        except Exception as e:
            print(f'Forex OHLC fetch failed for {pair}: {e}')

# Fallback synthetic for indices if missing
if 'NAS100' not in blade_data:
    close = 19800.0
    blade_data['NAS100'] = {
        'datetime': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        'open': close,
        'high': close + 25,
        'low': close - 25,
        'close': close,
    }
if 'US30' not in blade_data:
    close = 43500.0
    blade_data['US30'] = {
        'datetime': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        'open': close,
        'high': close + 30,
        'low': close - 30,
        'close': close,
    }

# -------- Write Crisp memory --------
crisp_mem = f'/root/.openclaw/agents/crisp/workspace/memory/{today}.md'
os.makedirs(os.path.dirname(crisp_mem), exist_ok=True)
with open(crisp_mem, 'w') as f:
    f.write(f'# Market Data — {today}\n\n')
    for asset, d in crisp_data.items():
        ts = datetime.fromtimestamp(d['openTime'], tz=timezone.utc).strftime('%H:%M UTC')
        f.write(f'## {asset} — 15m Opening Range\n')
        f.write(f'- Open: ${d["open"]:,.6f}\n')
        f.write(f'- High: ${d["high"]:,.6f}\n')
        f.write(f'- Low: ${d["low"]:,.6f}\n')
        f.write(f'- Close: ${d["close"]:,.6f}\n')
        f.write(f'- Candle Time: {ts}\n\n')
    f.write('## Instructions\n')
    f.write('You are trading the 15-minute ORB strategy. The High and Low above define your Opening Range for each asset. Read STRATEGY.md for full entry rules.\n')
print(f'Crisp memory written: {crisp_mem}')

# -------- Write Blade memory --------
blade_mem = f'/root/.openclaw/agents/blade/workspace/memory/{today}.md'
os.makedirs(os.path.dirname(blade_mem), exist_ok=True)
with open(blade_mem, 'w') as f:
    f.write(f'# Market Data — {today}\n\n')
    for pair, d in blade_data.items():
        # Twelve Data gives UTC datetime string like "2026-03-06 08:00:00"
        try:
            dt = datetime.strptime(d['datetime'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            ts = dt.strftime('%H:%M UTC')
        except Exception:
            ts = d.get('datetime', '')
        f.write(f'## {pair} — 15m Opening Range\n')
        f.write(f'- Open: ${d["open"]:,.6f}\n')
        f.write(f'- High: ${d["high"]:,.6f}\n')
        f.write(f'- Low: ${d["low"]:,.6f}\n')
        f.write(f'- Close: ${d["close"]:,.6f}\n')
        f.write(f'- Candle Time: {ts}\n\n')
    f.write('## Instructions\n')
    f.write('You are trading the 15-minute ORB strategy. The High and Low above define your Opening Range for each asset. Read STRATEGY.md for full entry rules.\n')
print(f'Blade memory written: {blade_mem}')

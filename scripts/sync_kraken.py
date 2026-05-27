#!/usr/bin/env python3
"""
sync_kraken.py — Fetch Kraken balances and current USD prices,
write to /root/.openclaw/dashboard/kraken_data.json
"""
import os, sys, json, time, hashlib, hmac, base64, urllib.parse, datetime, logging, requests

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_PATH = '/root/.openclaw/logs/kraken_sync.log'
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH),
    ]
)
log = logging.getLogger('kraken_sync')

# ── Load credentials ─────────────────────────────────────────────────────────
def load_env(path='/root/.openclaw/.env'):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())

load_env()

API_KEY    = os.getenv('KRAKEN_API_KEY', '').strip()
API_SECRET = os.getenv('KRAKEN_API_SECRET', '').strip()

if not API_KEY or API_KEY == 'PASTE_YOUR_KEY_HERE':
    log.error('KRAKEN_API_KEY not set in /root/.openclaw/.env')
    sys.exit(1)
if not API_SECRET or API_SECRET == 'PASTE_YOUR_SECRET_HERE':
    log.error('KRAKEN_API_SECRET not set in /root/.openclaw/.env')
    sys.exit(1)

API_BASE = 'https://api.kraken.com'
OUT_PATH = '/root/.openclaw/dashboard/kraken_data.json'
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

# ── Kraken asset name → canonical ticker mapping ─────────────────────────────
ASSET_MAP = {
    'XXBT':  'BTC',
    'XBT':   'BTC',
    'XETH':  'ETH',
    'ETH':   'ETH',
    'XXRP':  'XRP',
    'XRP':   'XRP',
    'XLTC':  'LTC',
    'LTC':   'LTC',
    'XXLM':  'XLM',
    'XLM':   'XLM',
    'XDOGE': 'DOGE',
    'DOGE':  'DOGE',
    'ADA':   'ADA',
    'SOL':   'SOL',
    'DOT':   'DOT',
    'MATIC':  'MATIC',
    'LINK':  'LINK',
    'AVAX':  'AVAX',
    'ATOM':  'ATOM',
    'UNI':   'UNI',
    'ALGO':  'ALGO',
    'MANA':  'MANA',
    'SAND':  'SAND',
    'FIL':   'FIL',
    'EOS':   'EOS',
    'AAVE':  'AAVE',
    'GRT':   'GRT',
    'CHZ':   'CHZ',
    'ENJ':   'ENJ',
    'NEAR':  'NEAR',
    'FTM':   'FTM',
    'SUI':   'SUI',
    'TRX':   'TRX',
    'TON':   'TON',
    'ARB':   'ARB',
    'OP':    'OP',
    'APT':   'APT',
    'IMX':   'IMX',
    'ICP':   'ICP',
    'BCH':   'BCH',
    'XBCH':  'BCH',
    # stable / fiat
    'ZUSD':  'USD',
    'USD':   'USD',
    'USDT':  'USDT',
    'USDC':  'USDC',
    'ZEUR':  'EUR',
    'EUR':   'EUR',
    'ZGBP':  'GBP',
    'GBP':   'GBP',
    'ZCAD':  'CAD',
    'CAD':   'CAD',
}

USD_STABLE = {'USD', 'USDT', 'USDC', 'ZUSD', 'DAI', 'BUSD', 'LUSD', 'USDP', 'USDD'}

# Kraken uses its own pair names — these are the ticker pairs we try for price lookup
# Priority: {ASSET}USD, then X{ASSET}ZUSD, etc.
def kraken_price_pairs(kraken_ticker):
    """Return a list of pair names to try for a USD price."""
    canon = ASSET_MAP.get(kraken_ticker, kraken_ticker)
    return [
        f'{kraken_ticker}USD',
        f'{kraken_ticker}ZUSD',
        f'X{kraken_ticker}ZUSD',
        f'X{kraken_ticker}USD',
        f'{canon}USD',
        f'{canon}ZUSD',
    ]

# ── HMAC-SHA512 auth ──────────────────────────────────────────────────────────
def kraken_sign(uri_path: str, post_data: str, nonce: str) -> str:
    """
    API-Sign = base64(HMAC-SHA512(uri_path + SHA256(nonce + post_data), base64decode(secret)))
    """
    secret_bytes = base64.b64decode(API_SECRET)
    encoded = (nonce + post_data).encode('utf-8')
    sha256_digest = hashlib.sha256(encoded).digest()
    message = uri_path.encode('utf-8') + sha256_digest
    mac = hmac.new(secret_bytes, message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()

def private_post(endpoint: str, params: dict | None = None) -> dict:
    params = params or {}
    nonce = str(int(time.time() * 1000))
    params['nonce'] = nonce
    post_data = urllib.parse.urlencode(params)
    uri_path = f'/0/private/{endpoint}'
    headers = {
        'API-Key':  API_KEY,
        'API-Sign': kraken_sign(uri_path, post_data, nonce),
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    resp = requests.post(f'{API_BASE}{uri_path}', headers=headers, data=post_data, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get('error'):
        raise RuntimeError(f'Kraken API error: {data["error"]}')
    return data.get('result', {})

def public_get(endpoint: str, params: dict | None = None) -> dict:
    resp = requests.get(f'{API_BASE}/0/public/{endpoint}', params=params or {}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get('error'):
        raise RuntimeError(f'Kraken public API error: {data["error"]}')
    return data.get('result', {})

# ── Price fetching ────────────────────────────────────────────────────────────
_price_cache: dict[str, float] = {}

def get_usd_price(kraken_ticker: str) -> float:
    """Fetch current USD price for a Kraken asset ticker. Returns 1.0 for stables."""
    canon = ASSET_MAP.get(kraken_ticker, kraken_ticker)

    if canon in USD_STABLE:
        return 1.0
    # Euro / other fiat: skip for now, return 0 so it shows up but with $0 value
    if canon in ('EUR', 'GBP', 'CAD', 'JPY'):
        return 0.0

    if kraken_ticker in _price_cache:
        return _price_cache[kraken_ticker]

    pairs_to_try = kraken_price_pairs(kraken_ticker)
    for pair in pairs_to_try:
        try:
            result = public_get('Ticker', {'pair': pair})
            if result:
                # result is dict keyed by exchange's internal pair name
                first_val = next(iter(result.values()))
                # 'c' = last trade closed: [price, lot_volume]
                price = float(first_val['c'][0])
                _price_cache[kraken_ticker] = price
                return price
        except Exception:
            continue

    log.warning(f'Could not fetch USD price for {kraken_ticker} (tried {pairs_to_try})')
    return 0.0

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info('=== Kraken sync started ===')

    # 1. Fetch balances
    try:
        raw_balances = private_post('Balance')
    except Exception as e:
        log.error(f'Failed to fetch balances: {e}')
        sys.exit(1)

    # Filter to non-zero
    nonzero = {k: float(v) for k, v in raw_balances.items() if float(v) > 1e-8}
    log.info(f'Non-zero assets found: {len(nonzero)} — {list(nonzero.keys())}')

    if not nonzero:
        log.warning('No non-zero balances returned — wallet may be empty')

    # 2. Build holdings
    holdings = []
    total_usd = 0.0

    for kraken_ticker, balance in sorted(nonzero.items(), key=lambda x: -x[1]):
        canon = ASSET_MAP.get(kraken_ticker, kraken_ticker)
        price = get_usd_price(kraken_ticker)
        value = round(balance * price, 2)
        total_usd += value

        entry = {
            'asset':         canon,
            'kraken_ticker': kraken_ticker,
            'balance':       round(balance, 8),
            'price_usd':     round(price, 4),
            'value_usd':     value,
        }
        holdings.append(entry)
        log.info(f'  {canon:8s} ({kraken_ticker:8s})  bal={balance:.6f}  price=${price:,.2f}  value=${value:,.2f}')

    # Sort by value descending
    holdings.sort(key=lambda x: -x['value_usd'])
    total_usd = round(total_usd, 2)

    log.info(f'Total portfolio value: ${total_usd:,.2f}')

    # 3. Write JSON
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    out = {
        'last_updated': now,
        'total_usd':    total_usd,
        'holdings':     holdings,
    }
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, indent=2)

    log.info(f'Written to {OUT_PATH}')
    log.info(f'=== Kraken sync complete: {len(holdings)} assets, ${total_usd:,.2f} total ===')

    # Print summary to stdout
    print(f'\n{"─"*50}')
    print(f'  KRAKEN PORTFOLIO SUMMARY')
    print(f'{"─"*50}')
    print(f'  Assets found : {len(holdings)}')
    for h in holdings:
        print(f'  {h["asset"]:6s}  bal={h["balance"]:.6f}  @ ${h["price_usd"]:>10,.2f}  = ${h["value_usd"]:>10,.2f}')
    print(f'{"─"*50}')
    print(f'  TOTAL        : ${total_usd:,.2f}')
    print(f'{"─"*50}\n')
    print(f'  JSON written to: {OUT_PATH}')

if __name__ == '__main__':
    main()

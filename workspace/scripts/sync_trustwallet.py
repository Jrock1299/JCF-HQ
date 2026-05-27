#!/usr/bin/env python3
import os, json, datetime, sys, requests
def load_env():
    try:
        with open('/etc/environment') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass

load_env()

OUT_PATH = "/root/.openclaw/dashboard/trustwallet_data.json"

WALLET_ETH = os.getenv("WALLET_ETH")
WALLET_XRP = os.getenv("WALLET_XRP")
WALLET_SOL = os.getenv("WALLET_SOL")
WALLET_ADA = os.getenv("WALLET_ADA")
WALLET_SUI = os.getenv("WALLET_SUI")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
BLOCKFROST_API_KEY = os.getenv("BLOCKFROST_API_KEY")

missing = [k for k,v in {
    'WALLET_ETH':WALLET_ETH,
    'WALLET_XRP':WALLET_XRP,
    'WALLET_SOL':WALLET_SOL,
    'WALLET_ADA':WALLET_ADA,
    'WALLET_SUI':WALLET_SUI,
    'ETHERSCAN_API_KEY':ETHERSCAN_API_KEY,
    'BLOCKFROST_API_KEY':BLOCKFROST_API_KEY
}.items() if not v]
if missing:
    print("Missing env vars: "+", ".join(missing), file=sys.stderr)
    sys.exit(1)

now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()

def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {}

# prices
price_url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum,ripple,solana,cardano,sui,chainlink&vs_currencies=usd"
prices = safe_json(requests.get(price_url, timeout=20))

def get_price(key):
    return float(prices.get(key,{}).get('usd',0) or 0)

# ETH balance (Etherscan v2)
eth_url = f"https://api.etherscan.io/v2/api?chainid=1&module=account&action=balance&address={WALLET_ETH}&tag=latest&apikey={ETHERSCAN_API_KEY}"
eth_resp = safe_json(requests.get(eth_url, timeout=20))
eth_result = eth_resp.get('result',0)
eth_balance = int(eth_result) / 1e18 if str(eth_result).isdigit() else 0.0

# LINK balance (ERC-20, Etherscan v2)
link_url = f"https://api.etherscan.io/v2/api?chainid=1&module=account&action=tokenbalance&contractaddress=0x514910771AF9Ca656af840dff83E8264EcF986CA&address={WALLET_ETH}&tag=latest&apikey={ETHERSCAN_API_KEY}"
link_resp = safe_json(requests.get(link_url, timeout=20))
link_result = link_resp.get('result',0)
link_balance = int(link_result) / 1e18 if str(link_result).isdigit() else 0.0

# XRP balance (xrpscan)
xrp_url = f"https://api.xrpscan.com/api/v1/account/{WALLET_XRP}"
xrp_resp = safe_json(requests.get(xrp_url, timeout=20))
xrp_balance = float(xrp_resp.get('xrpBalance',0) or 0)

# SOL balance
sol_payload = {"jsonrpc":"2.0","id":1,"method":"getBalance","params":[WALLET_SOL]}
sol_resp = safe_json(requests.post("https://api.mainnet-beta.solana.com", json=sol_payload, timeout=20))
sol_balance = int(sol_resp.get('result',{}).get('value',0) or 0) / 1e9

# ADA balance
ada_url = f"https://cardano-mainnet.blockfrost.io/api/v0/addresses/{WALLET_ADA}"
ada_resp = safe_json(requests.get(ada_url, headers={"project_id": BLOCKFROST_API_KEY}, timeout=20))
ada_amounts = ada_resp.get('amount',[])
ada_balance = 0.0
for a in ada_amounts:
    if a.get('unit') == 'lovelace':
        ada_balance = int(a.get('quantity',0)) / 1e6
        break

# SUI balance
sui_payload = {"jsonrpc":"2.0","id":1,"method":"suix_getBalance","params":[WALLET_SUI]}
sui_resp = safe_json(requests.post("https://fullnode.mainnet.sui.io", json=sui_payload, timeout=20))
sui_balance = int(sui_resp.get('result',{}).get('totalBalance',0) or 0) / 1e9

holdings = {
    "ETH": {"balance": eth_balance, "usd_price": get_price('ethereum')},
    "XRP": {"balance": xrp_balance, "usd_price": get_price('ripple')},
    "SOL": {"balance": sol_balance, "usd_price": get_price('solana')},
    "ADA": {"balance": ada_balance, "usd_price": get_price('cardano')},
    "SUI": {"balance": sui_balance, "usd_price": get_price('sui')},
    "LINK": {"balance": link_balance, "usd_price": get_price('chainlink')}
}

for k,v in holdings.items():
    v['usd_value'] = round(v['balance'] * v['usd_price'], 2)

total_usd = round(sum(v['usd_value'] for v in holdings.values()), 2)

out = {
    "total_usd": total_usd,
    "last_update": now,
    "holdings": holdings
}

with open(OUT_PATH, 'w') as f:
    json.dump(out, f, indent=2)

print(f"Saved {OUT_PATH}")

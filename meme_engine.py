import aiohttp
import asyncio
import pandas as pd
import os
from datetime import datetime
import uvloop
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.rpc.responses import LogsNotification
from solders.rpc.requests import LogsSubscribe
from anchorpy import Idl, Program
import base58
import logging
import requests

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# --- CONFIG ---
RPC_URL = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")  # Use paid RPC for speed
PUMP_FUN_PROGRAM = Pubkey.from_string("6ef8rrecthR5Dkzon8NwtDc6jUJuBZF6FVPm6146r62")
MIN_LIQUIDITY = 10  # SOL
MIN_FOLLOWERS = 1000  # For Twitter check
BUY_AMOUNT = 0.05  # SOL per snipe (paper)
SLIPPAGE = 0.05  # 5%
DATA_FILE = "/app/data/meme_training_data.csv"
METAPLEX_PROGRAM = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3yFxrGvJ9o9Mhno")

logger = logging.getLogger(__name__)

async def get_idl():
    idl_json = {
  "version": "0.1.0",
  "name": "pump",
  "instructions": [
    {
      "name": "initialize",
      "docs": ["Creates the global state."],
      "accounts": [
        { "name": "global", "isMut": true, "isSigner": false },
        { "name": "user", "isMut": true, "isSigner": true },
        { "name": "systemProgram", "isMut": false, "isSigner": false }
      ],
      "args": []
    },
    {
      "name": "setParams",
      "docs": ["Sets the global state parameters."],
      "accounts": [
        { "name": "global", "isMut": true, "isSigner": false },
        { "name": "user", "isMut": true, "isSigner": true },
        { "name": "systemProgram", "isMut": false, "isSigner": false },
        { "name": "eventAuthority", "isMut": false, "isSigner": false },
        { "name": "program", "isMut": false, "isSigner": false }
      ],
      "args": [
        { "name": "feeRecipient", "type": "publicKey" },
        { "name": "initialVirtualTokenReserves", "type": "u64" },
        { "name": "initialVirtualSolReserves", "type": "u64" },
        { "name": "initialRealTokenReserves", "type": "u64" },
        { "name": "tokenTotalSupply", "type": "u64" },
        { "name": "feeBasisPoints", "type": "u64" }
      ]
    },
    {
      "name": "create",
      "docs": ["Creates a new coin and bonding curve."],
      "accounts": [
        { "name": "mint", "isMut": true, "isSigner": true },
        { "name": "mintAuthority", "isMut": false, "isSigner": false },
        { "name": "bondingCurve", "isMut": true, "isSigner": false },
        { "name": "associatedBondingCurve", "isMut": true, "isSigner": false },
        { "name": "global", "isMut": false, "isSigner": false },
        { "name": "mplTokenMetadata", "isMut": false, "isSigner": false },
        { "name": "metadata", "isMut": true, "isSigner": false },
        { "name": "user", "isMut": true, "isSigner": true },
        { "name": "systemProgram", "isMut": false, "isSigner": false },
        { "name": "tokenProgram", "isMut": false, "isSigner": false },
        { "name": "associatedTokenProgram", "isMut": false, "isSigner": false },
        { "name": "rent", "isMut": false, "isSigner": false },
        { "name": "eventAuthority", "isMut": false, "isSigner": false },
        { "name": "program", "isMut": false, "isSigner": false }
      ],
      "args": [
        { "name": "name", "type": "string" },
        { "name": "symbol", "type": "string" },
        { "name": "uri", "type": "string" }
      ]
    },
    {
      "name": "buy",
      "docs": ["Buys tokens from a bonding curve."],
      "accounts": [
        { "name": "global", "isMut": false, "isSigner": false },
        { "name": "feeRecipient", "isMut": true, "isSigner": false },
        { "name": "mint", "isMut": false, "isSigner": false },
        { "name": "bondingCurve", "isMut": true, "isSigner": false },
        { "name": "associatedBondingCurve", "isMut": true, "isSigner": false },
        { "name": "associatedUser", "isMut": true, "isSigner": false },
        { "name": "user", "isMut": true, "isSigner": true },
        { "name": "systemProgram", "isMut": false, "isSigner": false },
        { "name": "tokenProgram", "isMut": false, "isSigner": false },
        { "name": "rent", "isMut": false, "isSigner": false },
        { "name": "eventAuthority", "isMut": false, "isSigner": false },
        { "name": "program", "isMut": false, "isSigner": false }
      ],
      "args": [
        { "name": "amount", "type": "u64" },
        { "name": "maxSolCost", "type": "u64" }
      ]
    },
    {
      "name": "sell",
      "docs": ["Sells tokens into a bonding curve."],
      "accounts": [
        { "name": "global", "isMut": false, "isSigner": false },
        { "name": "feeRecipient", "isMut": true, "isSigner": false },
        { "name": "mint", "isMut": false, "isSigner": false },
        { "name": "bondingCurve", "isMut": true, "isSigner": false },
        { "name": "associatedBondingCurve", "isMut": true, "isSigner": false },
        { "name": "associatedUser", "isMut": true, "isSigner": false },
        { "name": "user", "isMut": true, "isSigner": true },
        { "name": "systemProgram", "isMut": false, "isSigner": false },
        { "name": "associatedTokenProgram", "isMut": false, "isSigner": false },
        { "name": "tokenProgram", "isMut": false, "isSigner": false },
        { "name": "eventAuthority", "isMut": false, "isSigner": false },
        { "name": "program", "isMut": false, "isSigner": false }
      ],
      "args": [
        { "name": "amount", "type": "u64" },
        { "name": "minSolOutput", "type": "u64" }
      ]
    },
    {
      "name": "withdraw",
      "docs": ["Allows the admin to withdraw liquidity for a migration once the bonding curve completes"],
      "accounts": [
        { "name": "global", "isMut": false, "isSigner": false },
        { "name": "lastWithdraw", "isMut": true, "isSigner": false },
        { "name": "mint", "isMut": false, "isSigner": false },
        { "name": "bondingCurve", "isMut": true, "isSigner": false },
        { "name": "associatedBondingCurve", "isMut": true, "isSigner": false },
        { "name": "associatedUser", "isMut": true, "isSigner": false },
        { "name": "user", "isMut": true, "isSigner": true },
        { "name": "systemProgram", "isMut": false, "isSigner": false },
        { "name": "tokenProgram", "isMut": false, "isSigner": false },
        { "name": "rent", "isMut": false, "isSigner": false },
        { "name": "eventAuthority", "isMut": false, "isSigner": false },
        { "name": "program", "isMut": false, "isSigner": false }
      ],
      "args": []
    }
  ],
  "accounts": [
    {
      "name": "Global",
      "type": {
        "kind": "struct",
        "fields": [
          { "name": "initialized", "type": "bool" },
          { "name": "authority", "type": "publicKey" },
          { "name": "feeRecipient", "type": "publicKey" },
          { "name": "initialVirtualTokenReserves", "type": "u64" },
          { "name": "initialVirtualSolReserves", "type": "u64" },
          { "name": "initialRealTokenReserves", "type": "u64" },
          { "name": "tokenTotalSupply", "type": "u64" },
          { "name": "feeBasisPoints", "type": "u64" }
        ]
      }
    },
    {
      "name": "LastWithdraw",
      "type": {
        "kind": "struct",
        "fields": [
          { "name": "lastWithdrawTimestamp", "type": "i64" }
        ]
      }
    },
    {
      "name": "BondingCurve",
      "type": {
        "kind": "struct",
        "fields": [
          { "name": "virtualTokenReserves", "type": "u64" },
          { "name": "virtualSolReserves", "type": "u64" },
          { "name": "realTokenReserves", "type": "u64" },
          { "name": "realSolReserves", "type": "u64" },
          { "name": "tokenTotalSupply", "type": "u64" },
          { "name": "complete", "type": "bool" }
        ]
      }
    }
  ],
  "events": [
    {
      "name": "CreateEvent",
      "fields": [
        { "name": "name", "type": "string", "index": false },
        { "name": "symbol", "type": "string", "index": false },
        { "name": "uri", "type": "string", "index": false },
        { "name": "mint", "type": "publicKey", "index": false },
        { "name": "bondingCurve", "type": "publicKey", "index": false },
        { "name": "user", "type": "publicKey", "index": false }
      ]
    },
    {
      "name": "TradeEvent",
      "fields": [
        { "name": "mint", "type": "publicKey", "index": false },
        { "name": "solAmount", "type": "u64", "index": false },
        { "name": "tokenAmount", "type": "u64", "index": false },
        { "name": "isBuy", "type": "bool", "index": false },
        { "name": "user", "type": "publicKey", "index": false },
        { "name": "timestamp", "type": "i64", "index": false },
        { "name": "virtualSolReserves", "type": "u64", "index": false },
        { "name": "virtualTokenReserves", "type": "u64", "index": false },
        { "name": "realSolReserves", "type": "u64", "index": false },
        { "name": "realTokenReserves", "type": "u64", "index": false }
      ]
    },
    {
      "name": "CompleteEvent",
      "fields": [
        { "name": "user", "type": "publicKey", "index": false },
        { "name": "mint", "type": "publicKey", "index": false },
        { "name": "bondingCurve", "type": "publicKey", "index": false },
        { "name": "timestamp", "type": "i64", "index": false }
      ]
    },
    {
      "name": "SetParamsEvent",
      "fields": [
        { "name": "feeRecipient", "type": "publicKey", "index": false },
        { "name": "initialVirtualTokenReserves", "type": "u64", "index": false },
        { "name": "initialVirtualSolReserves", "type": "u64", "index": false },
        { "name": "initialRealTokenReserves", "type": "u64", "index": false },
        { "name": "tokenTotalSupply", "type": "u64", "index": false },
        { "name": "feeBasisPoints", "type": "u64", "index": false }
      ]
    }
  ],
  "errors": [
    { "code": 6000, "name": "NotAuthorized", "msg": "The given account is not authorized to execute this instruction." },
    { "code": 6001, "name": "AlreadyInitialized", "msg": "The program is already initialized." },
    { "code": 6002, "name": "TooMuchSolRequired", "msg": "slippage: Too much SOL required to buy the given amount of tokens." },
    { "code": 6003, "name": "TooLittleSolReceived", "msg": "slippage: Too little SOL received to sell the given amount of tokens." },
    { "code": 6004, "name": "MintDoesNotMatchBondingCurve", "msg": "The mint does not match the bonding curve." },
    { "code": 6005, "name": "BondingCurveComplete", "msg": "The bonding curve has completed and liquidity migrated to raydium." },
    { "code": 6006, "name": "BondingCurveNotComplete", "msg": "The bonding curve has not completed." },
    { "code": 6007, "name": "NotInitialized", "msg": "The program is not initialized." },
    { "code": 6008, "name": "WithdrawTooFrequent", "msg": "Withdraw too frequent." }
  ]
}
    return Idl.from_json(idl_json)

async def monitor_new_tokens(client: AsyncClient):
    program = Program(await get_idl(), PUMP_FUN_PROGRAM, provider=client)
    sub = await client.logs_subscribe(
        LogsSubscribe(
            mentions=[str(PUMP_FUN_PROGRAM)],
            commitment="processed"
        )
    )
    async for msg in sub:
        if isinstance(msg, LogsNotification):
            for log in msg.value.logs:
                if "create" in log.lower():  # Detect create instr
                    try:
                        sig = Signature.from_string(msg.value.signature)
                        tx = await client.get_transaction(sig)
                        mint_str = parse_mint_from_tx(tx)
                        if mint_str:
                            mint = Pubkey.from_string(mint_str)
                            token_info = await evaluate_token(client, mint)
                            if token_info:
                                await snipe_token(token_info)
                                await log_meme_data(token_info)
                    except Exception as e:
                        logger.error(f"Parse error: {e}")

async def evaluate_token(client: AsyncClient, mint: Pubkey) -> dict | None:
    # Get liquidity
    pool = await get_pool(mint)
    liq = await get_pool_liquidity(client, pool)
    if liq < MIN_LIQUIDITY: return None

    # Check creator holdings (rug risk)
    creator = await get_creator(client, mint)
    creator_bal = await client.get_token_accounts_by_owner(creator, TokenAccountOpts(mint=mint))
    if creator_bal.value and creator_bal.value[0].amount > 0.2 * 1000000000: return None  # Assume total supply 1B, holds too much

    # Check socials
    metadata = await get_metadata(client, mint)
    if metadata.get("twitter"):
        followers = await get_twitter_followers(metadata["twitter"])
        if followers < MIN_FOLLOWERS: return None

    # AI veto (assume ask_ai_judge from signal_engine)
    df = await get_initial_data(client, mint)
    from signal_engine import ask_ai_judge
    if not ask_ai_judge(df): return None

    return {"mint": mint, "liq": liq, "metadata": metadata}

async def get_twitter_followers(url: str) -> int:
    # Simple scraper (may break; use X tool if needed)
    headers = {'User-Agent': 'Mozilla/5.0'}
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url, headers=headers) as resp:
            if resp.status == 200:
                text = await resp.text()
                # Parse for follower count (fragile, look for data-testid or class)
                if 'followers' in text:
                    # Placeholder parse
                    return 1500
    return 0  # Fallback

async def snipe_token(token_info: dict):
    # Simulate buy
    price = await get_current_price(token_info["mint"])
    sl = price * (1 - 0.1)
    tp = price * (1 + 0.3)
    from portfolio import open_position
    open_position(str(token_info["mint"]), price, "BUY", "MEME", sl, tp, "SNIPER")
    logger.info(f"Sniped {token_info['mint']} at {price}")

    # Monitor for sell
    asyncio.create_task(monitor_position(token_info["mint"], tp, sl, max_hold=300))

async def monitor_position(mint: Pubkey, tp: float, sl: float, max_hold: int):
    start = datetime.now()
    client = AsyncClient(RPC_URL)
    while (datetime.now() - start).seconds < max_hold:
        price = await get_current_price(mint)
        if price >= tp or price <= sl:
            from portfolio import update_positions  # Or add close_position
            await update_positions()  # Trigger update to close
            return
        await asyncio.sleep(10)
    await client.close()

# Custom helpers
async def get_pool(mint: Pubkey) -> Pubkey:
    seeds = [b"bonding_curve", mint.to_bytes()]
    return Pubkey.find_program_address(seeds, PUMP_FUN_PROGRAM)[0]

async def get_pool_liquidity(client: AsyncClient, pool: Pubkey) -> float:
    acc = await client.get_account_info(pool)
    if acc.value:
        # Parse data (assume bytes 0-8 virtual_sol, etc.; adjust based on account struct)
        data = acc.value.data
        virtual_sol = int.from_bytes(data[8:16], 'little')  # Example offset
        return virtual_sol / 1e9
    return 0.0

async def get_creator(client: AsyncClient, mint: Pubkey) -> Pubkey:
    # From metadata creator field
    metadata = await get_metadata(client, mint)
    creator_str = metadata.get("creator", "11111111111111111111111111111111")
    return Pubkey.from_string(creator_str)

async def get_metadata(client: AsyncClient, mint: Pubkey) -> dict:
    pda = Pubkey.find_program_address([b"metadata", METAPLEX_PROGRAM.to_bytes(), mint.to_bytes()], METAPLEX_PROGRAM)[0]
    acc = await client.get_account_info(pda)
    if acc.value:
        data = acc.value.data
        # Parse Metaplex metadata (name at 32, symbol at 64+len(name), uri at after symbol)
        name_len = int.from_bytes(data[32:36], 'little')
        name = data[36:36+name_len].decode('utf-8')
        symbol_len = int.from_bytes(data[36+name_len:36+name_len+4], 'little')
        symbol = data[36+name_len+4:36+name_len+4+symbol_len].decode('utf-8')
        uri_len = int.from_bytes(data[36+name_len+4+symbol_len:36+name_len+4+symbol_len+4], 'little')
        uri = data[36+name_len+4+symbol_len+4:36+name_len+4+symbol_len+4+uri_len].decode('utf-8')
        async with aiohttp.ClientSession() as sess:
            async with sess.get(uri) as resp:
                if resp.status == 200:
                    return await resp.json()
    return {}

async def get_current_price(mint: Pubkey) -> float:
    # Placeholder; use Jupiter API for quote
    async with aiohttp.ClientSession() as sess:
        async with sess.get(f"https://api.jup.ag/quote?inputMint=So11111111111111111111111111111111111111112&outputMint={str(mint)}&amount=1000000000") as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data['outAmount']) / 1e9  # Approximate price in SOL
    return 0.001

def parse_mint_from_tx(tx) -> str:
    # Basic parse: assume create instr data has mint after discriminator (8 bytes)
    instr = tx.value.transaction.message.instructions[0]
    data = instr.data
    if len(data) > 40:
        mint_bytes = data[8:40]  # Typical position for mint pubkey in create
        return base58.b58encode(mint_bytes).decode()
    return ""

async def get_initial_data(client: AsyncClient, mint: Pubkey) -> pd.DataFrame:
    # Placeholder OHLC for AI
    # Fetch recent trades or simulate
    return pd.DataFrame([{"close": 0.001, "rsi": 50}], index=[datetime.now()])  # Mock DF

async def log_meme_data(token_info: dict):
    rows = [{"timestamp": datetime.now().isoformat(), "mint": str(token_info["mint"]), "liq": token_info["liq"], "metadata": str(token_info["metadata"])}]
    df = pd.DataFrame(rows)
    write_header = not os.path.exists(DATA_FILE)
    try:
        df.to_csv(DATA_FILE, mode='a', header=write_header, index=False)
    except Exception as e:
        logger.error(f"Meme Log Error: {e}")
    return len(rows)

async def meme_snipe_loop():
    client = AsyncClient(RPC_URL)
    await monitor_new_tokens(client)
    await client.close()

if __name__ == "__main__":
    asyncio.run(meme_snipe_loop())

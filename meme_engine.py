import aiohttp
import asyncio
import pandas as pd
import os
from datetime import datetime

# --- CONFIG ---
API_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
DATA_FILE = "/app/data/meme_training_data.csv"

async def fetch_new_solana_pairs():
    """
    Fetches the latest token profiles (new launches) from DexScreener.
    Filters for SOLANA chain only.
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(API_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    # Filter for Solana pairs only
                    solana_pairs = [p for p in data if p.get('chainId') == 'solana']
                    return solana_pairs
        except Exception as e:
            print(f"Meme Fetch Error: {e}")
            return []
    return []

async def log_meme_data():
    """
    Main function to fetch and log new pairs.
    """
    pairs = await fetch_new_solana_pairs()
    
    if not pairs:
        return 0

    # Ensure data directory exists
    if not os.path.exists("/app/data"):
        os.makedirs("/app/data")

    # Prepare data for CSV
    rows = []
    for p in pairs:
        rows.append({
            "timestamp": datetime.now().isoformat(),
            "name": p.get('tokenAddress', 'Unknown'),
            "symbol": p.get('tokenAddress', 'Unknown'),
            "url": p.get('url', ''),
            "description": p.get('description', ''),
            "chain": "solana"
        })

    # Convert to DataFrame
    df = pd.DataFrame(rows)
    
    # Append to CSV (header only if file is new)
    write_header = not os.path.exists(DATA_FILE)
    
    try:
        df.to_csv(DATA_FILE, mode='a', header=write_header, index=False)
    except Exception as e:
        print(f"Meme Log Error: {e}")
        
    return len(rows)

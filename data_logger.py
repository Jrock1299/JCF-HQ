import os
import pandas as pd
from datetime import datetime

# --- CONFIG ---
# This matches the Mount Path you just set in Railway
DATA_DIR = "/app/data"
FILE_PATH = os.path.join(DATA_DIR, "market_training_data.csv")

def log_market_snapshot(symbol, df, asset_type):
    """
    Saves the latest candle + indicators to a CSV file.
    This creates the 'Dataset' for future AI training.
    """
    if df is None or df.empty: return

    # Ensure the directory exists (in case Volume isn't mounted yet, prevents crash)
    if not os.path.exists(DATA_DIR):
        try:
            os.makedirs(DATA_DIR)
        except:
            return # If we can't write, just skip

    # Get latest data point
    current = df.iloc[-1]
    
    # Create a single row of data
    data_row = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "type": asset_type,
        "close": current['close'],
        "rsi": current.get('RSI_14', 0),
        "ema_50": current.get('EMA_50', 0),
        "ema_200": current.get('EMA_200', 0),
        # We will add a 'Target' column later when training (Did price go up next?)
    }

    # Convert to DataFrame
    row_df = pd.DataFrame([data_row])

    # Append to CSV
    # If file doesn't exist, write header. If it does, append without header.
    write_header = not os.path.exists(FILE_PATH)
    
    try:
        row_df.to_csv(FILE_PATH, mode='a', header=write_header, index=False)
        # Optional: Print to logs occasionally to confirm it's working
        # print(f"💾 Logged data for {symbol}")
    except Exception as e:
        print(f"Data Log Error: {e}")

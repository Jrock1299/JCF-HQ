import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score
import joblib
import pandas_ta_classic as ta

# --- CONFIG ---
DATA_FILE = "/app/data/market_training_data.csv"
MODEL_FILE = "/app/data/jcf_brain.joblib"

def load_and_prep_data():
    """
    Loads the raw CSV and converts it into 'Features' (X) and 'Targets' (y).
    """
    try:
        df = pd.read_csv(DATA_FILE)
        print(f"📂 CSV Loaded. Raw columns: {list(df.columns)}") # Debug Log
    except FileNotFoundError:
        print("❌ Error: No training data found. Let the bot run longer!")
        return None, None

    # --- FIX: ROBUST COLUMN CLEANING ---
    # 1. Strip whitespace and make lowercase
    df.columns = df.columns.str.strip().str.lower()
    
    # 2. Check if 'high' exists now
    if 'high' not in df.columns:
        # Fallback: Maybe it's named 'h' or something else?
        print(f"⚠️ Column 'high' missing. Columns are: {list(df.columns)}")
        return None, None
        
    # 3. Clean 'Repeated Header' rows (Common logger bug)
    # If the CSV has lines like 'time,open,high...' in the middle, remove them
    df = df[df['high'].astype(str) != 'high']
    
    # 4. Force Numeric
    cols_to_convert = ['open', 'high', 'low', 'close', 'vol']
    for col in cols_to_convert:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
    df = df.dropna()
    # -----------------------------------

    if len(df) < 100:
        print(f"⚠️ Not enough clean data (Only {len(df)} rows). Need 100+.")
        return None, None

    # 2. Feature Engineering (The "Inputs" for the AI)
    # We re-calculate indicators to ensure they are consistent
    try:
        df['RSI'] = ta.rsi(df['close'], length=14)
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['EMA_50'] = ta.ema(df['close'], length=50)
        df['EMA_200'] = ta.ema(df['close'], length=200)
    except Exception as e:
        print(f"❌ Indicator Error: {e}")
        return None, None
    
    # Meaningful Features (What the AI actually sees)
    df['rsi_trend'] = df['RSI'] - df['RSI'].shift(1) # Is RSI rising or falling?
    df['price_vs_ema200'] = (df['close'] - df['EMA_200']) / df['EMA_200'] # How far from trend?
    df['volatility'] = df['ATR'] / df['close'] # Relative volatility
    
    # 3. Create the "Target" (What we want to predict)
    # Target = 1 (Price went UP significantly in next 4 hours)
    df['future_close'] = df['close'].shift(-4)
    df['target'] = (df['future_close'] > df['close'] + (df['ATR'] * 1.5)).astype(int)

    # Drop NaNs created by shifting
    df = df.dropna()

    # Define X (Inputs) and y (Output)
    # Ensure all these columns exist
    feature_cols = ['RSI', 'rsi_trend', 'price_vs_ema200', 'volatility', 'close']
    if 'vol' in df.columns: feature_cols.append('vol')
    
    X = df[feature_cols]
    y = df['target']
    
    return X, y

def train_brain():
    print("🧠 Waking up JCF AI Brain...")
    
    X, y = load_and_prep_data()
    if X is None: 
        print("❌ Training Aborted due to data issues.")
        return

    # Split data: 80% for training, 20% for testing
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    # Initialize the Model (Random Forest)
    model = RandomForestClassifier(n_estimators=100, min_samples_split=10, random_state=42)
    
    print(f"🏋️ Training on {len(X_train)} scenarios...")
    model.fit(X_train, y_train)
    
    # Evaluate
    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    precision = precision_score(y_test, predictions, zero_division=0)
    
    print("--- 🎓 EXAM RESULTS ---")
    print(f"✅ Accuracy: {accuracy:.1%}")
    print(f"🎯 Precision: {precision:.1%} (When it says BUY, is it right?)")
    
    # Save the Brain
    joblib.dump(model, MODEL_FILE)
    print(f"💾 Brain saved to {MODEL_FILE}")

if __name__ == "__main__":
    train_brain()

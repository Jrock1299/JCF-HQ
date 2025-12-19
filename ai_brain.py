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
    except FileNotFoundError:
        print("❌ Error: No training data found. Let the bot run longer!")
        return None, None

    # 1. Clean Data
    df = df.dropna()
    if len(df) < 100:
        print(f"⚠️ Not enough data to train (Only {len(df)} rows). Need 500+.")
        return None, None

    # 2. Feature Engineering (The "Inputs" for the AI)
    # We re-calculate indicators to ensure they are consistent
    df['RSI'] = ta.rsi(df['close'], length=14)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA_50'] = ta.ema(df['close'], length=50)
    df['EMA_200'] = ta.ema(df['close'], length=200)
    
    # Meaningful Features (What the AI actually sees)
    df['rsi_trend'] = df['RSI'] - df['RSI'].shift(1) # Is RSI rising or falling?
    df['price_vs_ema200'] = (df['close'] - df['EMA_200']) / df['EMA_200'] # How far from trend?
    df['volatility'] = df['ATR'] / df['close'] # Relative volatility
    
    # 3. Create the "Target" (What we want to predict)
    # We want to know: Did price go UP significantly in the next 4 hours?
    # Target = 1 (Buy Signal worked), 0 (It didn't)
    
    # Look 4 candles ahead
    df['future_close'] = df['close'].shift(-4)
    
    # Define "Success": Price increased by at least 0.5% (Crypto/Stocks) or 0.1% (Forex)
    # For a generic model, we'll use a dynamic threshold based on ATR
    df['target'] = (df['future_close'] > df['close'] + (df['ATR'] * 1.5)).astype(int)

    # Drop NaNs created by shifting
    df = df.dropna()

    # Define X (Inputs) and y (Output)
    feature_cols = ['RSI', 'rsi_trend', 'price_vs_ema200', 'volatility', 'close', 'volume']
    X = df[feature_cols]
    y = df['target']
    
    return X, y

def train_brain():
    print("🧠 Waking up JCF AI Brain...")
    
    X, y = load_and_prep_data()
    if X is None: return

    # Split data: 80% for training, 20% for testing
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    # Initialize the Model (Random Forest)
    # n_estimators=100 means it creates 100 decision trees and averages them
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

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score
import joblib

# --- CONFIG ---
DATA_FILE = "/app/data/market_training_data.csv"
MODEL_FILE = "/app/data/jcf_brain.joblib"

def load_and_prep_data():
    try:
        df = pd.read_csv(DATA_FILE)
    except FileNotFoundError:
        print("❌ Error: No training data found.")
        return None, None

    # 1. Clean Columns
    df.columns = df.columns.str.strip().str.lower()
    
    # Check for basic requirements
    if 'close' not in df.columns:
        print(f"❌ Critical Data Missing. Columns found: {list(df.columns)}")
        return None, None

    # 2. Force Numeric
    cols_to_convert = ['close', 'rsi', 'ema_50', 'ema_200']
    for col in cols_to_convert:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df = df.dropna()

    if len(df) < 50:
        print(f"⚠️ Not enough clean data (Only {len(df)} rows).")
        return None, None

    # 3. Feature Engineering (The Math)
    
    # Feature A: RSI Trend
    if 'rsi' in df.columns:
        df['rsi_trend'] = df['rsi'] - df['rsi'].shift(1)
    else:
        df['rsi'] = 50 
        df['rsi_trend'] = 0

    # Feature B: Distance from EMA 
    # (Safety: Avoid division by zero)
    if 'ema_200' in df.columns:
        df['dist_ema200'] = (df['close'] - df['ema_200']) / df['ema_200'].replace(0, np.nan)
    else:
        df['dist_ema200'] = 0

    if 'ema_50' in df.columns:
        df['dist_ema50'] = (df['close'] - df['ema_50']) / df['ema_50'].replace(0, np.nan)
    else:
        df['dist_ema50'] = 0
        
    # 4. Create Target
    df['future_close'] = df['close'].shift(-4)
    df['target'] = (df['future_close'] > df['close'] * 1.003).astype(int)

    # --- THE FIX: SANITIZE DATA ---
    # Replace Infinity with NaN
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    # Drop any rows that still have NaNs
    df = df.dropna()
    # ------------------------------

    # Define Inputs (X)
    feature_cols = ['rsi', 'rsi_trend', 'dist_ema200', 'dist_ema50', 'close']
    final_features = [c for c in feature_cols if c in df.columns]
    
    X = df[final_features]
    y = df['target']
    
    # Final Safety Check
    if len(X) == 0:
        print("❌ Error: All data removed during cleaning.")
        return None, None
        
    return X, y

def train_brain():
    print("🧠 Waking up JCF AI Brain (Adaptive Mode)...")
    
    X, y = load_and_prep_data()
    if X is None: 
        print("❌ Training Aborted due to data issues.")
        return

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    # Train Random Forest
    model = RandomForestClassifier(n_estimators=100, min_samples_split=10, random_state=42)
    
    print(f"🏋️ Training on {len(X_train)} scenarios...")
    try:
        model.fit(X_train, y_train)
    except ValueError as e:
        print(f"❌ Math Error during fit: {e}")
        return
    
    # Evaluate
    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    precision = precision_score(y_test, predictions, zero_division=0)
    
    print("--- 🎓 EXAM RESULTS ---")
    print(f"✅ Accuracy: {accuracy:.1%}")
    print(f"🎯 Precision: {precision:.1%} (Win Probability)")
    
    joblib.dump(model, MODEL_FILE)
    print(f"💾 Brain saved to {MODEL_FILE}")

if __name__ == "__main__":
    train_brain()

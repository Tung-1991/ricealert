# -*- coding: utf-8 -*-
"""
trainer.py - AI Model Trainer
Version: 2.0 (Complete Overhaul)
Date: 2025-07-03
Description: This version re-engineers the training process for better model performance.
             - Implements tri-class labeling (BUY, SELL, HOLD) for the classifier.
             - Adds more powerful features like ATR, distance to EMAs, and candle patterns.
             - Refactors the code for clarity and maintainability.
             - Improves the regression target for more stable predictions.
"""
import os
import json
import joblib
import warnings
import requests
import pandas as pd
import numpy as np
import lightgbm as lgb
import ta
from datetime import datetime, timedelta, timezone
from time import sleep
from dotenv import load_dotenv
from sklearn.model_selection import train_test_split

# ==============================================================================
# SETUP & CONFIG
# ==============================================================================
warnings.filterwarnings("ignore", category=UserWarning)
load_dotenv()

SYMBOLS   = os.getenv("SYMBOLS",  "LINKUSDT,TAOUSDT").split(",")
INTERVALS = os.getenv("INTERVALS", "1h,4h,1d").split(",")

def _load_map(name: str, fallback: dict) -> dict:
    raw = os.getenv(name)
    if raw:
        try: return json.loads(raw)
        except json.JSONDecodeError: print(f"[WARN] Failed to parse {name} from .env, using fallback.")
    return fallback

HIST_MAP  = _load_map("HISTORY_LENGTH_MAP", {"1h": 4000, "4h": 3000, "1d": 1500})
OFFS_MAP  = _load_map("FUTURE_OFFSET_MAP",  {"1h": 6, "4h": 4, "1d": 2})
LABEL_MAP = _load_map("LABEL_THRESHOLD_MAP",{"1h": 0.01, "4h": 0.02, "1d": 0.03}) # 1%, 2%, 3% threshold
STEP_MAP  = _load_map("STEP_MAP",           {"1h": 1000, "4h": 1000, "1d": 1000})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ==============================================================================
# DATA FETCHING & FEATURE ENGINEERING
# ==============================================================================
def get_price_data(symbol: str, interval: str, limit: int, end_time: datetime = None) -> pd.DataFrame:
    # (No change here, this function is good)
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time:
        params["endTime"] = int(end_time.timestamp() * 1000)
    data = requests.get(url, params=params, timeout=10).json()
    if not data or 'msg' in data:
        print(f"[WARN] Failed to fetch data for {symbol} {interval}: {data.get('msg', 'Empty response')}")
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume", "_clt", "_qav", "_trades", "_tb_base", "_tb_quote", "_ignore"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col])
    return df

def get_full_price_history(symbol: str, interval: str, total: int, step: int) -> pd.DataFrame:
    # (No change here, this function is good)
    chunks, rows_fetched = [], 0
    end_time = datetime.now(timezone.utc)
    while rows_fetched < total:
        part = get_price_data(symbol, interval, step, end_time)
        if part.empty: break
        chunks.insert(0, part)
        rows_fetched += len(part)
        end_time = part.index[0] - timedelta(milliseconds=1)
        sleep(0.1)
    if not chunks: return pd.DataFrame()
    return pd.concat(chunks).drop_duplicates().iloc[-total:]

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """New, more powerful feature engineering function."""
    out = df.copy()
    close = out["close"]
    
    # Momentum & Trend
    for n in [14, 20, 50]:
        out[f'rsi_{n}'] = ta.momentum.rsi(close, window=n)
        out[f'ema_{n}'] = ta.trend.ema_indicator(close, window=n)
        out[f'dist_ema_{n}'] = (close - out[f'ema_{n}']) / out[f'ema_{n}']
        
    macd = ta.trend.MACD(close)
    out["macd_diff"] = macd.macd_diff()
    out["adx"] = ta.trend.adx(out["high"], out["low"], close)
    
    # Volatility
    out['atr'] = ta.volatility.average_true_range(out["high"], out["low"], close)
    bb = ta.volatility.BollingerBands(close)
    out['bb_width'] = (bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg()
    
    # Volume
    out['cmf'] = ta.volume.chaikin_money_flow(out["high"], out["low"], close, out["volume"])
    
    # Candle Patterns
    out['candle_body'] = abs(close - out['open'])
    out['candle_range'] = out['high'] - out['low']
    out['body_to_range_ratio'] = out['candle_body'] / out['candle_range']
    
    # Time-based features
    out['hour'] = out.index.hour
    out['day_of_week'] = out.index.dayofweek
    
    return out.dropna()

def create_labels_and_targets(df: pd.DataFrame, fut_off: int, label_th: float):
    """New tri-class labeling and regression target creation."""
    future_price = df['close'].shift(-fut_off)
    
    # Classification Labels
    pct_change = (future_price - df['close']) / df['close']
    df['label'] = 1 # Default to HOLD
    df.loc[pct_change >= label_th, 'label'] = 2 # BUY
    df.loc[pct_change <= -label_th, 'label'] = 0 # SELL
    
    # Regression Target (predict change normalized by volatility)
    df['reg_target'] = pct_change / (df['atr'].rolling(window=fut_off).mean() + 1e-9)
    
    return df.dropna()

# ==============================================================================
# TRAINING
# ==============================================================================
def train_and_save(symbol: str, interval: str, df: pd.DataFrame):
    features = [col for col in df.columns if col not in ['open', 'high', 'low', 'close', 'label', 'reg_target']]
    X = df[features]
    y_clf = df['label']
    y_reg = df['reg_target']

    X_train, X_test, y_train_clf, y_test_clf = train_test_split(X, y_clf, test_size=0.15, shuffle=False)
    
    # Classifier
    clf_params = {
        'objective': 'multiclass', 'num_class': 3, 'metric': 'multi_logloss',
        'n_estimators': 1000, 'learning_rate': 0.05,
        'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 1,
        'lambda_l1': 0.1, 'lambda_l2': 0.1,
        'num_leaves': 31, 'verbose': -1, 'n_jobs': -1, 'seed': 42,
    }
    clf = lgb.LGBMClassifier(**clf_params)
    clf.fit(X_train, y_train_clf, eval_set=[(X_test, y_test_clf)], callbacks=[lgb.early_stopping(50, verbose=False)])

    # Regressor
    y_train_reg = y_reg.loc[X_train.index]
    reg_params = {
        'objective': 'regression_l1', 'metric': 'mae',
        'n_estimators': 1000, 'learning_rate': 0.05,
        'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 1,
        'num_leaves': 31, 'verbose': -1, 'n_jobs': -1, 'seed': 42,
    }
    reg = lgb.LGBMRegressor(**reg_params)
    reg.fit(X, y_reg) # Train regressor on all data for better generalization

    # Save models and metadata
    joblib.dump(clf, os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl"), compress=3)
    joblib.dump(reg, os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl"), compress=3)

    meta = {
        "features": features,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "label_threshold": LABEL_MAP.get(interval, 0.01),
        "future_offset": OFFS_MAP.get(interval, 4)
    }
    with open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json"), "w") as f:
        json.dump(meta, f, indent=2)

    class_counts = y_clf.value_counts()
    print(f"✅ {symbol} [{interval}] | {len(df)} samples (SELL:{class_counts.get(0,0)}, HOLD:{class_counts.get(1,0)}, BUY:{class_counts.get(2,0)})")

# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    for sym in SYMBOLS:
        for iv in INTERVALS:
            hist_len = HIST_MAP.get(iv, 3000)
            fut_off = OFFS_MAP.get(iv, 4)
            label_th = LABEL_MAP.get(iv, 0.01)
            step_size = STEP_MAP.get(iv, 1000)

            print(f"\n🔄 Building dataset for {sym} [{iv}]...")
            try:
                df_raw = get_full_price_history(sym, iv, hist_len + fut_off, step_size)
                if len(df_raw) < 500:
                    print(f"⚠️  Not enough data for {sym} [{iv}] ({len(df_raw)} rows) → skipping.")
                    continue
                    
                df_features = add_features(df_raw)
                df_dataset = create_labels_and_targets(df_features, fut_off, label_th)
                
                if len(df_dataset) < 200:
                    print(f"⚠️  Not enough data after processing for {sym} [{iv}] → skipping.")
                    continue

                print(f"🔬 Training models for {sym} [{iv}]...")
                train_and_save(sym, iv, df_dataset)

            except Exception as e:
                print(f"[CRITICAL] Failed to train {sym} [{iv}]: {e}")
                import traceback
                print(traceback.format_exc())

    print("\n🎯 Training completed.")

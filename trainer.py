# trainer.py
import os, json, joblib, requests, ta
import pandas as pd
import lightgbm as lgb
from datetime import datetime, timedelta, timezone
from time import sleep
from dotenv import load_dotenv
from sklearn.model_selection import train_test_split

# ========== ENV ==========
load_dotenv()

SYMBOLS   = os.getenv("SYMBOLS",  "LINKUSDT").split(",")
INTERVALS = os.getenv("INTERVALS","1h,4h,1d").split(",")

def _load_map(name: str, fallback: dict) -> dict:
    raw = os.getenv(name)
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"[WARN] ENV {name} parse lỗi, dùng fallback.")
        return fallback

HIST_MAP  = _load_map("HISTORY_LENGTH_MAP", {"1h":3000,"4h":2000,"1d":1000})
OFFS_MAP  = _load_map("FUTURE_OFFSET_MAP",  {"1h":4,   "4h":2,   "1d":1})
LABEL_MAP = _load_map("LABEL_THRESHOLD_MAP",{"1h":0.0075,"4h":0.01,"1d":0.015})
STEP_MAP  = _load_map("STEP_MAP",            {"1h":1000,"4h":500,"1d":200})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ---------- Binance fetch ----------
def get_price_data(symbol:str, interval:str, limit:int=1000,
                   end_time:datetime|None=None) -> pd.DataFrame:
    url    = "https://api.binance.com/api/v3/klines"
    params = {"symbol":symbol,"interval":interval,"limit":limit}
    if end_time:
        params["endTime"] = int(end_time.timestamp()*1000)
    data = requests.get(url, params=params, timeout=10).json()

    df = pd.DataFrame(data, columns=[
        "timestamp","open","high","low","close","volume",
        "_clt","_qav","_trades","_tb_base","_tb_quote","_ignore"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df[["open","high","low","close","volume"]] = df[
        ["open","high","low","close","volume"]].astype(float)
    return df

def get_full_price_history(symbol, interval, total, step) -> pd.DataFrame:
    chunks, rows = [], 0
    end_time = datetime.now(timezone.utc)
    while rows < total:
        part = get_price_data(symbol, interval, step, end_time)
        if part.empty: break
        chunks.insert(0, part)
        rows += len(part)
        end_time = part.index[0] - timedelta(minutes=1)
        sleep(0.1)
    return pd.concat(chunks).iloc[-total:]

# ---------- Indicators ----------
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema_20"]  = ta.trend.ema_indicator(out["close"], 20)
    out["ema_50"]  = ta.trend.ema_indicator(out["close"], 50)
    out["rsi_14"]  = ta.momentum.rsi(out["close"], 14)
    bb             = ta.volatility.BollingerBands(out["close"], 20, 2)
    out["bb_upper"]= bb.bollinger_hband()
    out["bb_lower"]= bb.bollinger_lband()
    macd           = ta.trend.MACD(out["close"])
    out["macd_line"]   = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["adx"]     = ta.trend.adx(out["high"], out["low"], out["close"], 14)
    out["vol_ma20"]= out["volume"].ewm(span=20, adjust=False).mean()
    out["cmf"]     = ta.volume.chaikin_money_flow(
                        out["high"], out["low"], out["close"], out["volume"], 20)
    rl_low  = out["low"].rolling(50).min()
    rl_high = out["high"].rolling(50).max()
    out["fib_0_618"] = rl_high - (rl_high - rl_low) * 0.618
    out["price"] = out["close"]
    return out.dropna()

# ---------- Dataset ----------
def build_dataset(symbol, interval, hist_len, fut_off, label_th, step):
    df_raw = get_full_price_history(symbol, interval, hist_len + fut_off, step)
    df_ind = add_indicators(df_raw)

    X_rows, y_clf, y_reg, idxs = [], [], [], []
    for i in range(fut_off, len(df_ind)):
        past, fut = i - fut_off, i
        cur_p = df_ind.iloc[past]["close"]
        fut_p = df_ind.iloc[fut]["close"]
        pct   = (fut_p - cur_p) / cur_p
        label = 1 if pct >= label_th else 0

        feat = df_ind.iloc[past][[
            "price","ema_20","ema_50","rsi_14","bb_upper","bb_lower",
            "macd_line","macd_signal","adx","volume","vol_ma20",
            "cmf","fib_0_618"
        ]]

        X_rows.append(feat)
        y_clf.append(label)
        y_reg.append(pct)
        idxs.append(df_ind.index[past])

    X = pd.DataFrame(X_rows)
    X["timestamp"] = idxs
    return X, pd.Series(y_clf,name="label"), pd.Series(y_reg,name="reg_target")

# ---------- Train ----------
def train_and_save(symbol, interval, X, y_c, y_r):
    feats = X.drop(columns=["timestamp"]).columns.tolist()
    Xtr,Xval,ytr,yval = train_test_split(
        X[feats], y_c, test_size=0.1,
        shuffle=True, stratify=y_c, random_state=42)

    clf = lgb.LGBMClassifier(
        n_estimators=1000,learning_rate=0.05,max_depth=7,
        class_weight='balanced',n_jobs=-1,random_state=42)
    clf.fit(Xtr,ytr,eval_set=[(Xval,yval)],early_stopping_rounds=50,verbose=False)

    reg = lgb.LGBMRegressor(
        n_estimators=600,learning_rate=0.05,max_depth=6,
        n_jobs=-1,random_state=42)
    reg.fit(X[feats],y_r)

    joblib.dump(clf, os.path.join(DATA_DIR,f"model_{symbol}_clf_{interval}.pkl"), compress=3)
    joblib.dump(reg, os.path.join(DATA_DIR,f"model_{symbol}_reg_{interval}.pkl"), compress=3)

    meta = {"features":feats, "threshold":0.6,
            "trained_at":datetime.utcnow().isoformat()}
    with open(os.path.join(DATA_DIR,f"meta_{symbol}_{interval}.json"),"w") as f:
        json.dump(meta,f,indent=2)

    log = X.copy()
    log["label"], log["reg_target"] = y_c, y_r
    log.to_csv(os.path.join(DATA_DIR,f"train_data_{symbol}_{interval}.csv"), index=False)

    pos,neg = int(y_c.sum()),len(y_c)-int(y_c.sum())
    print(f"✅ {symbol} [{interval}] | {len(y_c)} samp (👍{pos}/👎{neg})")

# ---------- Main ----------
if __name__ == "__main__":
    for sym in SYMBOLS:
        for iv in INTERVALS:
            hist_len   = HIST_MAP.get(iv, 3000)
            fut_off    = OFFS_MAP.get(iv, 4)
            label_th   = LABEL_MAP.get(iv, 0.0075)
            step_size  = STEP_MAP.get(iv, 1000)

            print(f"\n🔄 {sym} [{iv}] hist={hist_len} off={fut_off} "
                  f"label={label_th} step={step_size}")

            X, y_clf, y_reg = build_dataset(
                sym, iv,
                hist_len=hist_len,
                fut_off=fut_off,
                label_th=label_th,
                step=step_size
            )
            if len(X) < 50:
                print(f"⚠️  {sym} [{iv}] thiếu data → skip.")
                continue
            train_and_save(sym, iv, X, y_clf, y_reg)
    print("\n🎯 Training completed.")

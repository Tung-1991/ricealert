# ===================== trainer.py — PROD v1.4 =====================
# DEBUG=0 -> log sạch, KHÔNG epoch (crontab/detached)
# DEBUG=1 -> có epoch, giữ tiến độ; vẫn chặn ptx85/NUMA/XLA/absl/retracing
# ================================================================

import os, sys, re, warnings, json, random, threading, select
from datetime import datetime, timedelta, timezone
from time import sleep

# --- ENV để giảm rác TF/XLA ---
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("TF_XLA_FLAGS", "--tf_xla_auto_jit=0 --tf_xla_enable_xla_devices=false")
os.environ.setdefault("XLA_FLAGS", "--xla_gpu_use_runtime_fusion=false --xla_gpu_enable_triton=false")

DEBUG = os.getenv("DEBUG","0") == "1"
VERBOSE = 2 if DEBUG else 0

# --- Bộ lọc rác + điều kiện epoch ---
_PAT_RUBBISH = re.compile(
    r"(" +
    r"\+ptx85|numa_node|NUMA support|"
    r"^=+ TensorFlow =+\s*$|XLA service .* initialized|Compiled cluster using XLA|"
    r"^I\d{4}|^W\d{4}|^E\d{4}|"
    r"StreamExecutor device|retracing\." +
    r")"
)
_PAT_EPOCH = re.compile(r"^\s*Epoch\s+\d+/\d+\s*$")

def _keep_line(s: str, allow_epoch: bool) -> bool:
    if _PAT_RUBBISH.search(s):
        return False
    if (not allow_epoch) and _PAT_EPOCH.search(s):
        return False
    return True

# --- Gắn filter ở C-STDOUT/C-STDERR (fd-level), trước khi import TF ---
def attach_fd_filter(fd: int, allow_epoch: bool):
    r_fd, w_fd = os.pipe()
    orig_fd = os.dup(fd)
    os.dup2(w_fd, fd)         # redirect C-level fd -> pipe
    os.close(w_fd)

    def _pump():
        with os.fdopen(r_fd, 'rb', buffering=0) as r, os.fdopen(orig_fd, 'wb', buffering=0) as w:
            buf = b""
            while True:
                rlist, _, _ = select.select([r.fileno()], [], [], 0.1)
                if rlist:
                    chunk = os.read(r.fileno(), 4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            s = line.decode("utf-8", "ignore")
                        except:
                            s = str(line)
                        if _keep_line(s, allow_epoch):
                            w.write((s+"\n").encode("utf-8", "ignore"))
                            w.flush()
                else:
                    # flush phần dư nếu stream kết thúc không có \n
                    if buf:
                        try:
                            s = buf.decode("utf-8", "ignore")
                        except:
                            s = str(buf)
                        if _keep_line(s, allow_epoch):
                            w.write((s).encode("utf-8", "ignore"))
                            w.flush()
                        buf = b""

    t = threading.Thread(target=_pump, daemon=True)
    t.start()

# Gắn cho cả stdout (fd=1) & stderr (fd=2)
attach_fd_filter(1, allow_epoch=DEBUG)
attach_fd_filter(2, allow_epoch=DEBUG)

# ---------------- TF + imports còn lại ----------------
warnings.filterwarnings("ignore", category=UserWarning)

import numpy as np, pandas as pd, requests, joblib, lightgbm as lgb, ta
import tensorflow as tf
tf.config.optimizer.set_jit(False)
try:
    import absl.logging as absl_logging
    absl_logging.set_verbosity(absl_logging.ERROR)
except Exception:
    pass
tf.get_logger().setLevel("ERROR")
for h in tf.get_logger().handlers:
    try: h.setLevel("ERROR")
    except Exception: pass

from dotenv import load_dotenv
from tensorflow.keras.utils import to_categorical
from tensorflow.keras.models import Model
from tensorflow.keras.layers import (
    Input, LSTM, Dense, Dropout, LayerNormalization, MultiHeadAttention,
    GlobalAveragePooling1D, Add, BatchNormalization
)
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# ---------------- Config ----------------
SEED = 42
random.seed(SEED); np.random.seed(SEED); tf.random.set_seed(SEED)
load_dotenv()

SYMBOLS   = os.getenv("SYMBOLS",  "ETHUSDT,BTCUSDT").split(",")
INTERVALS = os.getenv("INTERVALS","1h,4h,1d").split(",")

def _load_map(env_var: str, fallback: dict) -> dict:
    raw = os.getenv(env_var)
    if raw:
        try: return json.loads(raw)
        except json.JSONDecodeError: print(f"[WARN] Lỗi parse {env_var}, dùng mặc định.")
    return fallback

HIST_MAP = _load_map("HISTORY_LENGTH_MAP", {"1h":3000, "4h":2000, "1d":1000})
OFFS_MAP = _load_map("FUTURE_OFFSET_MAP",  {"1h":4, "4h":2, "1d":1})
LABEL_MAP= _load_map("LABEL_ATR_FACTOR_MAP",{"1h":0.65, "4h":0.75,"1d":0.85})
STEP_MAP = _load_map("STEP_MAP",           {"1h":1000, "4h":1000, "1d":1000})
MIN_MAP  = _load_map("MIN_SAMPLE_MAP",     {"1h":400, "4h":300, "1d":200})
SEQUENCE_LENGTH = 60
TRANSFORMER_HEADS = 8
TRANSFORMER_LAYERS = 4
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ---------------- Data utils ----------------
def get_price_data(symbol: str, interval: str, limit: int, end_time: datetime = None) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time: params["endTime"] = int(end_time.timestamp() * 1000)
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data: return pd.DataFrame()
        df = pd.DataFrame(data, columns=["timestamp","open","high","low","close","volume","c1","c2","c3","c4","c5","c6"]).iloc[:, :6]
        df.columns = ["timestamp","open","high","low","close","volume"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df.astype(float)
    except Exception as e:
        print(f"[ERROR] get_price_data {symbol} {interval}: {e}")
        return pd.DataFrame()

def get_full_price_history(symbol: str, interval: str, total: int, step: int) -> pd.DataFrame:
    chunks, rows_fetched = [], 0
    end_time = datetime.now(timezone.utc)
    while rows_fetched < total:
        part = get_price_data(symbol, interval, step, end_time)
        if part.empty: break
        chunks.insert(0, part)
        rows_fetched += len(part)
        end_time = part.index[0] - timedelta(milliseconds=1)
        sleep(0.25)
    if not chunks: return pd.DataFrame()
    return pd.concat(chunks).drop_duplicates().sort_index().iloc[-total:]

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close, high, low, volume = out["close"], out["high"], out["low"], out["volume"]
    out['price'] = close
    out['vol_ma20'] = volume.rolling(window=20).mean()
    bb = ta.volatility.BollingerBands(close, window=20)
    out['bb_upper'], out['bb_lower'] = bb.bollinger_hband(), bb.bollinger_lband()
    out['bb_width'] = (out['bb_upper'] - out['bb_lower']) / (bb.bollinger_mavg() + 1e-9)
    macd = ta.trend.MACD(close)
    out['macd'], out['macd_signal'], out["macd_diff"] = macd.macd(), macd.macd_signal(), macd.macd_diff()
    for n in [14, 28, 50]:
        out[f'rsi_{n}'] = ta.momentum.rsi(close, window=n)
        out[f'ema_{n}'] = ta.trend.ema_indicator(close, window=n)
        out[f'dist_ema_{n}'] = (close - out[f'ema_{n}']) / (out[f'ema_{n}'] + 1e-9)
    out["adx"] = ta.trend.adx(high, low, close)
    out['atr'] = ta.volatility.average_true_range(high, low, close, window=14)
    out['cmf'] = ta.volume.chaikin_money_flow(high, low, close, volume, window=20)
    for n in [1,2,3,5,8,13,21]:
        out[f'pct_change_lag_{n}'] = close.pct_change(periods=n)
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.bfill(inplace=True); out.ffill(inplace=True); out.fillna(0, inplace=True)
    return out

def create_labels_and_targets(df: pd.DataFrame, fut_off: int, atr_factor: float):
    df_copy = df.copy()
    future_price = df_copy['close'].shift(-fut_off)
    atr_threshold = atr_factor * df_copy['atr']
    df_copy['label'] = 1
    df_copy.loc[(future_price - df_copy['close']) > atr_threshold, 'label'] = 2
    df_copy.loc[(df_copy['close'] - future_price) > atr_threshold, 'label'] = 0
    atr_smooth = df_copy['atr'].rolling(window=fut_off).mean() + 1e-9
    df_copy['reg_target'] = (future_price - df_copy['close']) / atr_smooth
    df_copy['reg_target'] = df_copy['reg_target'].clip(lower=-10, upper=10)
    return df_copy.dropna()

# ---------------- Models ----------------
def create_sequences(data: pd.DataFrame, feature_cols: list, label_clf_col: str, label_reg_col: str, seq_length: int):
    X, y_clf, y_reg = [], [], []
    for i in range(len(data) - seq_length):
        X.append(data[feature_cols].iloc[i:(i + seq_length)].values)
        y_clf.append(data[label_clf_col].iloc[i + seq_length])
        y_reg.append(data[label_reg_col].iloc[i + seq_length])
    return np.array(X), np.array(y_clf), np.array(y_reg)

from tensorflow.keras.models import Model
from tensorflow.keras.layers import Input, LSTM, Dense, Dropout, LayerNormalization, MultiHeadAttention, GlobalAveragePooling1D, Add, BatchNormalization

def build_lstm_model(input_shape: tuple, model_type: str = 'classifier'):
    inputs = Input(shape=input_shape)
    x = LSTM(100, return_sequences=True, unroll=True)(inputs)
    x = Dropout(0.2)(x)
    x = LSTM(50, return_sequences=False, unroll=True)(x)
    x = Dropout(0.2)(x)
    x = Dense(25)(x)
    x = BatchNormalization()(x)
    if model_type == 'classifier':
        outputs = Dense(3, activation='softmax')(x)
        model = Model(inputs, outputs)
        model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'], run_eagerly=True)
    else:
        outputs = Dense(1, activation='linear')(x)
        model = Model(inputs, outputs)
        model.compile(optimizer='adam', loss='mean_squared_error', metrics=['mae'], run_eagerly=True)
    return model

def transformer_encoder_block(inputs, head_size, num_heads, ff_dim, dropout=0):
    x = LayerNormalization(epsilon=1e-6)(inputs)
    x = MultiHeadAttention(key_dim=head_size, num_heads=num_heads, dropout=dropout)(x, x)
    x = Dropout(dropout)(x)
    res = Add()([x, inputs])
    x = LayerNormalization(epsilon=1e-6)(res)
    x = Dense(ff_dim, activation="relu")(x)
    x = Dropout(dropout)(x)
    x = Dense(inputs.shape[-1])(x)
    return Add()([x, res])

def build_transformer_model(input_shape, head_size, num_heads, ff_dim, num_layers, dropout=0, model_type='classifier'):
    inputs = Input(shape=input_shape)
    x = inputs
    for _ in range(num_layers):
        x = transformer_encoder_block(x, head_size, num_heads, ff_dim, dropout)
    x = GlobalAveragePooling1D(data_format="channels_last")(x)
    x = Dense(20, activation="relu")(x)
    x = Dropout(0.1)(x)
    if model_type == 'classifier':
        outputs = Dense(3, activation="softmax")(x)
        model = Model(inputs, outputs)
        model.compile(optimizer="adam", loss="categorical_crossentropy", metrics=["accuracy"], run_eagerly=True)
    else:
        outputs = Dense(1, activation="linear")(x)
        model = Model(inputs, outputs)
        model.compile(optimizer="adam", loss="mean_squared_error", metrics=["mae"], run_eagerly=True)
    return model

from sklearn.preprocessing import StandardScaler
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

def train_and_save_all_models(symbol: str, interval: str, df: pd.DataFrame):
    print(f"--- Bắt đầu xử lý {symbol} [{interval}] ---")
    base_features = ['open', 'high', 'low', 'close', 'price']
    label_cols = ['label', 'reg_target']
    features_to_use = [c for c in df.columns if c not in base_features + label_cols]

    scaler = StandardScaler()
    df_scaled = df.copy()
    df_scaled[features_to_use] = scaler.fit_transform(df[features_to_use]).astype(np.float32)

    print("  -> (1/3) LightGBM...")
    try:
        X_lgbm, y_clf_lgbm, y_reg_lgbm = df[features_to_use], df['label'], df['reg_target']
        X_train, X_test, y_train_clf, y_test_clf, y_train_reg, y_test_reg = train_test_split(
            X_lgbm, y_clf_lgbm, y_reg_lgbm, test_size=0.15, shuffle=False)
        clf_lgbm = lgb.LGBMClassifier(objective='multiclass', num_class=3, is_unbalance=True, n_estimators=1000, learning_rate=0.05, verbose=-1, n_jobs=-1)
        clf_lgbm.fit(X_train, y_train_clf, eval_set=[(X_test, y_test_clf)], callbacks=[lgb.early_stopping(50, verbose=False)])
        reg_lgbm = lgb.LGBMRegressor(objective='regression_l1', n_estimators=1000, learning_rate=0.05, verbose=-1, n_jobs=-1)
        reg_lgbm.fit(X_train, y_train_reg, eval_set=[(X_test, y_test_reg)], callbacks=[lgb.early_stopping(50, verbose=False)])
        joblib.dump(clf_lgbm, os.path.join(DATA_DIR, f"model_{symbol}_lgbm_clf_{interval}.pkl"), compress=3)
        joblib.dump(reg_lgbm, os.path.join(DATA_DIR, f"model_{symbol}_lgbm_reg_{interval}.pkl"), compress=3)
        print("     ✅ LightGBM xong.")
    except Exception as e:
        print(f"     ❌ LGBM lỗi: {e}")

    print("  -> Dựng dữ liệu chuỗi cho DL...")
    try:
        X_seq, y_clf_seq, y_reg_seq = create_sequences(df_scaled, features_to_use, 'label', 'reg_target', SEQUENCE_LENGTH)
        X_seq = X_seq.astype(np.float32)
        y_clf_seq = to_categorical(y_clf_seq.astype(np.int32), num_classes=3).astype(np.float32)
        y_reg_seq = y_reg_seq.astype(np.float32)
        if len(X_seq) < 100:
            raise ValueError(f"Không đủ chuỗi ({len(X_seq)}).")
    except Exception as e:
        print(f"     ❌ Tạo chuỗi lỗi: {e}. Bỏ qua DL.")
        meta = {
            "features": features_to_use,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "atr_factor_threshold": OFFS_MAP.get(interval, 0.75),
            "future_offset": OFFS_MAP.get(interval, 4),
            "sequence_length": SEQUENCE_LENGTH
        }
        joblib.dump(scaler, os.path.join(DATA_DIR, f"scaler_{symbol}_{interval}.pkl"))
        with open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json"), "w") as f:
            json.dump(meta, f, indent=2)
        return

    input_shape = (X_seq.shape[1], X_seq.shape[2])

    print("  -> (2/3) LSTM...")
    try:
        clf_lstm = build_lstm_model(input_shape, model_type='classifier')
        reg_lstm = build_lstm_model(input_shape, model_type='regressor')
        clf_path = os.path.join(DATA_DIR, f"model_{symbol}_lstm_clf_{interval}.h5")
        reg_path = os.path.join(DATA_DIR, f"model_{symbol}_lstm_reg_{interval}.h5")
        clf_callbacks = [EarlyStopping(patience=10, monitor='val_accuracy', mode='max', restore_best_weights=True), ModelCheckpoint(filepath=clf_path, save_best_only=True, monitor='val_accuracy', mode='max')]
        reg_callbacks = [EarlyStopping(patience=10, monitor='val_loss', mode='min', restore_best_weights=True), ModelCheckpoint(filepath=reg_path, save_best_only=True, monitor='val_loss', mode='min')]
        clf_lstm.fit(X_seq, y_clf_seq, epochs=50, batch_size=64, validation_split=0.15, callbacks=clf_callbacks, verbose=VERBOSE)
        reg_lstm.fit(X_seq, y_reg_seq, epochs=50, batch_size=64, validation_split=0.15, callbacks=reg_callbacks, verbose=VERBOSE)
        print("     ✅ LSTM xong.")
    except Exception as e:
        print(f"     ❌ LSTM lỗi: {e}")

    print("  -> (3/3) Transformer...")
    try:
        clf_trans = build_transformer_model(input_shape, head_size=256, num_heads=TRANSFORMER_HEADS, ff_dim=4, num_layers=TRANSFORMER_LAYERS, model_type='classifier')
        reg_trans = build_transformer_model(input_shape, head_size=256, num_heads=TRANSFORMER_HEADS, ff_dim=4, num_layers=TRANSFORMER_LAYERS, model_type='regressor')
        clf_path = os.path.join(DATA_DIR, f"model_{symbol}_transformer_clf_{interval}.h5")
        reg_path = os.path.join(DATA_DIR, f"model_{symbol}_transformer_reg_{interval}.h5")
        clf_callbacks = [EarlyStopping(patience=10, monitor='val_accuracy', mode='max', restore_best_weights=True), ModelCheckpoint(filepath=clf_path, save_best_only=True, monitor='val_accuracy', mode='max')]
        reg_callbacks = [EarlyStopping(patience=10, monitor='val_loss', mode='min', restore_best_weights=True), ModelCheckpoint(filepath=reg_path, save_best_only=True, monitor='val_loss', mode='min')]
        clf_trans.fit(X_seq, y_clf_seq, epochs=50, batch_size=64, validation_split=0.15, callbacks=clf_callbacks, verbose=VERBOSE)
        reg_trans.fit(X_seq, y_reg_seq, epochs=50, batch_size=64, validation_split=0.15, callbacks=reg_callbacks, verbose=VERBOSE)
        print("     ✅ Transformer xong.")
    except Exception as e:
        print(f"     ❌ Transformer lỗi: {e}")

    meta = {
        "features": features_to_use,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "atr_factor_threshold": LABEL_MAP.get(interval, 0.75),
        "future_offset": OFFS_MAP.get(interval, 4),
        "sequence_length": SEQUENCE_LENGTH
    }
    joblib.dump(scaler, os.path.join(DATA_DIR, f"scaler_{symbol}_{interval}.pkl"))
    with open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json"), "w") as f:
        json.dump(meta, f, indent=2)
    counts = pd.Series(df['label']).value_counts()
    print(f"--- ✅ Xong {symbol} [{interval}] | Tổng: {len(df)} (S:{counts.get(0,0)}, H:{counts.get(1,0)}, B:{counts.get(2,0)}) ---\n")

# ---------------- Main ----------------
if __name__ == "__main__":
    gpus = tf.config.list_physical_devices('GPU')
    if gpus:
        try:
            for gpu in gpus:
                tf.config.experimental.set_memory_growth(gpu, True)
            print(f"✅ GPU(s) phát hiện: {len(gpus)} → memory_growth=ON")
        except RuntimeError as e:
            print(f"[WARN] set_memory_growth: {e}")
    else:
        print("⚠️ Không phát hiện GPU. Sẽ chạy CPU (chậm).")

    intervals_to_train = [iv.strip() for iv in INTERVALS if iv.strip()]
    if len(sys.argv) > 1:
        intervals_to_train = [iv.strip() for iv in sys.argv[1].split(',') if iv.strip()]
        print(f"🚀 Huấn luyện theo CLI intervals: {intervals_to_train}")

    for sym in SYMBOLS:
        for iv in intervals_to_train:
            hist_len   = HIST_MAP.get(iv, 3000)
            fut_off    = OFFS_MAP.get(iv, 4)
            atr_factor = LABEL_MAP.get(iv, 0.75)
            step_size  = STEP_MAP.get(iv, 1000)
            min_rows   = MIN_MAP.get(iv, 500)
            print(f"\n🔄 Dựng dữ liệu {sym} [{iv}]...")
            try:
                df_raw = get_full_price_history(sym, iv, hist_len + fut_off + SEQUENCE_LENGTH, step_size)
                if len(df_raw) < min_rows:
                    print(f"❌ Bỏ {sym} [{iv}] – chỉ có {len(df_raw)} nến (< {min_rows}).")
                    continue
                df_features = add_features(df_raw)
                df_dataset  = create_labels_and_targets(df_features, fut_off, atr_factor)
                if len(df_dataset) < (min_rows // 2):
                    print(f"⚠️ Bỏ {sym} [{iv}] – mẫu hợp lệ sau nhãn quá ít: {len(df_dataset)}.")
                    continue
                train_and_save_all_models(sym, iv, df_dataset)
            except Exception as e:
                print(f"[CRITICAL] Lỗi xử lý {sym} [{iv}]: {e}")
                import traceback; print(traceback.format_exc())

    print("\n🎯 TOÀN BỘ QUÁ TRÌNH HUẤN LUYỆN HOÀN TẤT.")
    print("Có thể nén thư mục 'data' để deploy.")
# =================== END trainer.py ===================

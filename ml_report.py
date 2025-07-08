# /root/ricealert/ml_report.py
"""
Merged version (File 1 foundation + safe embed splitting of File 2)
 – Keeps sub‑level‑aware cooldown & single API call (no redundant caching)
 – Adds 1 900‑char safeguard when sending embeds, without complex field truncation
"""
import os, json, time, requests, sys
import pandas as pd, numpy as np, ta
import joblib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from typing import List, Dict, Optional
from itertools import groupby

# --------------------------------------------------
# PATH & BASIC CONFIG
# --------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

load_dotenv()
SYMBOLS       = os.getenv("SYMBOLS", "LINKUSDT,TAOUSDT,ETHUSDT,AVAXUSDT,INJUSDT,SUIUSDT,FETUSDT").split(",")
INTERVALS     = os.getenv("INTERVALS", "1h,4h,1d").split(",")
WEBHOOK_URL   = os.getenv("DISCORD_AI_WEBHOOK")
ERROR_WEBHOOK = os.getenv("DISCORD_ERROR_WEBHOOK", "")

MAX_EMBED_FIELDS = 24          # field‑count safeguard
MAX_EMBED_CHARS  = 1900        # char‑count safeguard (< 2 000)
API_LIMIT_PER_KLINE = 200      # binance limit per request

DATA_DIR   = os.path.join(BASE_DIR, "data")
LOG_DIR    = os.path.join(BASE_DIR, "ai_logs")
STATE_FILE = os.path.join(BASE_DIR, "ml_state.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# --------------------------------------------------
# CONSTANT MAPS
# --------------------------------------------------
COOLDOWN_BY_LEVEL = {
    "STRONG_BUY": 3600, "PANIC_SELL": 3600,
    "BUY": 7200, "SELL": 7200,
    "WEAK_BUY": 14400, "WEAK_SELL": 14400,
    "HOLD": 28800, "AVOID": 28800,
}
LEVEL_MAP = {
    "STRONG_BUY": {"icon": "🚀", "name": "STRONG BUY"},
    "BUY":        {"icon": "✅", "name": "BUY"},
    "WEAK_BUY":   {"icon": "🟢", "name": "WEAK BUY"},
    "HOLD":       {"icon": "🔍", "name": "HOLD"},
    "AVOID":      {"icon": "🚧", "name": "AVOID"},
    "WEAK_SELL":  {"icon": "🔻", "name": "WEAK SELL"},
    "SELL":       {"icon": "❌", "name": "SELL"},
    "PANIC_SELL": {"icon": "🆘", "name": "PANIC SELL"},
}
SUB_LEVEL_INFO = {
    "HOLD_BULLISH":   {"icon": "📈", "name": "HOLD (Thiên Tăng)", "desc": "Thị trường tích lũy, thiên tăng."},
    "HOLD_BEARISH":   {"icon": "📉", "name": "HOLD (Thiên Giảm)", "desc": "Thị trường phân phối, thiên giảm."},
    "HOLD_NEUTRAL":   {"icon": "🤔", "name": "HOLD (Trung Lập)",  "desc": "Biến động quá nhỏ."},
    "AVOID_UNCERTAIN":{"icon": "❓", "name": "AVOID (Không Chắc)", "desc": "Tín hiệu nhiễu."},
    "AVOID_CONFLICT": {"icon": "⚔️", "name": "AVOID (Xung Đột)", "desc": "Tín hiệu trái chiều."},
    "DEFAULT":        {"icon": "",   "name": "",                "desc": ""},
}

def get_sub_info(key:str)->dict:
    return SUB_LEVEL_INFO.get(key, SUB_LEVEL_INFO["DEFAULT"])

# --------------------------------------------------
# DATA HELPERS
# --------------------------------------------------

def get_price_data(symbol:str, interval:str, limit:int)->pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return pd.DataFrame()
        df = pd.DataFrame(data,
                          columns=["timestamp","open","high","low","close","volume",
                                   "close_time","qav","trades","tb_bav","tb_qav","ignore"])
        df = df.iloc[:, :6]
        df.columns=["timestamp","open","high","low","close","volume"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df = df.apply(pd.to_numeric, errors="coerce")
        return df
    except Exception as e:
        print(f"[ERROR] get_price_data {symbol}-{interval}: {e}")
        return pd.DataFrame()

def add_features(df:pd.DataFrame)->pd.DataFrame:
    out=df.copy();close=out["close"];volume=out["volume"]
    out['price']=close;out['vol_ma20']=volume.rolling(20).mean()
    bb=ta.volatility.BollingerBands(close,20)
    out['bb_upper']=bb.bollinger_hband();out['bb_lower']=bb.bollinger_lband();out['bb_width']=(out['bb_upper']-out['bb_lower'])/(bb.bollinger_mavg()+1e-9)
    macd=ta.trend.MACD(close);out['macd']=macd.macd();out['macd_signal']=macd.macd_signal();out['macd_diff']=macd.macd_diff()
    cross=[(out['macd'].shift(1)<out['macd_signal'].shift(1))&(out['macd']>out['macd_signal']),
           (out['macd'].shift(1)>out['macd_signal'].shift(1))&(out['macd']<out['macd_signal'])]
    out['macd_cross']=np.select(cross,['bullish','bearish'],'neutral')
    ema_fast=ta.trend.ema_indicator(close,20);ema_slow=ta.trend.ema_indicator(close,50)
    out['trend']=np.select([ema_fast>ema_slow, ema_fast<ema_slow], ['uptrend','downtrend'],'sideway')
    for n in [14,28,50]:
        out[f'rsi_{n}']=ta.momentum.rsi(close,n);out[f'ema_{n}']=ta.trend.ema_indicator(close,n);out[f'dist_ema_{n}']=(close-out[f'ema_{n}'])/(out[f'ema_{n}']+1e-9)
    out['adx']=ta.trend.adx(out['high'],out['low'],close);out['atr']=ta.volatility.average_true_range(out['high'],out['low'],close,14)
    out['cmf']=ta.volume.chaikin_money_flow(out['high'],out['low'],close,volume,20)
    out.replace([np.inf,-np.inf],np.nan,inplace=True);out.bfill(inplace=True);out.ffill(inplace=True);out.fillna(0,inplace=True)
    return out

# --------------------------------------------------
# IO UTILS
# --------------------------------------------------

def write_json(path:str, data:dict):
    with open(path,'w') as f: json.dump(data,f,indent=2)

def send_discord_alert(payload:Dict):
    if not WEBHOOK_URL: return
    try:
        embeds = payload.get("embeds", [])
        if not embeds: return
        batch=[];chars=0
        def flush():
            nonlocal batch, chars
            if batch:
                requests.post(WEBHOOK_URL, json={"embeds": batch}, timeout=10).raise_for_status();time.sleep(1)
                batch=[];chars=0
        for embed in embeds:
            e_len=len(json.dumps(embed,ensure_ascii=False))
            if e_len>MAX_EMBED_CHARS:  # extreme (very unlikely with our sizes) – truncate description
                embed=embed.copy();embed['description']=embed.get('description','')[:1000]+" …"
                e_len=len(json.dumps(embed,ensure_ascii=False))
            if len(batch)>=MAX_EMBED_FIELDS or chars+e_len>MAX_EMBED_CHARS:
                flush()
            batch.append(embed);chars+=e_len
        flush()
    except Exception as exc:
        print(f"[ERROR] Discord alert failed: {exc}")
        if ERROR_WEBHOOK:
            try: requests.post(ERROR_WEBHOOK,json={"content":f"⚠️ ML_REPORT send error: {exc}"},timeout=10)
            except Exception: pass

def send_error_alert(msg:str):
    ts=datetime.utcnow().isoformat();open(os.path.join(LOG_DIR,"error_ml.log"),"a").write(f"{ts} | {msg}\n")
    if ERROR_WEBHOOK:
        try: requests.post(ERROR_WEBHOOK,json={"content":f"⚠️ ML_REPORT ERROR: {msg}"},timeout=10)
        except Exception: pass

def load_state():
    if not os.path.exists(STATE_FILE): return {}
    try:
        return json.load(open(STATE_FILE))
    except Exception: return {}

def save_state(d:dict):
    json.dump(d, open(STATE_FILE,'w'), indent=2)

def load_model(symbol:str,interval:str):
    try:
        clf=joblib.load(os.path.join(DATA_DIR,f"model_{symbol}_clf_{interval}.pkl"))
        reg=joblib.load(os.path.join(DATA_DIR,f"model_{symbol}_reg_{interval}.pkl"))
        meta=json.load(open(os.path.join(DATA_DIR,f"meta_{symbol}_{interval}.json")))
        return clf,reg,meta
    except Exception as e:
        send_error_alert(f"load_model {symbol}-{interval}: {e}")
        return None,None,None

def should_send_overview(state:dict)->bool:
    last=state.get("last_overview_timestamp",0)
    now=datetime.now(ZoneInfo("Asia/Bangkok"))
    for h in (8,20):
        t=now.replace(hour=h,minute=1,second=0,microsecond=0).timestamp()
        if now.timestamp()>=t and last<t:
            return True
    return False

# --------------------------------------------------
# CLASSIFY + ANALYZE
# --------------------------------------------------

def classify_level(pb:float, ps:float, pct:float, interval:str)->Dict[str,str]:
    dz={"1h":0.4,"4h":0.8,"1d":1.2}.get(interval,0.8)
    if pb>75: return {"level":"STRONG_BUY","sub_level":"STRONG_BUY"}
    if ps>75: return {"level":"PANIC_SELL","sub_level":"PANIC_SELL"}
    if pb>65: return {"level":"BUY","sub_level":"BUY"}
    if ps>65: return {"level":"SELL","sub_level":"SELL"}
    if pb>55: return {"level":"WEAK_BUY","sub_level":"WEAK_BUY"}
    if ps>55: return {"level":"WEAK_SELL","sub_level":"WEAK_SELL"}
    if abs(pct)<dz:
        sub="HOLD_NEUTRAL"
        if pb>ps+5: sub="HOLD_BULLISH"
        elif ps>pb+5: sub="HOLD_BEARISH"
        return {"level":"HOLD","sub_level":sub}
    sub="AVOID_UNCERTAIN"
    if pb>35 and ps>35: sub="AVOID_CONFLICT"
    return {"level":"AVOID","sub_level":sub}

def analyze(symbol:str, interval:str)->Optional[Dict]:
    clf,reg,meta=load_model(symbol,interval)
    if not clf: return None
    df=get_price_data(symbol,interval,API_LIMIT_PER_KLINE)
    if len(df)<100: return None
    feats=add_features(df)
    latest=feats.iloc[-1]
    X=pd.DataFrame([{f:latest.get(f,0) for f in meta['features']}])
    pb,ps=0.0,0.0
    try:
        probs=clf.predict_proba(X)[0];classes=clf.classes_.tolist()
        ps=probs[classes.index(0)]*100 if 0 in classes else 0
        pb=probs[classes.index(2)]*100 if 2 in classes else 0
    except Exception as e:
        send_error_alert(f"predict_proba {symbol}-{interval}: {e}")
    norm=float(reg.predict(X)[0])
    price=latest['close'];atr=latest['atr'] if latest['atr']>0 else price*0.01
    pct=norm*atr*100/price
    lv=classify_level(pb,ps,pct,interval)
    risk={"STRONG_BUY":1/3,"BUY":1/2.5,"WEAK_BUY":1/2,"HOLD":1/1.5,"AVOID":1/1.5,
          "WEAK_SELL":1/2,"SELL":1/2.5,"PANIC_SELL":1/3}.get(lv['level'],1/1.5)
    dir_=1 if pct>=0 else -1
    tp_pct=max(abs(pct),0.5);sl_pct=tp_pct*risk
    return {"symbol":symbol,"interval":interval,
            "prob_buy":round(pb,1),"prob_sell":round(ps,1),"pct":pct,
            "price":price,
            "tp":price*(1+dir_*tp_pct/100),"sl":price*(1-dir_*sl_pct/100),
            "level":lv['level'],"sub_level":lv['sub_level']}

# --------------------------------------------------
# FORMATTERS & ALERTS
# --------------------------------------------------

def fmt_price(p):
    if not np.isfinite(p): return "N/A"
    return f"{p:.8f}".rstrip('0').rstrip('.') if p<1 else f"{p:.4f}".rstrip('0').rstrip('.')

def fmt_pct(x):
    if not np.isfinite(x): return "N/A"
    return f"{x:+.4f}%" if abs(x)<0.01 and x!=0 else f"{x:+.2f}%"

def instant_alert(res:Dict, old_lv:Optional[str], old_sub:Optional[str]):
    lv,res_sub=res['level'],res['sub_level']
    if old_lv:
        if old_lv in ["HOLD","AVOID"] and old_sub:
            from_str=f"Từ **{get_sub_info(old_sub)['name']}** {get_sub_info(old_sub)['icon']}"
        else:
            oi=LEVEL_MAP.get(old_lv,{"name":"N/A","icon":"❓"});from_str=f"Từ **{oi['name']}** {oi['icon']}"
    else:
        from_str="Tín hiệu mới"
    if lv in ["HOLD","AVOID"]:
        si=get_sub_info(res_sub)
        to_str=f"chuyển sang **{si['name']}** {si['icon']}"
        desc=f"**Phân tích:** {si['desc']}"
        fields=[{"name":"Giá hiện tại","value":f"`{fmt_price(res['price'])}`","inline":True},
                {"name":"Dự đoán thay đổi","value":f"`{fmt_pct(res['pct'])}`","inline":True},
                {"name":"Xác suất Mua/Bán","value":f"`{res['prob_buy']:.1f}% / {res['prob_sell']:.1f}%`","inline":True}]
    else:
        li=LEVEL_MAP[lv];to_str=f"chuyển sang **{li['name']}** {li['icon']}"
        desc=f"Một cơ hội giao dịch **{li['name']}** tiềm năng đã xuất hiện."
        fields=[{"name":"Giá hiện tại","value":f"`{fmt_price(res['price'])}`","inline":True},
                {"name":"Dự đoán thay đổi","value":f"`{fmt_pct(res['pct'])}`","inline":True},
                {"name":"Xác suất Mua/Bán","value":f"`{res['prob_buy']:.1f}% / {res['prob_sell']:.1f}%`","inline":True},
                {"name":"Mục tiêu (TP)","value":f"`{fmt_price(res['tp'])}`","inline":True},
                {"name":"Cắt lỗ (SL)","value":f"`{fmt_price(res['sl'])}`","inline":True}]
    header=f"🔔 **AI Alert: {res['symbol']} ({res['interval']})**\n`{from_str} -> {to_str}`"
    embed={"title":header,"description":desc,"color":3447003,"fields":fields,
           "footer":{"text":f"AI Model v6.0 | {datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%Y-%m-%d %H:%M:%S')}"}}
    send_discord_alert({"embeds":[embed]})

# --------------------------------------------------
# SUMMARY REPORT
# --------------------------------------------------

def summary_report(results:List[Dict]):
    if not results: return
    counts={"BUY":0,"SELL":0,"HOLD_BULLISH":0,"HOLD_BEARISH":0}
    for r in results:
        if "BUY" in r['level']: counts["BUY"]+=1
        elif "SELL" in r['level']: counts["SELL"]+=1
        elif r['sub_level']=='HOLD_BULLISH': counts["HOLD_BULLISH"]+=1
        elif r['sub_level']=='HOLD_BEARISH': counts["HOLD_BEARISH"]+=1
    total=len(results)
    bull=counts['BUY']*2+counts['HOLD_BULLISH'];bear=counts['SELL']*2+counts['HOLD_BEARISH']
    status="TRUNG LẬP 🤔"
    if bull>bear*1.5 and bull/total>0.3: status="LẠC QUAN 📈"
    elif bear>bull*1.5 and bear/total>0.3: status="BI QUAN 📉"
    title=f"📊 Tổng quan Thị trường AI - {datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%H:%M (%d/%m/%Y)')}"
    desc=f"**Nhiệt kế thị trường: `{status}`**\n*Tổng hợp tín hiệu AI.*"
    embeds=[];embed={"title":title,"description":desc,"color":5814783,"fields":[],"footer":{"text":"AI Model v6.0"}}
    for sym,g in groupby(sorted(results,key=lambda x:x['symbol']),key=lambda x:x['symbol']):
        if len(embed['fields'])>=MAX_EMBED_FIELDS:
            embeds.append(embed);embed={"description":"*(tiếp)*","color":5814783,"fields":[]}
        lst=list(g);price=lst[0]['price']
        val = ""
        for r in sorted(lst, key=lambda x: INTERVALS.index(x['interval'])):
            info=get_sub_info(r['sub_level']) if r['level'] in ["HOLD","AVOID"] else LEVEL_MAP[r['level']]
            val+=f"`{r['interval']:<3}` {info['icon']} **{info['name']}** `{fmt_pct(r['pct'])}`\n"
        embed['fields'].append({"name":f"**{sym}** | Giá: `{fmt_price(price)}`","value":val,"inline":True})
    embeds.append(embed)
    send_discord_alert({"embeds":embeds})

# --------------------------------------------------
# MAIN LOOP
# --------------------------------------------------

def main():
    print("🧠 Bắt đầu phân tích AI …")
    state=load_state();results=[];now_utc=datetime.now(timezone.utc)
    for sym in SYMBOLS:
        for iv in INTERVALS:
            key=f"{sym}-{iv}"
            res=analyze(sym,iv)
            if not res:
                print(f"❌ {sym}-{iv} skip")
                continue
            write_json(os.path.join(LOG_DIR,f"{sym}_{iv}.json"),res)
            results.append(res)
            prev=state.get(key,{})
            if res['sub_level']!=prev.get('last_sub_level'):
                cd=COOLDOWN_BY_LEVEL.get(res['level'],3600)
                if now_utc.timestamp()-prev.get('last_alert_timestamp',0)>cd:
                    instant_alert(res,prev.get('last_level'),prev.get('last_sub_level'))
                    state[key]={"last_level":res['level'],"last_sub_level":res['sub_level'],"last_alert_timestamp":now_utc.timestamp()}
                else:
                    state.setdefault(key,{})
                    state[key].update({"last_level":res['level'],"last_sub_level":res['sub_level']})
    if should_send_overview(state):
        summary_report(results);state['last_overview_timestamp']=now_utc.timestamp()
    save_state(state)
    print("✅ Hoàn tất chu trình AI")

if __name__=="__main__":
    main()

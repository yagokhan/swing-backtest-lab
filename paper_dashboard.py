#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qswing Kağıt-Trade DASHBOARD — bağımsız web arayüzü.

Gösterir:
  • Güncel portföy (canlı FMP fiyatlarıyla K/Z) + kapanan işlemler
  • Son 22:45 tarama sonuçları (KIRILIM + İZLE)
  • Her açık/kapanan hisse için ETKİLEŞİMLİ mum grafiği (zoom/kaydır, zaman dilimi
    15m·30m·1h·2h·4h·1d) + AL/SAT işaretleri + giriş/stop/+2R hedef çizgileri

VERİYE/TRADE MANTIĞINA DOKUNMAZ — yalnız okur (~/.swing_paper.json, ~/.swing_lastscan*.json)
ve grafik için FMP günlük EOD + intraday çeker (yalnız gösterim; engine veri yolundan
bağımsız). Grafik kütüphanesi (Lightweight Charts) yerel servis edilir → CDN bağımlılığı yok.

Çalıştırma:
  python3 paper_dashboard.py [PORT]        # varsayılan 8061
  nohup python3 paper_dashboard.py >> swing2_out/dashboard.log 2>&1 &
"""
import json, os, sys, time, threading
import http.server
import urllib.parse
from datetime import datetime, time as _dtime
try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                       # zoneinfo/tzdata yoksa
    _ET = None

import pandas as pd

import paper_trader as pt
import swing2_backtest as s2

PORT = 8061
_BG, _CARD, _FG, _MUT = "#0d1218", "#161d27", "#e6edf3", "#8a95ad"
_GRN, _RED, _BLU, _AMB = "#16a34a", "#dc2626", "#3b82f6", "#f59e0b"

# vendor edilmiş TradingView Lightweight Charts (yerel servis → CDN bağımlılığı yok)
_LWC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_static", "lwc.js")
try:
    with open(_LWC_PATH, "rb") as _f:
        _LWC_JS = _f.read()
except Exception:
    _LWC_JS = b"console.error('lwc.js bulunamadi');"

# --- basit cache'ler (gereksiz ağ çağrısını önle) ---
_hist_cache = {}      # {symbol: (t_loaded, df)}
_quote_cache = {"t": 0, "data": {}}
_lock = threading.Lock()
HIST_TTL = 900        # 15 dk
QUOTE_TTL = 20        # sn


# ----------------------------- veri yardımcıları -----------------------------
def _fmp_key():
    return s2._fmp_key()


def _history(symbol):
    """Sembol için günlük OHLC (FMP EOD), 8 ay; 15 dk cache."""
    now = time.time()
    with _lock:
        c = _hist_cache.get(symbol)
        if c and now - c[0] < HIST_TTL:
            return c[1]
    key = _fmp_key()
    if not key:
        return None
    start = (pd.Timestamp.now().normalize() - pd.Timedelta(days=250)).strftime("%Y-%m-%d")
    frames = s2.fetch_daily_fmp([symbol], key, start, None, workers=1)
    df = frames.get(symbol)
    if df is not None and len(df):
        with _lock:
            _hist_cache[symbol] = (now, df)
    return df


_FMP_INTRA = "https://financialmodelingprep.com/stable/historical-chart/{interval}"
# zaman dilimi → FMP intraday aralığı + geriye dönük gün + (varsa) toplama katsayısı
TF_SPEC = {
    "15m": {"interval": "15min", "days": 12,  "intraday": True},
    "30m": {"interval": "30min", "days": 25,  "intraday": True},
    "1h":  {"interval": "1hour", "days": 70,  "intraday": True},
    "2h":  {"interval": "1hour", "days": 70,  "intraday": True, "agg": 2},
    "4h":  {"interval": "4hour", "days": 220, "intraday": True},
    "1d":  {"intraday": False},
}
TF_ORDER = ["15m", "30m", "1h", "2h", "4h", "1d"]
_tf_cache = {}        # {(symbol, tf): (t_loaded, df)}
TF_TTL = 60           # intraday 1 dk cache


def _fetch_intraday(symbol, interval, days):
    """FMP /stable intraday OHLCV → DatetimeIndex'li DataFrame (artan). Yalnız grafik
    GÖSTERİMİ için; trade/engine veri yolundan bağımsız (additive)."""
    key = _fmp_key()
    if not key:
        return None
    import urllib.request as _u, urllib.parse as _up
    frm = (pd.Timestamp.now().normalize() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    url = _FMP_INTRA.format(interval=interval) + "?" + _up.urlencode(
        {"symbol": symbol, "from": frm, "apikey": key})
    try:
        req = _u.Request(url, headers={"User-Agent": "swing2/1.0"})
        with _u.urlopen(req, timeout=20) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(raw, list) or not raw:
        return None
    rows = [(b["date"], b.get("open"), b.get("high"), b.get("low"),
             b.get("close"), b.get("volume") or 0) for b in raw]
    df = pd.DataFrame(rows, columns=["date", "Open", "High", "Low", "Close", "Volume"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df[["Open", "High", "Low", "Close", "Volume"]].astype(float)


def _agg_bars(df, n):
    """Gün-içi df'i her işlem günü içinde n-bar gruplarına topla (ör. 1h→2h)."""
    if df is None or not len(df):
        return df
    out = []
    for _, g in df.groupby(df.index.normalize()):
        g = g.sort_index()
        for i in range(0, len(g), n):
            c = g.iloc[i:i + n]
            out.append((c.index[0], c["Open"].iloc[0], c["High"].max(),
                        c["Low"].min(), c["Close"].iloc[-1], c["Volume"].sum()))
    a = pd.DataFrame(out, columns=["date", "Open", "High", "Low", "Close", "Volume"])
    return a.set_index("date").sort_index()


def _history_tf(symbol, tf):
    """Seçilen zaman dilimi için OHLCV df. tf='1d' → günlük EOD (mevcut cache);
    aksi halde FMP intraday (5 dk cache), 2h ise 1h'ten toplanır."""
    spec = TF_SPEC.get(tf)
    if not spec or not spec["intraday"]:
        return _history(symbol)            # günlük (15 dk cache)
    now = time.time()
    ck = (symbol, tf)
    with _lock:
        c = _tf_cache.get(ck)
        if c and now - c[0] < TF_TTL:
            return c[1]
    df = _fetch_intraday(symbol, spec["interval"], spec["days"])
    if df is not None and spec.get("agg"):
        df = _agg_bars(df, spec["agg"])
    if df is not None and len(df):
        with _lock:
            _tf_cache[ck] = (now, df)
    return df


def candles_json(symbol, tf):
    if tf not in TF_SPEC:
        tf = "1d"
    intraday = TF_SPEC[tf]["intraday"]
    df = _history_tf(symbol, tf)
    if df is None or not len(df):
        return {"symbol": symbol, "tf": tf, "candles": [], "error": "veri yok",
                "market": market_status()}
    df = df.tail(700)
    sma = df["Close"].rolling(50).mean()

    def tm(ts):
        ts = pd.Timestamp(ts)
        if intraday:                       # ET duvar-saatini UTC epoch gibi ver → eksen ET gösterir
            return int(ts.tz_localize("UTC").timestamp())
        return ts.strftime("%Y-%m-%d")

    candles = [{"time": tm(ts), "open": round(r.Open, 2), "high": round(r.High, 2),
                "low": round(r.Low, 2), "close": round(r.Close, 2)}
               for ts, r in df.iterrows()]
    sma_line = [{"time": tm(ts), "value": round(v, 2)} for ts, v in sma.items() if pd.notna(v)]

    def snap(date):
        if not date:
            return None
        pos = df.index.get_indexer([pd.Timestamp(date).normalize()], method="nearest")
        return tm(df.index[int(pos[0])]) if len(pos) and pos[0] >= 0 else None

    info = _pos_info(symbol)
    lines = {"entry": None, "stop": None, "target": None}
    markers = []
    if info:
        if info.get("entry") is not None:
            lines["entry"] = round(info["entry_fill"], 2)
        if info.get("stop") is not None:
            lines["stop"] = round(info["stop"], 2)
        if info.get("target") is not None:
            lines["target"] = round(info["target"], 2)
        bt = snap(info.get("entry_date"))
        if bt is not None:
            markers.append({"time": bt, "position": "belowBar", "color": _BLU,
                            "shape": "arrowUp", "text": "AL"})
        st = snap(info.get("exit_date"))
        if st is not None and info.get("exit") is not None:
            col = _GRN if info.get("outcome") == "TP" else _RED
            markers.append({"time": st, "position": "aboveBar", "color": col,
                            "shape": "arrowDown", "text": "SAT " + (info.get("outcome") or "")})
    markers.sort(key=lambda m: (m["time"] if isinstance(m["time"], int) else m["time"]))
    return {"symbol": symbol, "tf": tf, "intraday": intraday,
            "candles": candles, "sma": sma_line, "lines": lines, "markers": markers,
            "info": {"open": bool(info.get("open")) if info else None,
                     "outcome": (info.get("outcome") if info else None)},
            "market": market_status()}


def _live_quotes(symbols):
    """Açık pozisyonların anlık fiyatı; 45 sn cache."""
    now = time.time()
    with _lock:
        if now - _quote_cache["t"] < QUOTE_TTL and set(symbols) <= set(_quote_cache["data"]):
            return dict(_quote_cache["data"])
    key = _fmp_key()
    data = pt.quote_fmp(sorted(symbols), key) if (symbols and key) else {}
    with _lock:
        _quote_cache["t"] = now
        _quote_cache["data"] = data
    return data


# ----------------------------- piyasa durumu (ABD/ET) -----------------------------
# NYSE/NASDAQ tatilleri (tam kapalı günler) — gösterim doğruluğu için.
_MKT_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}


def market_status():
    """ABD borsası (ET) seans durumu. SADECE gösterim; trade mantığına dokunmaz.
    Döner: {state, label, dot, et, is_open}.
      state ∈ open | premarket | afterhours | closed | weekend | holiday
    """
    if _ET is None:
        return {"state": "unknown", "label": "Piyasa: bilinmiyor", "dot": "⚪",
                "et": "", "is_open": False}
    now = datetime.now(_ET)
    et_str = now.strftime("%H:%M ET")
    wd = now.weekday()                       # 0=Pzt … 6=Paz
    day = now.strftime("%Y-%m-%d")
    if wd >= 5:
        return {"state": "weekend", "label": "Piyasa KAPALI (hafta sonu)", "dot": "🔴",
                "et": et_str, "is_open": False}
    if day in _MKT_HOLIDAYS:
        return {"state": "holiday", "label": "Piyasa KAPALI (tatil)", "dot": "🔴",
                "et": et_str, "is_open": False}
    t = now.time()
    if _dtime(9, 30) <= t < _dtime(16, 0):
        return {"state": "open", "label": "Piyasa AÇIK", "dot": "🟢",
                "et": et_str, "is_open": True}
    if _dtime(4, 0) <= t < _dtime(9, 30):
        return {"state": "premarket", "label": "Açılış öncesi (pre-market)", "dot": "🟡",
                "et": et_str, "is_open": False}
    if _dtime(16, 0) <= t < _dtime(20, 0):
        return {"state": "afterhours", "label": "Kapanış sonrası (after-hours)", "dot": "🟡",
                "et": et_str, "is_open": False}
    return {"state": "closed", "label": "Piyasa KAPALI", "dot": "🔴",
            "et": et_str, "is_open": False}


# ----------------------------- portföy JSON -----------------------------
def _portfolio_payload(st, prices):
    """Tek portföyün JSON gövdesi (market/slippage hariç) — şampiyon + EMA için ortak."""
    positions, mkt_val, unreal = [], 0.0, 0.0
    for p in sorted(st["positions"], key=lambda x: x["symbol"]):
        ef = p.get("entry_fill", p["entry"])
        px = prices.get(p["symbol"])
        pnl = pct = None
        if px is not None:
            pnl = p["shares"] * (px - ef)
            pct = (px / ef - 1) * 100
            unreal += pnl
            mkt_val += p["shares"] * px
        else:
            mkt_val += p["shares"] * ef
        rec = {
            "symbol": p["symbol"], "entry": round(p["entry"], 2), "entry_fill": round(ef, 2),
            "shares": round(p["shares"], 3), "alloc": p.get("alloc"),
            "stop": (round(p["stop"], 2) if p.get("stop") is not None else None),
            "target": (round(p["target"], 2) if p.get("target") is not None else None),
            "price": (round(px, 2) if px is not None else None),
            "pnl": (round(pnl, 2) if pnl is not None else None),
            "pct": (round(pct, 2) if pct is not None else None),
            "entry_ts": p.get("entry_ts", p.get("entry_date")), "entry_date": p.get("entry_date"),
            "score": p.get("score")}
        if p.get("legs"):   # EMA varyantı: kalan bacaklar (çıkış planı)
            rem = [("8E" if l["rule"] == "ema8" else "21E") for l in p["legs"] if l["shares"] > 0]
            rec["exit_plan"] = "<" + "·".join(rem) if rem else "—"
        elif p.get("peak") is not None:   # şamdan varyantı: güncel trail seviyesi
            lvl = p.get("chand_stop")
            rec["exit_plan"] = (f"kapanış<${lvl:.2f}" if lvl is not None
                                else f"tepe−{pt.CHAND_MULT}×ATR")
        positions.append(rec)
    closed = []
    for r in st["closed"]:
        closed.append({
            "symbol": r["symbol"], "outcome": r.get("outcome"),
            "entry": r.get("entry"), "entry_fill": r.get("entry_fill", r.get("entry")),
            "exit": r.get("exit"), "shares": r.get("shares"),
            "pnl": r.get("pnl"), "pnl_pct": r.get("pnl_pct"),
            "entry_ts": r.get("entry_ts", r.get("entry_date")),
            "exit_ts": r.get("exit_ts", r.get("exit_date")),
            "entry_date": r.get("entry_date"), "exit_date": r.get("exit_date")})
    cash = st.get("cash", 0.0)
    equity = cash + mkt_val
    realized = sum((r.get("pnl") or 0.0) for r in st["closed"])
    start_cap = st.get("start_capital", pt.START_CAPITAL)
    return {
        "cash": round(cash, 2), "equity": round(equity, 2), "start_capital": start_cap,
        "unrealized": round(unreal, 2), "realized": round(realized, 2),
        "total_pl": round(equity - start_cap, 2),
        "total_pl_pct": round((equity - start_cap) / start_cap * 100, 2) if start_cap else 0.0,
        "n_open": len(positions), "n_closed": len(closed),
        "started": st.get("started"),
        "positions": positions, "closed": closed}


def portfolio_json():
    st = pt.load_state()
    ema_st = pt.load_state(pt.PAPER_EMA, variant="ema")
    ch_st = pt.load_state(pt.PAPER_CHAND, variant="chand")
    held = sorted(pt.held_symbols(st) | pt.held_symbols(ema_st) | pt.held_symbols(ch_st))
    prices = _live_quotes(held)
    out = _portfolio_payload(st, prices)
    out["market"] = market_status()
    out["slippage"] = pt._slip_note().strip(" ·") if pt.SLIPPAGE else ""
    out["ema"] = _portfolio_payload(ema_st, prices)
    out["chand"] = _portfolio_payload(ch_st, prices)
    return out


def scan_json():
    sd = pt.load_scan_data()
    if sd:
        return {"mode": "data", **sd}
    ls = pt.load_last_scan()
    if ls:
        return {"mode": "text", "asof": ls.get("asof"), "ts": ls.get("ts"), "text": ls.get("text", "")}
    return {"mode": "none"}


# ----------------------------- pozisyon meta (grafik overlay) -----------------------------
def _pos_info(symbol):
    """Sembolün giriş/stop/hedef + AL/SAT noktaları (önce açık, sonra kapanan)."""
    st = pt.load_state()
    for p in st["positions"]:
        if p["symbol"] == symbol:
            return {"entry": p["entry"], "entry_fill": p.get("entry_fill", p["entry"]),
                    "stop": p["stop"], "target": p["target"],
                    "entry_date": p.get("entry_date"), "exit_date": None, "exit": None,
                    "outcome": None, "open": True}
    last = None
    for r in st["closed"]:
        if r["symbol"] == symbol:
            last = r  # en son kapanan kaydı kullan
    if last:
        return {"entry": last.get("entry"), "entry_fill": last.get("entry_fill", last.get("entry")),
                "stop": None, "target": None,
                "entry_date": last.get("entry_date"), "exit_date": last.get("exit_date"),
                "exit": last.get("exit"), "outcome": last.get("outcome"), "open": False}
    return None


# ----------------------------- HTML sayfa -----------------------------
PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>qswing Kağıt-Trade Dashboard</title>
<style>
 /* ====== GECE MASASI — tek-ton grafit merdiveni (hue sabit, yalnız aydınlık kayar) ======
    derinlik stratejisi: SADECE kenarlık (düşük-opak rgba) + yüzey aydınlık basamağı; gölge yalnız modal.
    kimlik renkleri (altın/buz/fosfor) YALNIZ defter sırtı + yarış rayında — arayüz kromu nötr. */
 :root{
  --gece:#101216;          /* kanvas (s0) */
  --defter:#15181d;        /* defter yüzeyi (s1) */
  --defter2:#1b1f26;       /* satır hover / kontrol (s2) */
  --cam:#20252d;           /* modal / üst katman (s3) */
  --cizgi:rgba(174,188,214,.10);   /* standart kenar */
  --cizgi2:rgba(174,188,214,.20);  /* vurgu kenar */
  --murekkep:#e8ecf3;      /* birincil metin */
  --gumus:#a9b2c1;         /* ikincil */
  --sis:#69727f;           /* sönük etiket */
  --kar:#3ecf8e;   --kar-bg:rgba(62,207,142,.09);
  --zarar:#f07b7b; --zarar-bg:rgba(240,123,123,.09);
  --kehribar:#e8b04b; --kehribar-bg:rgba(232,176,75,.10);
  --altin:#d4a843;         /* 🏆 sırtı */
  --buz:#7eb3e3;           /* 📐 sırtı */
  --fosfor:#5ee0a0;        /* 💡 sırtı */
  --b4:4px;                /* boşluk taban birimi */
 }
 *{box-sizing:border-box}
 body{margin:0;background:var(--gece);color:var(--murekkep);
  font:14px/1.5 system-ui,"Segoe UI",Roboto,sans-serif;
  font-variant-numeric:tabular-nums}
 .muted{color:var(--sis)} .pos{color:var(--kar)} .neg{color:var(--zarar)}
 a{color:var(--gumus);text-decoration-color:var(--cizgi2)} a:hover{color:var(--murekkep)}

 /* ---- üst bant ---- */
 header{padding:14px 24px;border-bottom:1px solid var(--cizgi);
  display:flex;flex-wrap:wrap;gap:16px;align-items:baseline}
 h1{font-size:16px;font-weight:650;letter-spacing:-.01em;margin:0}
 h1 .alt{color:var(--sis);font-weight:500;font-size:12px;letter-spacing:.02em;margin-left:8px}
 #meta{font-size:12px}
 .refresh{margin-left:auto;display:flex;gap:8px;align-items:center}
 button{background:transparent;color:var(--gumus);border:1px solid var(--cizgi2);
  border-radius:7px;padding:6px 12px;font-size:12.5px;font-weight:550;cursor:pointer}
 button:hover{color:var(--murekkep);border-color:rgba(174,188,214,.34);background:var(--defter2)}

 /* seans ışığı */
 .mkt{display:inline-flex;align-items:center;gap:7px;padding:4px 11px;border-radius:999px;
  font-size:12px;font-weight:650;border:1px solid var(--cizgi2);color:var(--gumus)}
 .mkt .dot{width:8px;height:8px;border-radius:50%;display:inline-block;background:var(--sis)}
 .mkt.open{color:var(--kar);border-color:rgba(62,207,142,.4);background:var(--kar-bg)}
 .mkt.open .dot{background:var(--kar);animation:pulse 1.8s infinite}
 .mkt.closed{color:var(--zarar);border-color:rgba(240,123,123,.35);background:var(--zarar-bg)}
 .mkt.closed .dot{background:var(--zarar)}
 .mkt.ext{color:var(--kehribar);border-color:rgba(232,176,75,.35);background:var(--kehribar-bg)}
 .mkt.ext .dot{background:var(--kehribar)}
 @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(62,207,142,.55)}70%{box-shadow:0 0 0 7px rgba(62,207,142,0)}100%{box-shadow:0 0 0 0 rgba(62,207,142,0)}}

 .wrap{padding:28px 24px 56px;max-width:1240px;margin:0 auto}

 /* ---- YARIŞ RAYI: üç defterin özsermayesi tek bakışta ---- */
 .race{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:0 0 44px}
 .lane{background:var(--defter);border:1px solid var(--cizgi);border-radius:10px;
  padding:12px 16px 14px;border-top:2px solid var(--sis)}
 .lane.r0{border-top-color:var(--altin)} .lane.r1{border-top-color:var(--buz)} .lane.r2{border-top-color:var(--fosfor)}
 .lane .ln{font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--gumus)}
 .lane .ln .lead{color:var(--kehribar);letter-spacing:.04em;margin-left:6px;font-size:10px}
 .lane .lv{font-size:21px;font-weight:650;letter-spacing:-.01em;margin:6px 0 2px}
 .lane .lp{font-size:12.5px;font-weight:550}
 .lane .track{height:3px;background:var(--defter2);border-radius:2px;margin-top:10px;overflow:hidden}
 .lane .fill{height:100%;border-radius:2px;background:var(--sis)}
 .lane.r0 .fill{background:var(--altin)} .lane.r1 .fill{background:var(--buz)} .lane.r2 .fill{background:var(--fosfor)}

 /* ---- DEFTER: her portföy, kimlik renginde sırtı olan bir kayıt defteri ---- */
 .defter{background:var(--defter);border:1px solid var(--cizgi);border-left:3px solid var(--sis);
  border-radius:10px;padding:18px 20px 20px;margin:0 0 28px}
 .defter.d-champ{border-left-color:var(--altin)}
 .defter.d-ema{border-left-color:var(--buz)}
 .defter.d-chand{border-left-color:var(--fosfor)}
 .defter.d-scan{border-left-color:var(--cizgi2)}
 .defter h2{font-size:13px;font-weight:650;letter-spacing:.02em;margin:0 0 4px}
 .defter .kural{display:block;font-size:11.5px;font-weight:450;color:var(--sis);
  letter-spacing:.01em;margin:0 0 16px}
 .defter .kural a{color:var(--sis)}
 h3.alt{font-size:10.5px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;
  color:var(--sis);margin:20px 0 8px}

 /* KPI bandı: kart grid'i değil, ayraçlı cetvel */
 .kpis{display:flex;flex-wrap:wrap;background:var(--gece);border:1px solid var(--cizgi);
  border-radius:8px;padding:4px 0;margin:0 0 4px}
 .kpi{padding:8px 18px;border-right:1px solid var(--cizgi);min-width:128px}
 .kpi:last-child{border-right:none}
 .kpi .v{font-size:17px;font-weight:650;letter-spacing:-.01em}
 .kpi .l{color:var(--sis);font-size:10.5px;font-weight:550;letter-spacing:.07em;text-transform:uppercase;margin-top:2px}

 /* tablolar: defterin içinde çerçevesiz; satırlar ince çizgiyle */
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--cizgi);white-space:nowrap}
 th:first-child,td:first-child{text-align:left}
 th{color:var(--sis);font-weight:600;font-size:10.5px;letter-spacing:.07em;text-transform:uppercase}
 tr:last-child td{border-bottom:none}
 .sym{font-weight:650;letter-spacing:.01em}
 tbody tr.clk{cursor:pointer} tbody tr.clk:hover{background:var(--defter2)}
 .badge{display:inline-block;padding:1px 8px;border-radius:5px;font-size:10.5px;font-weight:650;letter-spacing:.04em}
 .b-buy{background:var(--kar-bg);color:var(--kar)} .b-tp{background:var(--kar-bg);color:var(--kar)}
 .b-stop{background:var(--zarar-bg);color:var(--zarar)} .b-watch{background:var(--kehribar-bg);color:var(--kehribar)}

 .scanbox{white-space:pre-wrap;word-break:break-word;font-size:13px}
 .ipucu{color:var(--sis);font-size:12px;margin-top:24px}

 /* ---- grafik modalı (s3) ---- */
 .modal{position:fixed;inset:0;background:rgba(8,9,12,.84);display:none;
  align-items:center;justify-content:center;z-index:50;padding:14px}
 .modal.open{display:flex}
 .modal-inner{background:var(--cam);border:1px solid var(--cizgi2);border-radius:12px;padding:14px;
  max-width:1180px;width:100%;max-height:calc(100vh - 28px);display:flex;flex-direction:column;
  overflow:hidden;box-shadow:0 18px 48px rgba(0,0,0,.5)}
 .modal-head{display:flex;justify-content:space-between;align-items:center;gap:12px;
  margin-bottom:10px;flex-wrap:wrap;flex:0 0 auto}
 #chart{width:100%;flex:1 1 auto;min-height:240px}
 .chartnote{margin-top:6px;font-size:12px;flex:0 0 auto}
 .mktmini{font-size:12px;font-weight:600}
 .tfbar{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}
 .tfbar .tf{padding:5px 11px;font-size:12px;font-weight:600;background:transparent;
  color:var(--sis);border:1px solid var(--cizgi);border-radius:7px;cursor:pointer}
 .tfbar .tf:hover{border-color:var(--cizgi2);color:var(--murekkep)}
 .tfbar .tf.on{background:var(--defter2);color:var(--murekkep);border-color:var(--cizgi2)}
 .x{cursor:pointer;border:1px solid var(--cizgi2);border-radius:7px;padding:5px 11px;
  background:transparent;color:var(--gumus)} .x:hover{color:var(--murekkep);background:var(--defter2)}
</style></head><body>
<header>
  <h1>qswing Seans Masası<span class="alt">kağıt-trade defterleri</span></h1>
  <span class="mkt" id="mkt" title="ABD borsası seans durumu (ET)">…</span>
  <span class="muted" id="meta">yükleniyor…</span>
  <div class="refresh">
    <span class="muted" id="upd"></span>
    <button onclick="window.open('/rapor','_blank')" title="Deney iterasyonu: canlı baz vs önerilen varyant — ekonomist gözüyle detaylı karşılaştırma">📊 Rapor</button>
    <button onclick="loadAll()">↻ Yenile</button>
  </div>
</header>
<div class="wrap">
  <div class="race" id="race"></div>

  <section class="defter d-champ">
    <h2>🏆 ATR-trail (şampiyon)</h2>
    <span class="kural">giriş: 40g kırılım · çıkış: %50 kısmi @+2R · +2R hedef · +1R sonrası kapanış−2.5×ATR trail</span>
    <div class="kpis" id="kpis"></div>
    <h3 class="alt">Açık Pozisyonlar</h3><div id="open"></div>
    <h3 class="alt">Kapanan İşlemler</h3><div id="closed"></div>
  </section>

  <section class="defter d-ema">
    <h2>📐 8/21-EMA varyantı</h2>
    <span class="kural">girişler şampiyonla aynı · çıkış: %50 kapanış&lt;8-EMA · kalan %50 kapanış&lt;21-EMA</span>
    <div class="kpis" id="kpisE"></div>
    <h3 class="alt">Açık Pozisyonlar</h3><div id="openE"></div>
    <h3 class="alt">Kapanan İşlemler</h3><div id="closedE"></div>
  </section>

  <section class="defter d-chand">
    <h2>💡 63G-Şamdan varyantı</h2>
    <span class="kural">giriş: yalnız 63g (çeyreklik) tepe kıranlar · çıkış: tüm pozisyon, kapanış&lt;tepe−3.25×ATR · kısmi/hedef yok · <a href="/rapor" target="_blank">detaylı rapor</a></span>
    <div class="kpis" id="kpisC"></div>
    <h3 class="alt">Açık Pozisyonlar</h3><div id="openC"></div>
    <h3 class="alt">Kapanan İşlemler</h3><div id="closedC"></div>
  </section>

  <section class="defter d-scan">
    <h2>Son Tarama</h2>
    <span class="kural">22:45 (15:45 ET) qswing kırılım taraması — yapısal veri varsa tablo, yoksa mesaj metni</span>
    <div id="scan" class="scanbox">…</div>
  </section>

  <p class="ipucu">Bir <b>açık</b> ya da <b>kapanan</b> pozisyon satırına tıkla → <b>etkileşimli</b> mum grafiği açılır: tekerlekle <b>zoom</b>, sürükleyerek <b>kaydır</b>, üstten <b>zaman dilimi</b> (15m·30m·1h·2h·4h·1d) seç. <span class="pos">AL ▲</span> / <span class="neg">SAT ▼</span> + giriş/stop/+2R çizgileri işaretli.</p>
</div>
<div class="modal" id="modal" onclick="if(event.target===this)closeChart()">
  <div class="modal-inner">
    <div class="modal-head">
      <div><b id="modalTitle">—</b> <span class="mktmini" id="chartMkt"></span> <span class="mktmini muted" id="chartCd" title="otomatik veri tazelemeye kalan süre"></span></div>
      <div class="tfbar" id="tfbar"></div>
      <button class="x" onclick="closeChart()">✕ Kapat</button>
    </div>
    <div id="chart"></div>
    <div class="muted chartnote" id="chartNote"></div>
  </div>
</div>
<script src="/static/lwc.js"></script>
<script>
const $=id=>document.getElementById(id);
const f=(v,d=2)=>v==null?'—':Number(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const cls=v=>v==null?'':(v>=0?'pos':'neg');
const sign=v=>v==null?'—':(v>=0?'+':'')+f(v);

async function loadAll(){
  const [p,s]=await Promise.all([fetch('/api/portfolio').then(r=>r.json()),fetch('/api/scan').then(r=>r.json())]);
  renderRace(p);
  renderKpis(p,'kpis',p.ema); renderOpen(p,'open'); renderClosed(p,'closed');
  if(p.ema){renderKpis(p.ema,'kpisE',p); renderOpen(p.ema,'openE',true); renderClosed(p.ema,'closedE');}
  if(p.chand){renderKpis(p.chand,'kpisC',p); renderOpen(p.chand,'openC',true); renderClosed(p.chand,'closedC');}
  renderScan(s); renderMkt(p.market);
  $('meta').textContent=`başlangıç ${p.started||'?'} · ${p.slippage||'slippage kapalı'}`;
  $('upd').textContent='güncellendi '+new Date().toLocaleTimeString('tr-TR');
}
function renderRace(p){
  // yarış rayı: üç defterin özsermayesi tek bakışta (salt görüntü — /api/portfolio verisinden)
  const L=[['🏆 ATR-trail',p,'r0'],['📐 8/21-EMA',p.ema,'r1'],['💡 63G-Şamdan',p.chand,'r2']].filter(x=>x[1]&&x[1].equity!=null);
  if(!L.length){$('race').innerHTML='';return;}
  const eqs=L.map(x=>x[1].equity),mx=Math.max(...eqs),mn=Math.min(...eqs);
  $('race').innerHTML=L.map(([n,d,c])=>{
    const w=(mx===mn)?100:Math.round(8+92*(d.equity-mn)/(mx-mn));
    const lead=(d.equity===mx&&mx!==mn)?'<span class="lead">önde</span>':'';
    return `<div class="lane ${c}"><div class="ln">${n}${lead}</div>
     <div class="lv">$${f(d.equity)}</div>
     <div class="lp ${cls(d.total_pl)}">${sign(d.total_pl)}$ · ${sign(d.total_pl_pct)}% · ${d.n_open} açık</div>
     <div class="track"><div class="fill" style="width:${w}%"></div></div></div>`;
  }).join('');
}
function renderMkt(m){
  const el=$('mkt'); if(!m){el.textContent='';return;}
  const cl=m.is_open?'open':(m.state==='premarket'||m.state==='afterhours'?'ext':'closed');
  el.className='mkt '+cl;
  el.innerHTML=`<span class="dot"></span>${m.label}${m.et?' · '+m.et:''}`;
}
function renderKpis(p,el,other){
  const k=[['Özsermaye','$'+f(p.equity)],['Genel K/Z',sign(p.total_pl)+'$ ('+sign(p.total_pl_pct)+'%)',cls(p.total_pl)],
   ['Gerçekleşmemiş',sign(p.unrealized)+'$',cls(p.unrealized)],['Gerçekleşen',sign(p.realized)+'$',cls(p.realized)],
   ['Nakit','$'+f(p.cash)],['Pozisyon',p.n_open+' açık · '+p.n_closed+' kapanan']];
  if(other&&other.equity!=null){const d=p.equity-other.equity;
   k.push(['⚖️ Fark (diğerine göre)',sign(d)+'$',cls(d)]);}
  $(el).innerHTML=k.map(x=>`<div class="kpi"><div class="v ${x[2]||''}">${x[1]}</div><div class="l">${x[0]}</div></div>`).join('');
}
function renderOpen(p,el,ema){
  if(!p.positions.length){$(el).innerHTML='<p class="muted">Açık pozisyon yok.</p>';return;}
  const exitH=ema?'<th>Çıkış planı</th>':'<th>Stop</th><th>Hedef</th>';
  let h='<table><tr><th>Hisse</th><th>Fiyat</th><th>Giriş</th><th>Adet</th><th>K/Z</th><th>%</th>'+exitH+'<th>Giriş zamanı</th></tr>';
  for(const x of p.positions){
   const exitC=ema?`<td>${x.exit_plan||'—'}</td>`:`<td>${f(x.stop)}</td><td>${f(x.target)}</td>`;
   h+=`<tr class="clk" onclick="openChart('${x.symbol}')"><td class="sym">${x.symbol}</td><td>${f(x.price)}</td><td>${f(x.entry_fill)}</td>
   <td>${f(x.shares,3)}</td><td class="${cls(x.pnl)}">${sign(x.pnl)}$</td><td class="${cls(x.pct)}">${sign(x.pct)}%</td>
   ${exitC}<td class="muted">${x.entry_ts||''}</td></tr>`;}
  $(el).innerHTML=h+'</table>';
}
function renderClosed(p,el){
  if(!p.closed.length){$(el).innerHTML='<p class="muted">Kapanan işlem yok.</p>';return;}
  let h='<table><tr><th>Hisse</th><th>Sonuç</th><th>Giriş</th><th>Çıkış</th><th>K/Z</th><th>%</th><th>Giriş→Çıkış</th></tr>';
  for(const x of p.closed){const b=(x.outcome==='TP'||(x.pnl!=null&&x.pnl>=0))?'b-tp':'b-stop';
   h+=`<tr class="clk" onclick="openChart('${x.symbol}')"><td class="sym">${x.symbol}</td><td><span class="badge ${b}">${x.outcome||''}</span></td>
   <td>${f(x.entry_fill)}</td><td>${f(x.exit)}</td><td class="${cls(x.pnl)}">${sign(x.pnl)}$</td>
   <td class="${cls(x.pnl_pct)}">${sign(x.pnl_pct)}%</td><td class="muted">${x.entry_date} → ${x.exit_date}</td></tr>`;}
  $(el).innerHTML=h+'</table>';
}
function renderScan(s){
  if(s.mode==='none'){$('scan').innerHTML='<span class="muted">Henüz kayıtlı tarama yok.</span>';return;}
  if(s.mode==='text'){$('scan').innerHTML=`<div class="muted">🕒 ${s.ts} (asof ${s.asof})</div><div style="margin-top:8px">${s.text}</div>`;return;}
  const rows=(arr,watch)=>arr.map(c=>`<tr><td class="sym">${c.symbol}</td>
    <td>${watch?'<span class="badge b-watch">İZLE</span>':'<span class="badge b-buy">KIRILIM</span>'}</td>
    <td>${c.score??'—'}</td><td>${f(c.entry)}</td><td>${f(c.stop)}</td><td>${f(c.partial_target)}</td>
    <td>${c.risk_pct==null?'—':f(c.risk_pct)+'%'}</td><td>${c.rs==null?'—':'+'+f(c.rs,0)}</td></tr>`).join('');
  let h=`<div class="muted" style="margin-bottom:8px">🕒 ${s.ts} (asof ${s.asof}) · rejim ${s.regime_open?'🟢 AÇIK':'🔴 KAPALI'}</div>`;
  h+='<table style="white-space:normal"><tr><th>Hisse</th><th>Tip</th><th>Puan</th><th>Giriş</th><th>Stop</th><th>+2R</th><th>Risk</th><th>RS</th></tr>';
  h+=rows(s.buyable||[],false)+rows(s.watch||[],true)+'</table>';
  $('scan').innerHTML=h; $('scan').classList.remove('scanbox');
}
const TFS=['15m','30m','1h','2h','4h','1d'];
let _chart=null,_series=null,_sma=null,_plines=[],_cursym=null,_curtf='1d',_chartTimer=null,_cdTimer=null,_nextAt=0;
function buildTfbar(){
  $('tfbar').innerHTML=TFS.map(tf=>`<button class="tf${tf===_curtf?' on':''}" onclick="setTf('${tf}')">${tf}</button>`).join('');
}
function setTf(tf){_curtf=tf;buildTfbar();drawChart();}
function openChart(sym){
  _cursym=sym;_curtf='1d';
  $('modal').classList.add('open');
  buildTfbar();
  ensureChart();
  drawChart();
  if(_chartTimer)clearInterval(_chartTimer);
  _nextAt=Date.now()+60000;
  _chartTimer=setInterval(()=>{_nextAt=Date.now()+60000;drawChart(true);},60000);   // açıkken 60 sn'de bir tazele (zoom korunur)
  if(_cdTimer)clearInterval(_cdTimer);
  _cdTimer=setInterval(tickCd,1000); tickCd();          // geri sayım rozeti (↻ Ns)
}
function tickCd(){
  const s=Math.max(0,Math.ceil((_nextAt-Date.now())/1000));
  $('chartCd').textContent='↻ '+s+'s';
}
function closeChart(){
  $('modal').classList.remove('open');
  if(_chartTimer){clearInterval(_chartTimer);_chartTimer=null;}
  if(_cdTimer){clearInterval(_cdTimer);_cdTimer=null;}
}
function ensureChart(){
  if(_chart)return;
  const el=$('chart');el.innerHTML='';
  _chart=LightweightCharts.createChart(el,{
    width:el.clientWidth,height:el.clientHeight,autoSize:true,
    layout:{background:{color:'#20252d'},textColor:'#e8ecf3',fontSize:12},
    grid:{vertLines:{color:'rgba(174,188,214,.06)'},horzLines:{color:'rgba(174,188,214,.06)'}},
    timeScale:{timeVisible:true,secondsVisible:false,borderColor:'rgba(174,188,214,.20)'},
    rightPriceScale:{borderColor:'rgba(174,188,214,.20)'},
    crosshair:{mode:0}});
  _series=_chart.addCandlestickSeries({upColor:'#16a34a',downColor:'#dc2626',
    wickUpColor:'#16a34a',wickDownColor:'#dc2626',borderVisible:false});
  _sma=_chart.addLineSeries({color:'#f59e0b',lineWidth:1,priceLineVisible:false,lastValueVisible:false});
  window.addEventListener('resize',()=>{if(_chart)_chart.applyOptions({width:el.clientWidth,height:el.clientHeight});});
}
async function drawChart(keep){
  const sym=_cursym,tf=_curtf;
  $('modalTitle').textContent=sym+' · '+tf;
  if(!keep)$('chartNote').textContent='yükleniyor…';
  let d;
  try{d=await fetch(`/api/candles/${sym}?tf=${tf}`).then(r=>r.json());}
  catch(e){$('chartNote').textContent='grafik yüklenemedi';return;}
  if(sym!==_cursym||tf!==_curtf)return;   // arada başka tıklama olduysa yoksay
  if(d.market){const m=d.market;$('chartMkt').textContent=m.dot+' '+m.label+(m.et?' · '+m.et:'');
    $('chartMkt').style.color=m.is_open?'#7ee2a8':(m.state==='premarket'||m.state==='afterhours'?'#ffd591':'#ffa3ab');}
  ensureChart();
  _series.setData(d.candles||[]);
  _sma.setData(d.sma||[]);
  _plines.forEach(pl=>{try{_series.removePriceLine(pl);}catch(e){}});_plines=[];
  const L=d.lines||{};
  const addL=(p,c,t)=>{if(p!=null)_plines.push(_series.createPriceLine({price:p,color:c,lineWidth:1,lineStyle:2,axisLabelVisible:true,title:t}));};
  addL(L.entry,'#3b82f6','Giriş');addL(L.stop,'#dc2626','Stop');addL(L.target,'#16a34a','+2R');
  _series.setMarkers(d.markers||[]);
  if(!keep)_chart.timeScale().fitContent();   // otomatik tazelemede zoom/kaydırma korunur
  if(d.error){$('chartNote').textContent='⚠️ '+d.error;}
  else{$('chartNote').textContent=(d.intraday?'🕒 saatler ET · ':'')+((d.candles||[]).length)+' bar · tekerlek=zoom, sürükle=kaydır · SMA50 (turuncu) · giriş/stop/+2R çizgileri · AL▲/SAT▼';}
}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeChart();});
loadAll();
setInterval(loadAll,30000);   // piyasa durumu + fiyatlar otomatik tazelensin
</script></body></html>"""


# ----------------------------- HTTP -----------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/" or path == "/index.html":
                self._send(200, PAGE, "text/html; charset=utf-8")
            elif path == "/api/portfolio":
                self._send(200, json.dumps(portfolio_json(), ensure_ascii=False), "application/json")
            elif path == "/api/scan":
                self._send(200, json.dumps(scan_json(), ensure_ascii=False), "application/json")
            elif path == "/static/lwc.js":
                self._send(200, _LWC_JS, "application/javascript; charset=utf-8")
            elif path == "/rapor":
                # Strateji karşılaştırma raporu (statik, gen_exp_report.py üretir) — salt-okur
                rp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_static", "exp_report.html")
                if os.path.exists(rp):
                    with open(rp, "rb") as fh:
                        self._send(200, fh.read(), "text/html; charset=utf-8")
                else:
                    self._send(404, "Rapor henüz üretilmedi (python3 gen_exp_report.py)", "text/plain; charset=utf-8")
            elif path.startswith("/api/candles/"):
                sym = path[len("/api/candles/"):].upper()
                q = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                tf = (q.get("tf", ["1d"])[0])
                self._send(200, json.dumps(candles_json(sym, tf), ensure_ascii=False), "application/json")
            else:
                self._send(404, "yok", "text/plain; charset=utf-8")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send(500, f"hata: {e}", "text/plain; charset=utf-8")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Dashboard hazır → http://localhost:{port}  (Ctrl+C ile dur)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()

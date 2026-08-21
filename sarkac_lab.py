"""sarkac_lab.py — 🔔 SARKAÇ-14: QQQ'nun RSI salınımıyla TQQQ al-sat.

YÖNTEM
------
Sinyal **QQQ** üzerinden, işlem **TQQQ** üzerinde:

    RSI(QQQ, 14) <= 30  →  TQQQ AL      (aşırı satım)
    RSI(QQQ, 14) >= 70  →  TQQQ SAT     (aşırı alım)

Aradaki barlarda hiçbir şey yapılmaz. Pozisyon ya tam açık ya tamamen nakit;
kaldıraç TQQQ'nun kendi 3× yapısından gelir, ayrıca kaldıraç kullanılmaz.

Kaynak: BalintDavid "RSI Swing Indicator" (Pine v4, MPL-2.0). Gösterge fiyat
üstüne HH/LH/HL/LL salınım çizgileri çiziyor; bu labdaki alım-satım kuralı o
göstergenin **durum makinesinden** türetildi (aşağıya bak). Göstergenin çizim
kısmı (label/line) alım-satımı etkilemez, o yüzden taşınmadı.

PINE DURUM MAKİNESİ (birebir korundu)
-------------------------------------
Orijinal kodda `laststate` son aşırılığı tutar (1=aşırı alım, 2=aşırı satım) ve
YENİ salınım yalnız DURUM DEĞİŞİMİNDE üretilir:

    if (laststate == 2 and isOverbought)   → yeni tepe (HH/LH)
    if (laststate == 1 and isOversold)     → yeni dip  (HL/LL)

Bu kontroller durum güncellenmeden ÖNCE çalışır, yani ÖNCEKİ barın durumuna
bakar. Sonuç: histerezis. Arka arkaya gelen aşırı-satım barları tekrar sinyal
üretmez; bir sonraki sinyal ancak karşı uca değince gelir. Alım-satıma çevirisi
doğal olarak alternans: al → sat → al → sat.

İLK İŞLEM FARKI (ölçülüyor, varsayılmıyor)
------------------------------------------
Pine'da `laststate` 0'dan başlar. Katı okumada ilk aşırı-satım ALIM ÜRETMEZ
(çünkü `laststate == 1` şartı sağlanmaz); ilk alım ancak OS→OB→OS sırasından
sonra gelir. Alım-satım niyetine daha yakın okuma ise "nakitken ilk aşırı satım
al" der. İkisi de kuruldu: `start_mode="pine"` (katı) / `"flat"` (varsayılan).

ZAMANLAMA
---------
RSI kapanışta bilinir, işlem kapanışta yapılır (Qulla-21'in 15:45 kapanış
konvansiyonuyla aynı). Sinyal barının kapanışından doldurulur; gelecek bar
kullanılmaz.

CANLI SİSTEME DOKUNMAZ. Kendi verisini çeker, kendi cache'ini kullanır.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/gokhan")
import pit_universe as pu

CACHE = "/home/gokhan/swing2_cache/sarkac_data.pkl"
OUT_JSON = "/home/gokhan/swing2_out/sarkac_results.json"

SIGNAL_SYM = "QQQ"        # göstergenin izlendiği enstrüman
TRADE_SYM = "TQQQ"        # alınıp satılan enstrüman
DATA_START = "2006-01-01"  # RSI ısınması için bol tampon (TQQQ 2010-02-11'de doğdu)
DATA_END = "2026-08-20"

# maliyet varsayımları — swing2_backtest.Config ile hizalı
COMMISSION = 1.0
ENTRY_SLIP_BPS = 8.0
EXIT_SLIP_BPS = 8.0
INITIAL_CAPITAL = 10_000.0


# =========================================================================
# RSI — TradingView ta.rsi ile birebir
# =========================================================================
def rma(x: pd.Series, n: int) -> pd.Series:
    """TradingView ta.rma (Wilder yumuşatması).

    swing2_backtest.rsi() saf ewm kullanıyor (SMA tohumu YOK); TradingView ilk
    n değerin SMA'sıyla tohumlar. Fark üstel olarak sönümlenir ve ~100 bar sonra
    ölçülemez hâle gelir, ama gösterge birebir istendiği için burada TV yolu
    uygulanır. İkisinin yakınsaması --rsi-check ile doğrulanabilir."""
    x = x.astype(float)
    vals = x.to_numpy()
    out = np.full(len(vals), np.nan)
    # BAŞTAKİ NaN'LARI ATLA. close.diff() ilk elemanı NaN verir; tohumu doğrudan
    # vals[:n]'den almak 14 değişim yerine 13'ünün ortalamasını alıp sonucu bir
    # bar erken yerleştirirdi. TradingView rma'sı ilk n GEÇERLİ değerle tohumlar.
    valid = np.flatnonzero(~np.isnan(vals))
    if len(valid) < n:
        return pd.Series(out, index=x.index)
    s = valid[0]                     # ilk geçerli konum
    seed_end = s + n                 # tohum penceresi: [s, s+n)
    if seed_end > len(vals):
        return pd.Series(out, index=x.index)
    out[seed_end - 1] = np.nanmean(vals[s:seed_end])
    a = 1.0 / n
    for i in range(seed_end, len(vals)):
        prev = out[i - 1]
        v = vals[i]
        out[i] = prev if np.isnan(v) else (a * v + (1 - a) * prev)
    return pd.Series(out, index=x.index)


def rsi_tv(close: pd.Series, n: int = 14) -> pd.Series:
    """TradingView: rsi = 100 − 100/(1 + rma(gain,n)/rma(loss,n))"""
    d = close.astype(float).diff()
    up = rma(d.clip(lower=0.0), n)
    dn = rma((-d).clip(lower=0.0), n)
    rs = up / dn.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    out[(dn == 0) & (up > 0)] = 100.0        # sıfır kayıp → RSI 100
    return out


def ema(x: pd.Series, n: int) -> pd.Series:
    """Üstel hareketli ortalama (TradingView ta.ema ile aynı: adjust=False)."""
    return x.astype(float).ewm(span=n, adjust=False).mean()


# =========================================================================
# PINE DURUM MAKİNESİ
# =========================================================================
def swing_states(rsi: pd.Series, ob: float = 70.0, os_: float = 30.0) -> pd.DataFrame:
    """Pine `laststate` makinesini birebir yürüt.

    Dönen kolonlar:
      state      : bar SONUNDAKİ durum (0 nötr · 1 aşırı alım · 2 aşırı satım)
      to_ob      : bu barda aşırı-satım→aşırı-alım geçişi (yeni tepe) oldu mu
      to_os      : bu barda aşırı-alım→aşırı-satım geçişi (yeni dip) oldu mu
    Geçişler durum güncellenmeden ÖNCEKİ değere bakar — Pine'daki sırayla aynı."""
    r = rsi.to_numpy(dtype=float)
    n = len(r)
    state = np.zeros(n, dtype=np.int8)
    to_ob = np.zeros(n, dtype=bool)
    to_os = np.zeros(n, dtype=bool)
    last = 0
    for i in range(n):
        v = r[i]
        if np.isnan(v):
            state[i] = last
            continue
        is_ob = v >= ob
        is_os = v <= os_
        if last == 2 and is_ob:
            to_ob[i] = True
        if last == 1 and is_os:
            to_os[i] = True
        if is_ob:
            last = 1
        elif is_os:
            last = 2
        state[i] = last
    return pd.DataFrame({"state": state, "to_ob": to_ob, "to_os": to_os}, index=rsi.index)


def exit_signals(rsi: pd.Series, ob=70.0, os_=30.0) -> pd.DataFrame:
    """ALTERNATİF zamanlama: bölgeye GİRERKEN değil, bölgeden ÇIKARKEN.

      AL  : RSI aşırı-satım bölgesindeyken YUKARI keserse (30'un üstüne dönerse)
      SAT : RSI aşırı-alım bölgesindeyken AŞAĞI keserse (70'in altına dönerse)

    Pine göstergesi bunu YAPMAZ — orada salınım bölgeye GİRİŞTE başlar. Ama
    "düşen bıçağı yakalama" sorununa doğal cevap budur: dip teyit edilene kadar
    beklenir. Karşılaştırma için kuruldu, varsayılan DEĞİL.
    Ölçüldü (2010-2026): CAGR %16,4 vs %23,6 — daha kötü, üstelik 2022'yi de
    kurtarmıyor (RSI Ocak 2022'de 30'un üstüne hemen döndü, teyit yanlış çıktı)."""
    r = rsi.to_numpy(dtype=float)
    n = len(r)
    buy = np.zeros(n, dtype=bool)
    sell = np.zeros(n, dtype=bool)
    in_os = in_ob = False
    long_ = False          # ALTERNANS: touch modundaki durum makinesiyle aynı disiplin —
    for i in range(n):     # pozisyondayken AL, nakitteyken SAT üretilmez; yoksa grafikte
        v = r[i]           # işleme dönüşmeyen hayalet işaretler çıkar
        if np.isnan(v):
            continue
        if v <= os_:
            in_os = True
        elif in_os:                       # bölgeden yukarı çıktı → AL
            in_os = False
            if not long_:
                buy[i] = True; long_ = True
        if v >= ob:
            in_ob = True
        elif in_ob:                       # bölgeden aşağı indi → SAT
            in_ob = False
            if long_:
                sell[i] = True; long_ = False
    return pd.DataFrame({"buy": buy, "sell": sell}, index=rsi.index)


def signals(rsi: pd.Series, ob=70.0, os_=30.0, start_mode="flat",
            signal_mode="touch") -> pd.DataFrame:
    """Al/sat sinyalleri.

    signal_mode="touch" : Pine göstergesinin KENDİSİ — bölgeye İLK TEMASTA
                          (RSI <= 30 olduğu ilk bar AL, >= 70 olduğu ilk bar SAT).
                          Histerezisli: arka arkaya aşırı barlar tekrar tetiklemez.
    signal_mode="exit"  : bölgeden ÇIKIŞTA (bkz. exit_signals) — karşılaştırma için.

    start_mode="pine" : katı Pine okuması — ilk alım ancak OS→OB→OS'ten sonra
    start_mode="flat" : nakitken görülen İLK aşırı satım da alır (varsayılan)"""
    if signal_mode == "exit":
        return exit_signals(rsi, ob, os_)
    st = swing_states(rsi, ob, os_)
    buy = st["to_os"].copy()
    sell = st["to_ob"].copy()
    if start_mode == "flat":
        r = rsi.to_numpy(dtype=float)
        first_os = None
        for i in range(len(r)):
            if not np.isnan(r[i]) and r[i] <= os_:
                first_os = i
                break
        if first_os is not None and not buy.iloc[first_os]:
            buy.iloc[first_os] = True
    st["buy"] = buy
    st["sell"] = sell
    return st


# =========================================================================
# VERİ
# =========================================================================
def load_data(force=False):
    """QQQ + TQQQ günlük OHLCV. Kendi cache'i; canlı depoya dokunmaz."""
    if os.path.exists(CACHE) and not force:
        return pickle.load(open(CACHE, "rb"))
    key = pu._key()
    lim = pu.RateLimiter(rpm=120)
    out = {}
    for sym in (SIGNAL_SYM, TRADE_SYM):
        tag, df = pu._download_one(sym, key, DATA_START, DATA_END, keep_floor=0.0, limiter=lim)
        if df is None or len(df) < 500:
            raise SystemExit(f"{sym} indirilemedi ({tag})")
        out[sym] = df.astype(float)
    pickle.dump(out, open(CACHE, "wb"), protocol=4)
    return out


# =========================================================================
# BACKTEST — uzun/nakit, tam pozisyon
# =========================================================================
def backtest(sig_close, trade_ohlc, ob=70.0, os_=30.0, length=14,
             start=None, end=None, start_mode="flat", signal_mode="touch",
             ema_len=0, ema_src="trade", ema_mode="combine",
             capital=INITIAL_CAPITAL, commission=COMMISSION,
             entry_bps=ENTRY_SLIP_BPS, exit_bps=EXIT_SLIP_BPS):
    """Sinyal serisi sig_close (QQQ) üzerinden trade_ohlc (TQQQ) al-sat.

    Fiyatlar sinyal barının KAPANIŞINDAN dolar; gelecek bar kullanılmaz.
    Takvim iki enstrümanın KESİŞİMİ (TQQQ 2010-02-11'de doğduğu için backtest
    fiilen oradan başlar; RSI ise QQQ'nun tüm geçmişinden ısınmıştır).

    EMA TRAILING STOP (ema_len > 0 ile açılır)
    ------------------------------------------
      ema_src  : "trade" → EMA tutulan enstrümandan (TQQQ) · "signal" → QQQ'dan
      ema_mode : "combine" → RSI hedefi DURUR, EMA ek koruma (hangisi önce gelirse)
                 "replace" → RSI satış sinyali YOK SAYILIR, çıkış yalnız EMA'dan

    KURULMA ŞARTI (önemli): RSI <= 30'da alırken fiyat zaten EMA'ların ALTINDADIR
    (RSI o yüzden düşük). Kurulma şartı olmasa stop ertesi bar tetiklenir ve
    yöntem hiç işlem taşıyamaz. Bu yüzden stop, fiyat EMA'nın ÜSTÜNE kapanana
    kadar PASİF kalır; ancak kurulduktan sonra EMA altı kapanışta satar.
    Kapanış teyitli (gün-içi iğne satmaz) — Qulla-21'in 21-EMA runner'ıyla aynı
    konvansiyon."""
    rsi = rsi_tv(sig_close, length)
    sg = signals(rsi, ob, os_, start_mode, signal_mode)

    cal = sig_close.index.intersection(trade_ohlc.index)
    if start:
        cal = cal[cal >= pd.Timestamp(start)]
    if end:
        cal = cal[cal <= pd.Timestamp(end)]
    if len(cal) < 30:
        raise SystemExit("pencere çok kısa")

    px = trade_ohlc["Close"].reindex(cal)
    buy = sg["buy"].reindex(cal).fillna(False)
    sell = sg["sell"].reindex(cal).fillna(False)
    rsi_w = rsi.reindex(cal)

    # EMA, kendi TAM serisinde hesaplanır (pencereye kırpılmadan) → pencere
    # başında ısınmış gelir; sonra takvime hizalanır.
    # HATA TUZAĞI: EMA hangi seriden hesaplanıyorsa KIYAS FİYATI DA o seriden
    # olmalı. TQQQ fiyatını ($30) QQQ'nun EMA'sıyla ($400) karşılaştırmak stop'u
    # sessizce ölü bırakır (kurulma şartı hiç sağlanmaz) — ölçüldü, tüm QQQ
    # satırları bazla birebir aynı çıkmıştı.
    if ema_len and ema_len > 0:
        base = trade_ohlc["Close"] if ema_src == "trade" else sig_close
        ema_w = ema(base, int(ema_len)).reindex(cal)
        ref_w = base.reindex(cal)              # EMA ile AYNI serinin fiyatı
    else:
        ema_w = ref_w = None

    cash = float(capital)
    shares = 0.0
    trades, eq = [], []
    entry_px = entry_dt = None
    days_in = 0
    armed = False                              # EMA stop kuruldu mu

    for d in cal:
        p = float(px.loc[d])
        if not np.isfinite(p) or p <= 0:
            eq.append((d, cash + shares * (entry_px or 0.0)))
            continue

        if shares == 0.0 and bool(buy.loc[d]):
            fill = p * (1 + entry_bps / 1e4)
            shares = max(0.0, (cash - commission) / fill)
            cash -= shares * fill + commission
            entry_px, entry_dt = fill, d
            armed = False                      # stop henüz kurulmadı
        elif shares > 0.0 and _exit_now(d, sell, ema_w, ref_w, ema_mode, armed):
            fill = p * (1 - exit_bps / 1e4)
            proceeds = shares * fill - commission
            cash += proceeds
            trades.append({
                "in": str(entry_dt.date()), "out": str(d.date()),
                "entry": round(entry_px, 4), "exit": round(fill, 4),
                "bars": int(cal.get_loc(d) - cal.get_loc(entry_dt)),
                "pnl": round(proceeds - shares * entry_px, 2),
                "pct": round((fill / entry_px - 1) * 100, 2),
                "rsi_in": round(float(rsi_w.loc[entry_dt]), 1),
                "rsi_out": round(float(rsi_w.loc[d]), 1),
                # çıkış nedeni etiketi: EMA kapalıysa her zaman RSI; açıksa
                # replace modunda hep EMA, combine modunda hangisi tetiklediyse
                "why": ("RSI" if (not ema_len or ema_len <= 0)
                        else (f"EMA{int(ema_len)}" if ema_mode == "replace"
                              else ("RSI" if bool(sell.loc[d]) else f"EMA{int(ema_len)}")))})
            shares = 0.0
            entry_px = entry_dt = None
            armed = False

        # KURULMA: fiyat EMA'nın üstüne kapandıysa stop artık aktif
        if shares > 0.0 and ema_w is not None:
            e = ema_w.get(d, np.nan); c = ref_w.get(d, np.nan)
            if np.isfinite(e) and np.isfinite(c) and float(c) > float(e):
                armed = True

        if shares > 0.0:
            days_in += 1
        eq.append((d, cash + shares * p))

    # pencere sonunda açık pozisyon → piyasa değerinden kapat (raporlama için)
    open_trade = None
    if shares > 0.0:
        d = cal[-1]
        p = float(px.loc[d])
        open_trade = {"in": str(entry_dt.date()), "out": f"AÇIK ({d.date()})",
                      "entry": round(entry_px, 4), "exit": round(p, 4),
                      "bars": int(cal.get_loc(d) - cal.get_loc(entry_dt)),
                      "pnl": round(shares * p - shares * entry_px, 2),
                      "pct": round((p / entry_px - 1) * 100, 2),
                      "rsi_in": round(float(rsi_w.loc[entry_dt]), 1),
                      "rsi_out": round(float(rsi_w.loc[d]), 1)}

    equity = pd.Series(dict(eq)).sort_index()
    return {"equity": equity, "trades": trades, "open": open_trade,
            "exposure": days_in / max(1, len(cal)), "calendar": cal,
            "rsi": rsi_w, "buy": buy, "sell": sell}


def _exit_now(d, sell, ema_w, ref_w, ema_mode, armed):
    """Bu barda çıkılsın mı? (RSI hedefi ve/veya kurulmuş EMA trailing stop)

    ref_w, EMA ile AYNI serinin kapanışıdır — kıyas hep kendi içinde yapılır."""
    rsi_hit = bool(sell.loc[d])
    if ema_w is None:
        return rsi_hit
    ema_hit = False
    if armed:
        e = ema_w.get(d, np.nan); c = ref_w.get(d, np.nan)
        ema_hit = bool(np.isfinite(e) and np.isfinite(c) and float(c) < float(e))
    if ema_mode == "replace":
        return ema_hit
    return rsi_hit or ema_hit


def buy_hold(price: pd.Series, cal, capital=INITIAL_CAPITAL,
             commission=COMMISSION, slip_bps=ENTRY_SLIP_BPS):
    p = price.reindex(cal).dropna()
    if len(p) < 2:
        return None
    fill = float(p.iloc[0]) * (1 + slip_bps / 1e4)
    sh = (capital - commission) / fill
    return (sh * p).reindex(cal).ffill()


def metrics(equity: pd.Series, trades, exposure, capital=INITIAL_CAPITAL, open_trade=None):
    eq = equity.dropna()
    if len(eq) < 2:
        return {}
    roi = (float(eq.iloc[-1]) / capital - 1) * 100
    dd = float(((eq / eq.cummax() - 1) * 100).min())
    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    cagr = ((float(eq.iloc[-1]) / capital) ** (1 / yrs) - 1) * 100
    allt = list(trades) + ([open_trade] if open_trade else [])
    wins = [t for t in allt if t["pnl"] > 0]
    loss = [t for t in allt if t["pnl"] <= 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in loss))
    r = eq.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
    return {
        "roi": round(roi, 1), "cagr": round(cagr, 1), "max_dd": round(dd, 1),
        "calmar": round(roi / abs(dd), 2) if dd else 0.0,
        "cagr_dd": round(cagr / abs(dd), 2) if dd else 0.0,
        "sharpe": round(sharpe, 2),
        "trades": len(allt), "kapali": len(trades),
        "win_rate": round(100 * len(wins) / max(1, len(allt)), 1),
        # zarar eden işlem yoksa PF matematiksel olarak sonsuzdur; JSON'da
        # Infinity diye bir şey olmadığı için None döner (arayüz '—' gösterir).
        "profit_factor": round(gp / gl, 2) if gl else None,
        "exposure": round(100 * exposure, 1),
        "avg_bars": round(float(np.mean([t["bars"] for t in allt])), 0) if allt else 0,
        "best": round(max((t["pct"] for t in allt), default=0.0), 1),
        "worst": round(min((t["pct"] for t in allt), default=0.0), 1),
        "son_equity": round(float(eq.iloc[-1]), 0),
    }


def bh_metrics(curve: pd.Series, capital=INITIAL_CAPITAL):
    if curve is None:
        return {}
    eq = curve.dropna()
    roi = (float(eq.iloc[-1]) / capital - 1) * 100
    dd = float(((eq / eq.cummax() - 1) * 100).min())
    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    cagr = ((float(eq.iloc[-1]) / capital) ** (1 / yrs) - 1) * 100
    r = eq.pct_change().dropna()
    return {"roi": round(roi, 1), "cagr": round(cagr, 1), "max_dd": round(dd, 1),
            "calmar": round(roi / abs(dd), 2) if dd else 0.0,
            "cagr_dd": round(cagr / abs(dd), 2) if dd else 0.0,
            "sharpe": round(float(r.mean() / r.std() * np.sqrt(252)), 2) if r.std() > 0 else 0.0,
            "exposure": 100.0, "trades": 1, "son_equity": round(float(eq.iloc[-1]), 0)}


# =========================================================================
# RAPOR
# =========================================================================
WINS = [
    ("tüm geçmiş", None, None),
    ("2010-2015", "2010-02-11", "2015-12-31"),
    ("2016-2019", "2016-01-01", "2019-12-31"),
    ("2020-2022", "2020-01-01", "2022-12-31"),
    ("2023-bugün", "2023-01-01", None),
]

GRID = [(ln, ob, os_) for ln in (7, 14, 21)
        for ob, os_ in ((70, 30), (75, 25), (65, 35), (80, 20))]


def run_one(q, t, ln=14, ob=70, os_=30, start=None, end=None, start_mode="flat"):
    r = backtest(q, t, ob=ob, os_=os_, length=ln, start=start, end=end, start_mode=start_mode)
    m = metrics(r["equity"], r["trades"], r["exposure"], open_trade=r["open"])
    return r, m


def line(w=104):
    print("-" * w)


def report(q, t, out_json=OUT_JSON):
    res = {"meta": {"signal": SIGNAL_SYM, "trade": TRADE_SYM,
                    "commission": COMMISSION, "entry_bps": ENTRY_SLIP_BPS,
                    "exit_bps": EXIT_SLIP_BPS, "capital": INITIAL_CAPITAL}}

    print("\n" + "=" * 104)
    print("🔔 SARKAÇ-14 — QQQ'nun RSI salınımıyla TQQQ al-sat")
    print("=" * 104)
    print(f"sinyal: RSI({SIGNAL_SYM},14) <= 30 AL · >= 70 SAT   |   işlem: {TRADE_SYM} "
          f"(tam pozisyon, kapanıştan)")
    print(f"maliyet: ${COMMISSION}/işlem + giriş {ENTRY_SLIP_BPS:.0f}bps / çıkış "
          f"{EXIT_SLIP_BPS:.0f}bps · sermaye ${INITIAL_CAPITAL:,.0f}")

    # ---- ana koşu + karşılaştırma --------------------------------------
    r, m = run_one(q, t)
    cal = r["calendar"]
    rows = [("🔔 SARKAÇ-14", m)]
    for nm, px in ((f"{TRADE_SYM} al-tut", t["Close"]), (f"{SIGNAL_SYM} al-tut", q)):
        rows.append((nm, bh_metrics(buy_hold(px, cal))))

    print(f"\nANA KOŞU  ({cal[0].date()} → {cal[-1].date()})")
    line()
    print(f"{'':16s} {'ROI':>11s} {'CAGR':>7s} {'MaxDD':>8s} {'CAGR/DD':>8s} {'Sharpe':>7s} "
          f"{'işlem':>6s} {'isabet':>7s} {'piyasada':>9s}")
    for nm, x in rows:
        print(f"{nm:16s} {x['roi']:>10.1f}% {x['cagr']:>6.1f}% {x['max_dd']:>7.1f}% "
              f"{x['cagr_dd']:>8.2f} {x['sharpe']:>7.2f} {x.get('trades',1):>6d} "
              f"{x.get('win_rate','—'):>6}{'%' if 'win_rate' in x else ' '} "
              f"{x.get('exposure',100):>8.0f}%")
    line()
    print("CAGR/DD = yıllık bileşik getiri ÷ en derin çukur. ROI/MaxDD çok yıllı bileşikte")
    print("yanıltıcıdır (ROI kümülatif, MaxDD tek olay) — kıyas bu sütundan yapılır.")
    res["main"] = {nm: x for nm, x in rows}
    res["trades"] = r["trades"] + ([r["open"]] if r["open"] else [])

    # ---- pencereler -----------------------------------------------------
    print("\nDÖNEMLER")
    line()
    print(f"{'dönem':14s} {'SARKAÇ ROI':>12s} {'TQQQ al-tut':>12s} {'QQQ al-tut':>12s} "
          f"{'SARKAÇ DD':>11s} {'TQQQ DD':>9s} {'işlem':>6s}")
    wrows = []
    for nm, a, b in WINS:
        rr, mm = run_one(q, t, start=a, end=b)
        c2 = rr["calendar"]
        bt_ = bh_metrics(buy_hold(t["Close"], c2))
        bq = bh_metrics(buy_hold(q, c2))
        print(f"{nm:14s} {mm['roi']:>11.1f}% {bt_['roi']:>11.1f}% {bq['roi']:>11.1f}% "
              f"{mm['max_dd']:>10.1f}% {bt_['max_dd']:>8.1f}% {mm['trades']:>6d}")
        wrows.append({"win": nm, "sarkac": mm, "tqqq": bt_, "qqq": bq})
    line()
    res["windows"] = wrows

    # ---- parametre gridi ------------------------------------------------
    print("\nPARAMETRE DUYARLILIĞI  (17 işlemlik örnekte tek parametre seti kanıt değildir)")
    line()
    print(f"{'RSI':>4s} {'AL<=':>5s} {'SAT>=':>6s} {'ROI':>11s} {'CAGR':>7s} {'MaxDD':>8s} "
          f"{'CAGR/DD':>8s} {'işlem':>6s} {'isabet':>7s} {'en kötü':>8s}")
    grows = []
    for ln, ob, os_ in GRID:
        _, gm = run_one(q, t, ln=ln, ob=ob, os_=os_)
        star = " ←" if (ln, ob, os_) == (14, 70, 30) else ""
        print(f"{ln:>4d} {os_:>5d} {ob:>6d} {gm['roi']:>10.1f}% {gm['cagr']:>6.1f}% "
              f"{gm['max_dd']:>7.1f}% {gm['cagr_dd']:>8.2f} {gm['trades']:>6d} "
              f"{gm['win_rate']:>6.0f}% {gm['worst']:>7.1f}%{star}")
        grows.append({"len": ln, "ob": ob, "os": os_, **gm})
    line()
    res["grid"] = grows

    # ---- işlem defteri --------------------------------------------------
    allt = r["trades"] + ([r["open"]] if r["open"] else [])
    print("\nİŞLEM DEFTERİ")
    line()
    print(f"{'giriş':12s} {'çıkış':14s} {'bar':>5s} {'RSI giriş':>10s} {'RSI çıkış':>10s} "
          f"{'sonuç':>9s} {'P&L $':>13s}")
    for x in allt:
        print(f"{x['in']:12s} {x['out']:14s} {x['bars']:>5d} {x['rsi_in']:>10.1f} "
              f"{x['rsi_out']:>10.1f} {x['pct']:>8.1f}% {x['pnl']:>13,.0f}")
    line()

    # ---- kuyruk teşhisi -------------------------------------------------
    worst = min(allt, key=lambda x: x["pct"]) if allt else None
    if worst:
        tot = sum(x["pnl"] for x in allt)
        print(f"\nKUYRUK: en kötü tek işlem {worst['in']} → {worst['out']} "
              f"({worst['bars']} bar) {worst['pct']:+.1f}% = ${worst['pnl']:,.0f}")
        pos = sum(x["pnl"] for x in allt if x["pnl"] > 0)
        print(f"  toplam net ${tot:,.0f} · kazançların toplamı ${pos:,.0f} · "
              f"bu tek işlem kazançların %{abs(worst['pnl'])/max(pos,1)*100:.0f}'ini götürdü")
        res["worst_trade"] = worst

    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    json.dump(res, open(out_json, "w"), indent=1, default=float)
    print(f"\nkaydedildi {out_json}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="veriyi yeniden indir")
    ap.add_argument("--rsi-check", action="store_true", help="RSI doğrulaması")
    a = ap.parse_args()
    d = load_data(force=a.refresh)
    q, t = d[SIGNAL_SYM]["Close"], d[TRADE_SYM]
    if a.rsi_check:
        import swing2_backtest as s
        both = pd.DataFrame({"tv": rsi_tv(q, 14), "eski": s.rsi(q, 14)}).dropna()
        late = both[both.index >= "2010-01-01"]
        print(f"RSI yakınsama (2010+): maks fark {(late['tv']-late['eski']).abs().max():.8f}")
        return
    report(q, t)


if __name__ == "__main__":
    main()


# =========================================================================
# DASHBOARD API — backtest.html'in beklediği yanıt şekli
# =========================================================================
# Qulla-21 ile AYNI sözleşme döner (config/metrics/equity/monthly/trades) ki
# arayüzdeki render kodu değişmeden çalışsın. Tek fark: kıyas çizgisi SPY değil
# TQQQ al-tut — bu yöntemin dürüst alternatifi odur. Etiket `bench_label` ile
# gelir, arayüz onu kullanır.
def _period_start(period, end_ts):
    m = {"1y": 365, "2y": 730, "5y": 1826, "10y": 3652}
    return end_ts - pd.Timedelta(days=m.get(str(period), 730))


def _monthly_table(eq: pd.Series, bench: pd.Series):
    me = eq.resample("ME").last()
    r = me.pct_change().dropna() * 100
    mb = bench.resample("ME").last() if bench is not None else None
    rb = (mb.pct_change().dropna() * 100) if mb is not None else None
    rows = []
    for y in sorted({d.year for d in r.index}):
        months = [None] * 12
        for d, v in r[r.index.year == y].items():
            months[d.month - 1] = round(float(v), 2)
        ys = r[r.index.year == y]
        yp = (np.prod([1 + v / 100 for v in ys]) - 1) * 100 if len(ys) else None
        bp = None
        if rb is not None:
            bs = rb[rb.index.year == y]
            bp = (np.prod([1 + v / 100 for v in bs]) - 1) * 100 if len(bs) else None
        rows.append({"year": int(y),
                     "months": months,
                     "year_pct": round(float(yp), 2) if yp is not None else None,
                     "spy_pct": round(float(bp), 2) if bp is not None else None,
                     "alpha_pct": (round(float(yp - bp), 2)
                                   if (yp is not None and bp is not None) else None)})
    return rows


def run_api(params: dict) -> dict:
    p = params or {}
    ln = int(p.get("rsi_length", 14))
    ob = float(p.get("rsi_overbought", 70))
    os_ = float(p.get("rsi_oversold", 30))
    if not (51 <= ob <= 100 and 1 <= os_ <= 49):
        raise ValueError("RSI eşikleri: aşırı alım 51-100, aşırı satım 1-49")
    if not (2 <= ln <= 100):
        raise ValueError("RSI uzunluğu 2-100 olmalı")
    cap = float(p.get("initial_capital", INITIAL_CAPITAL))

    d = load_data()
    q, t = d[SIGNAL_SYM]["Close"], d[TRADE_SYM]

    full = q.index.intersection(t.index)
    end_ts = pd.Timestamp(p["end_date"]) if p.get("end_date") else full[-1]
    if p.get("start_date") and p.get("end_date"):
        start_ts, date_range = pd.Timestamp(p["start_date"]), True
    else:
        start_ts, date_range = max(_period_start(p.get("period", "2y"), end_ts), full[0]), False

    smode = p.get("signal_mode", "touch")
    if smode not in ("touch", "exit"):
        raise ValueError("signal_mode: 'touch' veya 'exit'")
    elen = int(p.get("ema_len", 0) or 0)
    if elen and not (2 <= elen <= 200):
        raise ValueError("EMA uzunluğu 2-200 olmalı (0 = kapalı)")
    esrc = p.get("ema_src", "trade")
    emode = p.get("ema_mode", "replace")
    if esrc not in ("trade", "signal") or emode not in ("combine", "replace"):
        raise ValueError("ema_src: 'trade'|'signal' · ema_mode: 'combine'|'replace'")
    r = backtest(q, t, ob=ob, os_=os_, length=ln,
                 start=str(start_ts.date()), end=str(end_ts.date()),
                 start_mode=p.get("start_mode", "flat"),
                 signal_mode=smode, ema_len=elen, ema_src=esrc, ema_mode=emode,
                 capital=cap)
    cal = r["calendar"]
    m = metrics(r["equity"], r["trades"], r["exposure"], capital=cap, open_trade=r["open"])

    # KIYAS = QQQ al-tut (piyasanın kendisi). TQQQ al-tut kıyas olarak
    # KULLANILMAZ — kaldıraçlı bir ürünü yine kaldıraçlı hâline kıyaslamak
    # "piyasayı geçtin mi" sorusunu cevaplamaz. TQQQ yalnız işlem yapılan
    # enstrüman olarak sinyal grafiğinde görünür.
    bench = buy_hold(q, cal, capital=cap)
    bm = bh_metrics(bench, capital=cap)

    eq = r["equity"]
    equity = [{"date": str(dt.date()), "equity": round(float(v), 2),
               "spy": (round(float(bench.loc[dt]), 2)
                       if bench is not None and dt in bench.index
                       and np.isfinite(bench.loc[dt]) else None)}
              for dt, v in eq.items()]

    allt = r["trades"] + ([r["open"]] if r["open"] else [])
    trades = [{"symbol": TRADE_SYM, "entry_date": x["in"],
               "exit_date": x["out"], "entry": x["entry"], "exit": x["exit"],
               "pnl": x["pnl"], "pnl_pct": x["pct"],
               "outcome": ("AÇIK" if str(x["out"]).startswith("AÇIK")
                           else (x.get("why") or f"RSI≥{int(ob)}")),
               "sector": "—", "score": int(round(x["rsi_in"]))} for x in allt]

    return {
        "config": {"method": "sarkac", "universe_n": 1,
                   "start": str(cal[0].date()), "end": str(cal[-1].date()),
                   "period": p.get("period", "2y"), "date_range": date_range,
                   "signal_sym": SIGNAL_SYM, "trade_sym": TRADE_SYM,
                   "rsi_length": ln, "rsi_overbought": ob, "rsi_oversold": os_,
                   "start_mode": p.get("start_mode", "flat"),
                   "signal_mode": smode, "ema_len": elen,
                   "ema_src": esrc, "ema_mode": emode},
        "bench_label": f"{SIGNAL_SYM} al-tut",
        "metrics": {
            "roi": m["roi"], "spy_roi": bm.get("roi"),
            "alpha": round(m["roi"] - bm.get("roi", 0.0), 1),
            "max_dd": m["max_dd"], "win_rate": m["win_rate"],
            "profit_factor": m["profit_factor"], "trades": m["trades"],
            "final": m["son_equity"], "initial": cap,
            "peak": round(float(eq.cummax().iloc[-1]), 0),
            "cagr": m["cagr"], "cagr_dd": m["cagr_dd"], "sharpe": m["sharpe"],
            "exposure": m["exposure"], "avg_bars": m["avg_bars"],
            "best": m["best"], "worst": m["worst"],
            "bench_cagr": bm.get("cagr"), "bench_dd": bm.get("max_dd"),
            "bench_cagr_dd": bm.get("cagr_dd"), "bench_sharpe": bm.get("sharpe"),
            "tp": 0, "partial": 0, "trail": 0, "stop": 0,
            "eod": 1 if r["open"] else 0,
        },
        "equity": equity,
        "monthly": _monthly_table(eq, bench),
        "trades": trades,
        "grid": [],
        "chart": _chart_block(q, t, r, cal, ob, os_, elen, esrc),
    }


def _chart_block(q, t, r, cal, ob, os_, ema_len=0, ema_src="trade"):
    """Sinyal grafiği için hizalı diziler: QQQ fiyatı, RSI, ve AL/SAT işaretleri.

    İşaretler tarih dizisiyle AYNI uzunlukta; sinyal olmayan günlerde None.
    Böylece arayüz tarafında x ekseni hizalaması için ek iş gerekmez."""
    qq = q.reindex(cal)
    tt = t["Close"].reindex(cal)
    rsi = r["rsi"].reindex(cal)
    buy = r["buy"].reindex(cal).fillna(False)
    sell = r["sell"].reindex(cal).fillna(False)

    def num(x):
        v = float(x)
        return round(v, 2) if np.isfinite(v) else None

    dates = [str(d.date()) for d in cal]
    qv = [num(v) for v in qq]
    tv_ = [num(v) for v in tt]
    rv = [num(v) for v in rsi]
    b_px = [qv[i] if bool(buy.iloc[i]) else None for i in range(len(cal))]
    s_px = [qv[i] if bool(sell.iloc[i]) else None for i in range(len(cal))]
    b_rsi = [rv[i] if bool(buy.iloc[i]) else None for i in range(len(cal))]
    s_rsi = [rv[i] if bool(sell.iloc[i]) else None for i in range(len(cal))]
    # trailing stop açıksa EMA'yı da çiz — hangi seriden hesaplandıysa
    # grafikte o eksene oturur (QQQ paneli QQQ EMA'sını gösterir)
    ev = None
    if ema_len and ema_len > 0 and ema_src == "signal":
        ev = [num(v) for v in ema(qq, int(ema_len))]
    elif ema_len and ema_len > 0:
        ev = [num(v) for v in ema(tt, int(ema_len))]
    return {"dates": dates, "qqq": qv, "tqqq": tv_, "rsi": rv,
            "buy_px": b_px, "sell_px": s_px, "buy_rsi": b_rsi, "sell_rsi": s_rsi,
            "ob": ob, "os": os_, "ema": ev, "ema_len": int(ema_len or 0),
            "ema_src": ema_src,
            "n_buy": int(buy.sum()), "n_sell": int(sell.sum())}

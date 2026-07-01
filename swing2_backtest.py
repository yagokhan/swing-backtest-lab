#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Swing Trade 2.0 — Çoklu Hisse Tarama Tabanlı Portföy Backtest Simülatörü (v3)
============================================================================
JavaScript "Swing Trade 2.0" motorunun TAM Python portu + portföy backtest'i.

v3 yenilikleri:
  • PARAMETRE GRID-SEARCH (skor eşiği / R-R / ATR stop optimizasyonu — veri 1 kez indirilir)
  • AYLIK GETİRİ TABLOSU (Year × Month + yıllık toplam)
  • KISMİ KÂR ALMA (partial take-profit) + TRAILING STOP (ATR tabanlı)

v2'den gelenler:
  • Geniş S&P 500 havuzu + sektör ETF göreli güç (RS)
  • 8-katman skor (24p) + kill-switch (decisionFromScore portu)
  • Dinamik ATR stop + 1:3 R/R trade-plan
  • Komisyon + slippage · bileşik (compounding) · CSV + matplotlib

Kurulum:
  pip install yfinance pandas numpy matplotlib
  python3 swing2_backtest.py

Sınırlar: Katman 5 (opsiyon) nötr 1p · Katman 2 yalnız VCP+konsolidasyon ·
          Katman 8 earnings varsa kullanılır.
"""

from __future__ import annotations
import os
import copy
import itertools
import warnings
import pickle
import hashlib
import concurrent.futures as _cf
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("Eksik bağımlılık: pip install yfinance pandas numpy matplotlib")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except ImportError:
    HAVE_MPL = False

warnings.simplefilter("ignore", category=FutureWarning)
warnings.simplefilter("ignore", category=RuntimeWarning)


# =========================================================================
# SEKTÖR ETF HARİTASI (JS SECTOR_MAP portu)
# =========================================================================
SECTOR_MAP = {
    "NVDA": "SMH", "AMD": "SMH", "AVGO": "SMH", "QCOM": "SMH", "INTC": "SMH",
    "MU": "SMH", "MRVL": "SMH", "LRCX": "SMH", "AMAT": "SMH", "KLAC": "SMH",
    "TXN": "SMH", "ADI": "SMH", "MCHP": "SMH", "NXPI": "SMH", "ON": "SMH",
    "MSFT": "IGV", "ORCL": "IGV", "CRM": "IGV", "ADBE": "IGV", "NOW": "IGV",
    "SNOW": "IGV", "PANW": "IGV", "CRWD": "IGV", "FTNT": "IGV", "PLTR": "IGV",
    "INTU": "IGV", "CDNS": "IGV", "SNPS": "IGV",
    "AAPL": "XLK", "CSCO": "XLK", "IBM": "XLK", "ACN": "XLK", "DELL": "XLK",
    "ANET": "XLK", "SMCI": "XLK",
    "GOOGL": "XLC", "GOOG": "XLC", "META": "XLC", "NFLX": "XLC", "DIS": "XLC",
    "T": "XLC", "VZ": "XLC", "TMUS": "XLC",
    "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "NKE": "XLY", "MCD": "XLY",
    "SBUX": "XLY", "BKNG": "XLY", "LOW": "XLY", "TJX": "XLY",
    "WMT": "XLP", "PG": "XLP", "KO": "XLP", "PEP": "XLP", "COST": "XLP",
    "PM": "XLP", "MO": "XLP",
    "JPM": "XLF", "BAC": "XLF", "GS": "XLF", "MS": "XLF", "WFC": "XLF",
    "C": "XLF", "V": "XLF", "MA": "XLF", "AXP": "XLF", "SCHW": "XLF",
    "BLK": "XLF", "SPGI": "XLF",
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE", "SLB": "XLE", "EOG": "XLE",
    "JNJ": "XLV", "UNH": "XLV", "LLY": "XLV", "PFE": "XLV", "MRK": "XLV",
    "ABBV": "XLV", "TMO": "XLV", "ABT": "XLV", "AMGN": "XLV", "ISRG": "XLV",
    "CAT": "XLI", "BA": "XLI", "GE": "XLI", "HON": "XLI", "RTX": "XLI",
    "LMT": "XLI", "UPS": "XLI", "UNP": "XLI", "DE": "XLI",
}
DEFAULT_UNIVERSE = tuple(SECTOR_MAP.keys())


# =========================================================================
# KONFİGÜRASYON
# =========================================================================
@dataclass
class Config:
    universe: tuple = DEFAULT_UNIVERSE
    benchmark: str = "SPY"
    period: str = "2y"
    interval: str = "1d"
    # El ile tarih aralığı (boş = period kullan). İndirme bu tarihlerden ~warmup_buffer
    # gün önce başlar (indikatör/SMA200 ısınması); işlem yalnız [start_date, end_date] arasında.
    start_date: str = ""
    end_date: str = ""
    warmup_calendar_buffer: int = 420   # start_date öncesi indirilecek tampon (takvim günü)

    initial_capital: float = 100_000.0
    max_positions: int = 5
    max_position_pct: float = 0.20
    sizing_mode: str = "fixed"         # 'fixed' (poz başına sermaye×%20) | 'risk' (işlem başına sabit risk)
    risk_per_trade_pct: float = 1.0    # risk modunda: işlem başına riske edilecek sermaye %'si
    compounding: bool = True

    warmup_bars: int = 220
    atr_period: int = 14
    rr_target: float = 2.0        # 2y+5y grid şampiyonu
    atr_stop_mult: float = 1.5    # 2y+5y grid şampiyonu (dar stop kazandı)
    pivot_lookback: int = 10
    slope_window: int = 20

    min_score: int = 16           # 2y+5y grid şampiyonu (tatlı nokta)
    require_not_killswitch: bool = True
    max_dist_sma20: float = 0.0   # SMA20'ye max uzaklık (chase kapısı); 0 = kapalı, ör. 0.25 = %25

    commission_per_trade: float = 1.0
    slippage_bps: float = 5.0          # limit-benzeri (hedef/kısmi) fill kayması
    entry_slippage_bps: float = 8.0    # GİRİŞ: kapanışa 5dk kala (15:55 ET) hacim/spread oynaklığı
    stop_slippage_bps: float = 15.0    # market emri (stop/trail) — daha çok kayar
    # Giriş dolum referansı: 'close' = resmî kapanış (16:00) · 'preclose' = 15:45 ET gün-içi proxy
    entry_fill_mode: str = "close"
    preclose_frac: float = 0.96        # 15:45 ET ≈ seansın %96'sı (375/390 dk) → Open→Close yolu
    gap_fills: bool = True             # gap'le açılan barlarda açılıştan dol (gerçekçi)
    use_earnings: bool = True
    per_ticker_download: bool = True   # her sembolü TEK TEK indir (anti-contamination)
    download_workers: int = 10         # paralel indirme işçisi (hız)
    debug_download: bool = False       # her sembol için ilk Close'u DEBUG bas
    disk_cache: bool = False           # indirilen veriyi diske yaz/oku (yfinance throttle'a karşı)
    cache_dir: str = "swing2_cache"
    price_source: str = "fmp"          # günlük fiyat kaynağı: 'fmp' (ücretli, varsayılan) | 'yfinance'

    # --- v3: Kısmi kâr alma + trailing stop ---
    partial_tp: bool = True
    partial_rr: float = 2.0        # ilk kâr alma seviyesi (1:2.0) — FMP 2y+5y kalibrasyon şampiyonu
    partial_pct: float = 0.5       # pozisyonun %50'sini sat
    trailing_stop: bool = True
    atr_trail_mult: float = 2.5    # trailing stop = close - mult*ATR
    trail_after_r: float = 1.0     # +1R sonrası trailing devreye girer
    breakeven_mode: str = "strict_entry"  # kısmi sonrası stop: 'strict_entry' | 'half_risk'

    # --- v4: 8-MA trailing çıkış (trend-takip) ---
    entry_mode: str = "swing2"     # GİRİŞ: 'swing2' (8-katman skor) | 'qswing_breakout' (Qullamaggie 20g kırılım)
    qswing_breakout_lb: int = 40   # qswing kırılım: önceki kaç günün tepesi (FMP ızgara şampiyonu: 40g)
    qswing_near_high: float = 0.75 # 52H zirveye yakınlık (fiyat ≥ bu × 52H)
    qswing_vdu_max: float = 9.0    # VDU (vol5/vol50) tavanı; ≥9 = kapalı, ör. 1.0 = hacim kurumuş şart
    qswing_rs_min: float = 0.0     # min görece güç (60g getiri − SPY 60g); ör. 8 = SPY'ı ≥%8 geç
    qswing_min_score: float = 0.0  # qswing 0–100 öncelik skoru EŞİĞİ (0 = kapalı); ör. 65 = sadece skor≥65 gir
    exit_mode: str = "optimized"   # 'optimized' (mevcut) | 'ma_trail' (8-MA altına kapanınca çık)
    ma_trail_len: int = 8          # hareketli ortalama periyodu
    ma_trail_type: str = "sma"     # 'sma' | 'ema'
    ma_confirm_close: bool = True  # True: günü MA altında KAPATINCA çık; False: gün-içi değince
    ma_keep_initial_stop: bool = True  # ilk koruma stopu (ATR/LOW10) felaket-zemini olarak kalsın

    # --- v5: 8-EMA stop sabit + TP-modu grid-search ---
    # exit_mode='tp_grid' iken stop DAİMA 8-EMA; aşağıdaki tp_mode TP tarafını belirler
    tp_mode: str = "RR_BASED"          # 'RR_BASED' | 'MOMENTUM_OSCILLATOR' | 'ATR_CLIMAX' | 'HYBRID_TREND'
    rsi_overbought_limit: float = 70.0 # MOMENTUM_OSCILLATOR: RSI bu seviyede tam TP
    climax_atr_mult: float = 2.0       # ATR_CLIMAX: Close > 8EMA + mult*ATR → aşırı uzama, çık
    hybrid_runner_ma: int = 21         # HYBRID_TREND: gövde yarısının takip ettiği EMA

    # --- v6: BÖLÜNMÜŞ ÇIKIŞ (exit_mode='split') ---
    # Pozisyon split_ratio / (1-split_ratio) iki yarıya bölünür; her yarı KENDİ atomik
    # kuralıyla yönetilir (ortak felaket stopu YOK). Atomik kural id'leri:
    #   'ema8' | 'ema21' | 'ma10' | 'ma20' | 'ma50' (kapanış MA altına inince) ·
    #   'target' (+param×R sabit hedef, limit) · 'atr_trail' (param×ATR şamdan trail).
    split_a: str = "ema8"
    split_b: str = "ema21"
    split_a_param: float = 0.0         # 'target'→R katı (vars. 2.0) · 'atr_trail'→ATR× (vars. 2.5)
    split_b_param: float = 0.0
    split_ratio: float = 0.5           # A yarısının payı (kalan B'ye)
    # +2R (A) yarısı çıkınca kalan runner (B) slotu İŞGAL ETMESİN → boşalan sermaye yeniden
    # konuşlanabilir. Tek başına zayıf; büyük poz% ile birlikte anlamlı ("combo").
    # (opt-in: varsayılan kapalı; canlı Qulla-21 ve mevcut backtest davranışı DEĞİŞMEZ.)
    free_runner_slots: bool = False

    # --- v7: ATR-REJİM (oynaklık/testere kilidi + saf ATR çıkış) ---
    # Rejim kilidi: SPY 20g ATR% (= SPY_ATR20/SPY_Close*100) eşiği aşarsa piyasa aşırı
    # çalkantılı/testere kabul edilir → skor ne olursa olsun YENİ İŞLEM AÇILMAZ.
    # (opt-in: varsayılan kapalı; mevcut çıkış modlarının davranışını DEĞİŞTİRMEZ.)
    regime_atr_filter: bool = False    # True → SPY oynaklık kilidi aktif
    regime_atr_threshold: float = 1.5  # SPY ATR20% tavanı (%); ör. 1.5 veya 1.8 — aşılırsa kilitli
    # exit_mode='atr_regime' (saf ATR: sabit kâr-al / zarar-kes, trailing/partial YOK):
    atr_target_mult: float = 3.0       # sabit hedef = entry + mult × ATR0  (kâr-al)
    risk_per_trade_usd: float = 1000.0 # sabit-dolar risk: lot = 1000 / (entry − ATR-stop)

    # --- v6: dinamik RS-sıralı evren (selection-bias giderme) ---
    use_rs_universe: bool = False      # True: günlük top-N RS izleme listesi girişleri kapılar
    rs_n: int = 50                     # izleme listesi büyüklüğü (top-N)
    rs_weights: tuple = (0.2, 0.4, 0.4)   # 1ay/3ay/6ay momentum ağırlıkları
    rs_skip: int = 5                   # son N barı atla (kısa vade dönüş gürültüsü)
    rs_windows: tuple = (21, 63, 126)  # 1ay/3ay/6ay (işlem günü)
    rs_dollar_vol_floor: float = 0.0   # min ort. $-hacim; 0 = kapalı
    rs_pool: tuple = ()                # boş = cfg.universe'i havuz olarak kullan
    liquidate_at_end: bool = True      # False: pencere sonunda açık pozisyonları KAPATMA (canlı snapshot için)

    out_dir: str = "swing2_out"
    trades_csv: str = "trades.csv"
    equity_csv: str = "equity.csv"
    equity_png: str = "equity_curve.png"
    grid_csv: str = "grid_results.csv"


# =========================================================================
# İNDİKATÖRLER
# =========================================================================
def sma(s, n): return s.rolling(n).mean()
def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0); loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1/n, adjust=False).mean()
    al = loss.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))


def macd(close, fast=12, slow=26, sig=9):
    line = ema(close, fast) - ema(close, slow)
    signal = ema(line, sig)
    return line, signal, line - signal


def stochastic(df, k=14, d=3):
    lo = df["Low"].rolling(k).min(); hi = df["High"].rolling(k).max()
    kline = (df["Close"] - lo) / (hi - lo).replace(0, np.nan) * 100
    return kline, kline.rolling(d).mean()


def atr(df, n=14):
    h, l, c = df["High"], df["Low"], df["Close"]; pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def slope_pct(s, w): return (s / s.shift(w) - 1.0) * 100.0


def add_indicators(df, cfg):
    out = df.copy(); c = out["Close"]
    out["SMA8"] = sma(c, getattr(cfg, "ma_trail_len", 8))
    out["EMA8"] = ema(c, 8)            # TP-grid sabit 8-EMA stop
    out["EMA21"] = ema(c, 21)          # HYBRID_TREND gövde takibi
    out["SMA10"] = sma(c, 10); out["SMA20"] = sma(c, 20)
    out["SMA50"] = sma(c, 50); out["SMA200"] = sma(c, 200)
    out["SLOPE200"] = slope_pct(out["SMA200"], cfg.slope_window)
    out["ATR"] = atr(out, cfg.atr_period); out["ATR_PCT"] = out["ATR"] / c * 100
    # ATR-REJİM filtresi (v7): 20g BASİT TR ortalaması → oynaklık/testere metriği (SPY için kullanılır)
    _pc = c.shift(1)
    _tr20 = pd.concat([out["High"] - out["Low"], (out["High"] - _pc).abs(), (out["Low"] - _pc).abs()], axis=1).max(axis=1)
    out["ATR20"] = _tr20.rolling(20).mean()
    out["ATR20_PCT"] = out["ATR20"] / c * 100      # = (SPY_ATR_20 / SPY_Close) * 100
    out["RSI"] = rsi(c, 14)
    out["MACD"], out["MACD_SIG"], out["MACD_HIST"] = macd(c)
    out["STOCH_K"], out["STOCH_D"] = stochastic(out)
    out["STOCH_K_PREV"] = out["STOCH_K"].shift(1)
    out["STOCH_D_PREV"] = out["STOCH_D"].shift(1)   # %K↓%D kesişimi tespiti
    up = c > out["Open"]; dn = c < out["Open"]
    up_avg = (out["Volume"] * up).rolling(20).sum() / up.rolling(20).sum().replace(0, np.nan)
    dn_avg = (out["Volume"] * dn).rolling(20).sum() / dn.rolling(20).sum().replace(0, np.nan)
    out["UPDN_RATIO"] = up_avg / dn_avg
    down_vol = out["Volume"].where(dn, 0.0)
    out["MAX_DOWN_VOL10"] = down_vol.shift(1).rolling(cfg.pivot_lookback).max()
    out["POCKET_PIVOT"] = (c > out["Open"]) & (out["MAX_DOWN_VOL10"] > 0) & (out["Volume"] > out["MAX_DOWN_VOL10"])
    out["TIGHT5"] = (((out["High"] - out["Low"]) / c) < 0.012).rolling(5).sum()
    out["LOW10"] = out["Low"].rolling(cfg.pivot_lookback).min()
    out["HIGH52"] = out["High"].rolling(252).max()
    for _lb in (10, 20, 40, 63):                                  # qswing kırılım: önceki N-gün tepe (nedensel)
        out[f"HIGH_PRIOR_{_lb}"] = out["High"].rolling(_lb).max().shift(1)
    out["HIGH_PRIOR"] = out[f"HIGH_PRIOR_{getattr(cfg, 'qswing_breakout_lb', 20)}"]
    out["VDU"] = out["Volume"].rolling(5).mean() / out["Volume"].rolling(50).mean()  # hacim kuruması
    out["RET60"] = (c / c.shift(60) - 1.0) * 100.0
    return out


# =========================================================================
# PATTERN / STAGE / TRADE PLAN / SKOR (JS portu — v2 ile aynı)
# =========================================================================
def zigzag(closes, threshold=3.0):
    n = len(closes)
    if n < 4: return []
    pivots = []; last_i, last_p, trend = 0, closes[0], 0
    for i in range(1, n):
        chg = (closes[i] - last_p) / last_p * 100 if last_p else 0
        if trend >= 0 and chg <= -threshold:
            pivots.append({"i": last_i, "price": last_p, "kind": "H"}); trend, last_i, last_p = -1, i, closes[i]
        elif trend <= 0 and chg >= threshold:
            pivots.append({"i": last_i, "price": last_p, "kind": "L"}); trend, last_i, last_p = 1, i, closes[i]
        else:
            if trend >= 0 and closes[i] > last_p: last_i, last_p = i, closes[i]
            elif trend <= 0 and closes[i] < last_p: last_i, last_p = i, closes[i]
    return pivots


def detect_vcp(window, threshold=3.0):
    closes = window["Close"].to_numpy(); zz = zigzag(closes, threshold)
    cons = []
    for j in range(len(zz) - 1):
        if zz[j]["kind"] == "H" and zz[j + 1]["kind"] == "L":
            h, l = zz[j]["price"], zz[j + 1]["price"]
            cons.append({"pct": (h - l) / h * 100, "s": zz[j]["i"], "e": zz[j + 1]["i"]})
    if len(cons) < 2: return {"found": False, "strong": False}
    last = cons[-5:]
    dec = sum(1 for k in range(1, len(last)) if last[k]["pct"] < last[k - 1]["pct"] * 0.95) >= max(1, len(last) - 2)
    vols = window["Volume"].to_numpy(); vdry = False
    if len(last) >= 2:
        vf = vols[last[0]["s"]:last[0]["e"] + 1].mean() if last[0]["e"] >= last[0]["s"] else 0
        vl = vols[last[-1]["s"]:last[-1]["e"] + 1].mean() if last[-1]["e"] >= last[-1]["s"] else 0
        vdry = bool(vf and vl and vl < vf * 0.85)
    return {"found": len(cons) >= 2 and dec, "strong": len(cons) >= 3 and dec and vdry}


def detect_stage(row):
    c, s20, s50, s200, sl = row["Close"], row["SMA20"], row["SMA50"], row["SMA200"], row["SLOPE200"]
    if any(pd.isna(x) for x in (c, s200, sl)): return {"stage": 0, "pts": 0}
    if c < s200 and sl < -0.5: return {"stage": 4, "pts": 0}
    if c > s200 and abs(sl) < 1 and not pd.isna(s20) and not pd.isna(s50) and s20 < s50: return {"stage": 3, "pts": 0}
    if abs((c - s200) / s200) < 0.07 and abs(sl) < 2: return {"stage": 1, "pts": 1}
    if not pd.isna(s20) and not pd.isna(s50) and c > s200 and s20 > s50 and s50 > s200 and sl > 0:
        return {"stage": 2, "pts": 3 if (c - s200) / s200 * 100 < 25 else 2}
    if c > s200 and sl > -0.5: return {"stage": 2, "pts": 1}
    return {"stage": 4, "pts": 0}


def compute_trade_plan(row, cfg):
    c, atr_v, low10, high52 = row["Close"], row["ATR"], row["LOW10"], row["HIGH52"]
    entry = c; stop = low10; capped = False
    if not pd.isna(atr_v):
        floor = c - cfg.atr_stop_mult * atr_v
        if stop < floor: stop, capped = floor, True
    if stop >= entry: stop = entry - (atr_v if not pd.isna(atr_v) else entry * 0.02)
    risk = entry - stop; target = entry + risk * cfg.rr_target
    headroom = (high52 - entry) if not pd.isna(high52) else 0
    natural = high52 if (not pd.isna(high52) and high52 > entry * 1.03 and headroom > risk * 1.5) else entry + risk * cfg.rr_target
    rr_pot = (natural - entry) / risk if risk > 0 else None
    return {"entry": entry, "stop": stop, "target": target, "risk": risk, "rr_potential": rr_pot, "atr_capped": capped}


def score_layers(row, stage, vcp, plan, m):
    L = []
    L.append({"id": 1, "pts": stage["pts"]})
    l2 = 3 if vcp["strong"] else 2 if vcp["found"] else (1 if (not pd.isna(row["SMA50"]) and row["Close"] > row["SMA50"]) else 0)
    L.append({"id": 2, "pts": l2})
    l3 = 0
    if not pd.isna(row["UPDN_RATIO"]) and row["UPDN_RATIO"] >= 1.5: l3 += 1
    if bool(row["POCKET_PIVOT"]): l3 += 1
    if not pd.isna(row["TIGHT5"]) and row["TIGHT5"] >= 3: l3 += 1
    L.append({"id": 3, "pts": min(l3, 3)})
    l4 = 0
    if m["spy_above_sma200"]: l4 += 1
    if m["spy_atr_pct"] is not None and m["spy_atr_pct"] < 1.5: l4 += 1
    sec = m["sector"]
    if sec and sec.get("ok"):
        if sec["above50"] and sec["above200"]: l4 += 1
    elif sec is None: l4 += 1
    if m["rs60"] is not None and m["rs60"] > 5 and l4 < 3: l4 += 1
    L.append({"id": 4, "pts": min(l4, 3)})
    L.append({"id": 5, "pts": 1})
    l6 = 0; r = row["RSI"]
    if not pd.isna(r) and 45 <= r <= 65: l6 += 1
    if not pd.isna(row["MACD"]) and not pd.isna(row["MACD_SIG"]) and row["MACD"] > row["MACD_SIG"]: l6 += 1
    k, kp = row["STOCH_K"], row["STOCH_K_PREV"]
    if not pd.isna(k) and not pd.isna(kp) and 20 < k < 80 and k > kp: l6 += 1
    L.append({"id": 6, "pts": min(l6, 3)})
    rr = plan["rr_potential"]
    l7 = 0 if rr is None else 3 if rr >= 3 else 2 if rr >= 2 else 1 if rr >= 1.5 else 0
    L.append({"id": 7, "pts": l7})
    d = m["earnings_days"]
    l8 = 2 if d is None else 0 if d < 7 else 1 if d < 14 else 3
    L.append({"id": 8, "pts": min(l8, 3)})
    return L, sum(x["pts"] for x in L)


def decision_from_score(total, layers):
    pts = {l["id"]: l["pts"] for l in layers}
    if pts.get(1) == 0:
        return {"label": "SWING DEĞİL — UZAK DUR", "kill": "stage", "tradeable": False}
    if total >= 18: dec = {"label": "GÜÇLÜ SWING FIRSATI", "kill": None, "tradeable": True}
    elif total >= 13: dec = {"label": "İZLE", "kill": None, "tradeable": True}
    elif total >= 8: dec = {"label": "ZAYIF / BEKLE", "kill": None, "tradeable": False}
    else: dec = {"label": "SWING DEĞİL", "kill": None, "tradeable": False}
    if pts.get(8) == 0 and total >= 18:
        dec = {"label": "İZLE — BİLANÇO RİSKİ", "kill": "earnings", "tradeable": False}
    return dec


# =========================================================================
# VERİ YAPILARI
# =========================================================================
@dataclass
class Position:
    symbol: str; entry_date: pd.Timestamp; entry: float
    stop: float; target: float; shares: float; cost: float; score: int
    risk0: float; partial_done: bool = False
    legs: list = field(default_factory=list)   # 'split' çıkışta iki yarı-bacak (½/½)
    atr_peak: float = 0.0                      # 'atr_full' çıkış: şamdan tepe (en yüksek HIGH)


@dataclass
class Trade:
    symbol: str; entry_date: pd.Timestamp; exit_date: pd.Timestamp
    entry: float; exit: float; shares: float; pnl: float; pnl_pct: float
    outcome: str; score: int; sector: str


# =========================================================================
# VERİ İNDİRME (tek sefer — grid-search bunu yeniden kullanır)
# =========================================================================
def _fetch_earnings(sym):
    try:
        df = yf.Ticker(sym).get_earnings_dates(limit=24)
        if df is None or df.empty: return []
        idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
        return sorted(pd.Timestamp(d).normalize() for d in idx)
    except Exception:
        return []


def earnings_days_until(dates, date):
    if not dates: return None
    d0 = pd.Timestamp(date).normalize(); fut = [d for d in dates if d >= d0]
    return int((fut[0] - d0).days) if fut else None


OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def heikin_ashi(d):
    """Gerçek OHLC DataFrame'inden Heikin Ashi OHLC üretir — SADECE GÖRSEL.
    Trade mantığını / veri çekmeyi ETKİLEMEZ; çağıran kod ham fiyatla devam eder.
    HA_Close=(O+H+L+C)/4 · HA_Open=(önceki HA_Open+önceki HA_Close)/2 ·
    HA_High=max(H,HA_O,HA_C) · HA_Low=min(L,HA_O,HA_C).
    İlk açılışın doğru olması için TÜM geçmişle (pencere kesilmeden) çağrılmalı."""
    o = d["Open"].to_numpy(dtype=float); h = d["High"].to_numpy(dtype=float)
    lo = d["Low"].to_numpy(dtype=float); c = d["Close"].to_numpy(dtype=float)
    n = len(d)
    ha = d.copy()
    if n == 0:
        return ha
    ha_close = (o + h + lo + c) / 4.0
    ha_open = ha_close.copy()
    ha_open[0] = (o[0] + c[0]) / 2.0
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
    ha_high = pd_np_max3(h, ha_open, ha_close)
    ha_low = pd_np_min3(lo, ha_open, ha_close)
    ha["Open"], ha["High"], ha["Low"], ha["Close"] = ha_open, ha_high, ha_low, ha_close
    return ha


def pd_np_max3(a, b, c):
    import numpy as _np
    return _np.maximum(_np.maximum(a, b), c)


def pd_np_min3(a, b, c):
    import numpy as _np
    return _np.minimum(_np.minimum(a, b), c)


def _flatten_ohlcv(df, ticker):
    """yfinance çıktısını (flat veya MultiIndex, hangi sırada olursa olsun)
    düz OHLCV sütunlarına indirger. Ticker'a ait olduğunu doğrular."""
    if df is None or df.empty:
        return None
    cols = df.columns
    fields = set(OHLCV)
    if isinstance(cols, pd.MultiIndex):
        lvl0 = set(cols.get_level_values(0))
        lvlL = set(cols.get_level_values(-1))
        if fields.issubset(lvl0):
            # ('Open','CSCO') gibi → alan adı 0. seviyede; ticker doğrula
            tk = set(cols.get_level_values(-1))
            if ticker not in tk:
                return None
            df = df.xs(ticker, axis=1, level=-1)
        elif fields.issubset(lvlL):
            # ('CSCO','Open') gibi → alan adı son seviyede
            tk = set(cols.get_level_values(0))
            if ticker not in tk:
                return None
            df = df.xs(ticker, axis=1, level=0)
        else:
            df = df.copy(); df.columns = cols.get_level_values(0)
    df = df.copy()
    if not fields.issubset(set(df.columns)):
        return None
    return df[OHLCV]


def _download_one(ticker, period, interval, timeout=20, tries=2, start=None, end=None):
    """TEK sembol indir → izole, düz OHLCV. Batch/multi-index karışması imkânsız.
    start/end verilirse period yerine tarih aralığı kullanılır.
    timeout: ağ asılmasını engeller (yfinance requests timeout); tries: kısa retry."""
    df = None
    for _ in range(tries):
        try:
            if start is not None or end is not None:
                df = yf.download(ticker, start=start, end=end, interval=interval,
                                 auto_adjust=True, progress=False, threads=False, timeout=timeout)
            else:
                df = yf.download(ticker, period=period, interval=interval,
                                 auto_adjust=True, progress=False, threads=False, timeout=timeout)
            if df is not None and not df.empty:
                break
        except Exception:
            df = None
    if df is None:
        return None
    return _flatten_ohlcv(df, ticker)


def _clean_frame(d, today):
    """Tek-sembol düz OHLCV çerçevesini temizle: gelecek-bar kes, eksik/bozuk satır at.
    Cross-fill YOK — eksik gün başka veriyle doldurulmaz."""
    if d is None or not set(OHLCV).issubset(set(d.columns)):
        return None
    d = d[OHLCV].copy()
    d = d[d.index <= today]                        # gelecek-bar kesimi
    d = d.dropna(how="any")                        # eksik gün → AT (doldurma yok)
    ok = ((d[["Open", "High", "Low", "Close"]] > 0).all(axis=1)
          & (d["High"] >= d["Low"])
          & (d["High"] >= d[["Open", "Close"]].max(axis=1))
          & (d["Low"] <= d[["Open", "Close"]].min(axis=1)))
    d = d[ok]
    return d if len(d) else None


_FMP_EOD = "https://financialmodelingprep.com/stable/historical-price-eod/full"


def _fmp_key(explicit=None):
    """FMP API anahtarı: explicit > env FMP_API_KEY > ~/.portfolio_keys.json."""
    import json as _json
    k = explicit or os.environ.get("FMP_API_KEY")
    if k:
        return k
    p = os.path.expanduser("~/.portfolio_keys.json")
    if os.path.exists(p):
        try:
            return _json.load(open(p)).get("FMP_API_KEY")
        except Exception:
            return None
    return None


def _period_to_start(period, buffer_days):
    """'2y'/'1y'/'5y'/'10y'/'6mo' → bugünden geriye başlangıç tarihi (YYYY-MM-DD)."""
    import re as _re
    m = _re.match(r"\s*(\d+)\s*(y|mo|d)", str(period or "2y"))
    if m:
        n = int(m.group(1)); u = m.group(2)
        days = n * 365 if u == "y" else (n * 30 if u == "mo" else n)
    else:
        days = 730
    start = pd.Timestamp.now().normalize() - pd.Timedelta(days=days + int(buffer_days))
    return start.strftime("%Y-%m-%d")


def _fmp_daily_one(ticker, key, dl_start, dl_end, timeout=15, tries=2):
    """Tek sembol FMP /stable EOD → düz OHLCV DataFrame (artan tarih) veya None."""
    import urllib.request as _u, urllib.parse as _up, json as _json, time as _t
    q = {"symbol": ticker, "apikey": key}
    if dl_start:
        q["from"] = dl_start
    if dl_end:
        q["to"] = dl_end
    url = _FMP_EOD + "?" + _up.urlencode(q)
    for _ in range(tries):
        try:
            req = _u.Request(url, headers={"User-Agent": "swing2/1.0"})
            with _u.urlopen(req, timeout=timeout) as r:
                raw = _json.loads(r.read().decode("utf-8"))
            if isinstance(raw, list) and raw:
                rows = [(b["date"], b.get("open"), b.get("high"), b.get("low"),
                         b.get("close"), b.get("volume") or 0) for b in raw]
                df = pd.DataFrame(rows, columns=["date"] + OHLCV)
                df["date"] = pd.to_datetime(df["date"]).dt.normalize()
                df = df.set_index("date").sort_index()
                return df[OHLCV].astype(float)
            return None
        except Exception:
            _t.sleep(0.4)
    return None


def fetch_daily_fmp(tickers, key, dl_start, dl_end, workers=8):
    """Tüm sembolleri eşzamanlı FMP'den indir → {ticker: OHLCV DataFrame | None}.
    Toplam bütçe aşılırsa asılı semboller None bırakılır (sonsuz bekleme yok)."""
    frames = {t: None for t in tickers}
    ex = _cf.ThreadPoolExecutor(max_workers=workers)
    fut = {ex.submit(_fmp_daily_one, t, key, dl_start, dl_end): t for t in tickers}
    budget = 45 + 1.2 * len(tickers)      # sn; asılı kalmayı önler
    try:
        for f in _cf.as_completed(fut, timeout=budget):
            t = fut[f]
            try:
                frames[t] = f.result()
            except Exception:
                frames[t] = None
    except _cf.TimeoutError:
        miss = [t for t, v in frames.items() if v is None]
        print(f"⚠️ FMP indirme bütçesi ({budget:.0f}s) aşıldı — eksik: {', '.join(miss[:12])}"
              + (" ..." if len(miss) > 12 else ""), flush=True)
    ex.shutdown(wait=False, cancel_futures=True)
    return frames


def build_market_from_frames(frames: dict, cfg: Config, today=None) -> dict:
    """Önceden çekilmiş HAM OHLCV çerçevelerinden ({ticker: df}) piyasa dict'i kur:
    temizle (gelecek-bar `today`'de kes) + indikatör (her sembol KENDİ serisinde, causal) +
    SPY takvimine reindex (fill YOK). İNDİRME YAPMAZ — artımlı veri deposu (qulla_paper) bunu
    kullanır: 5y yeniden indirmek yerine depodaki ham seriyi verip göstergeleri taze hesaplar."""
    today = pd.Timestamp(today).normalize() if today is not None else pd.Timestamp.now().normalize()
    etfs = sorted({SECTOR_MAP[s] for s in cfg.universe if s in SECTOR_MAP})
    spy_raw = _clean_frame(frames.get(cfg.benchmark), today)
    if spy_raw is None or len(spy_raw) < cfg.warmup_bars:
        raise SystemExit("SPY verisi yetersiz/geçersiz.")
    cal = spy_raw.index

    data, skipped, anomalies = {}, [], []
    for s in cfg.universe:
        d = _clean_frame(frames.get(s), today)
        if d is None or len(d) < cfg.warmup_bars:
            skipped.append(s); continue
        n_big = int((d["Close"].pct_change().abs() > 0.40).sum())
        if n_big: anomalies.append(f"{s}({n_big})")
        ind = add_indicators(d, cfg)               # KENDİ serisinde (causal)
        data[s] = ind.reindex(cal)                 # SPY takvimine — fill YOK

    spy = add_indicators(spy_raw, cfg)

    sectors = {}
    for e in etfs:
        d = _clean_frame(frames.get(e), today)
        if d is not None and len(d) >= 200:
            cl = d["Close"]
            sectors[e] = pd.DataFrame({"Close": cl, "SMA50": sma(cl, 50), "SMA200": sma(cl, 200)}).reindex(cal)

    earnings = {}
    if cfg.use_earnings:
        print("Earnings takvimleri çekiliyor...")
        for s in data: earnings[s] = _fetch_earnings(s)

    if skipped: print(f"Atlanan (yetersiz/geçersiz veri): {', '.join(skipped)}")
    if anomalies: print(f"⚠️ >%40 tek-gün sıçrama (split olabilir): {', '.join(anomalies)}")
    print(f"Hazır: {len(data)} hisse · {len(cal)} bar ({cal[0].date()} → {cal[-1].date()}) · sınır≤{today.date()}")
    return {"data": data, "spy": spy, "sectors": sectors, "earnings": earnings,
            "calendar": cal, "vcp_cache": {}}


def download_and_align_data(cfg: Config) -> dict:
    """Anti-contamination veri pipeline'ı:
    1) HER sembol TEK TEK indirilir (batch/multi-index karışması imkânsız) — thread'li
    2) kolonlar kesin düzleştirilir + ticker doğrulanır
    3) gelecek barlar kesilir, bozuk satırlar atılır (auto_adjust=True)
    4) indikatörler sembolün KENDİ dense serisinde; SPY takvimine reindex(fill YOK)"""
    etfs = sorted({SECTOR_MAP[s] for s in cfg.universe if s in SECTOR_MAP})
    tickers = list(dict.fromkeys(list(cfg.universe) + [cfg.benchmark] + etfs))
    today = pd.Timestamp.now().normalize()

    # ---- El ile tarih aralığı (varsa) — indirme penceresi warmup tamponuyla genişler ----
    use_dates = bool(cfg.start_date or cfg.end_date)
    dl_start = dl_end = None
    if use_dates:
        if cfg.start_date:
            dl_start = (pd.Timestamp(cfg.start_date) - pd.Timedelta(days=cfg.warmup_calendar_buffer)).strftime("%Y-%m-%d")
        if cfg.end_date:
            dl_end = (pd.Timestamp(cfg.end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")  # yf end hariç
    win_tag = f"{cfg.start_date or '_'}_{cfg.end_date or '_'}" if use_dates else cfg.period

    # ---- Disk cache (yfinance throttle'a karşı: bir kez indir, tekrar tekrar oku) ----
    cache_file = None
    if cfg.disk_cache:
        sig = hashlib.md5(("|".join(sorted(tickers)) + f"|{win_tag}|{cfg.interval}|{cfg.price_source}|ma{cfg.ma_trail_len}|{today.date()}").encode()).hexdigest()[:12]
        cache_file = os.path.join(cfg.cache_dir, f"market_{win_tag}_{sig}.pkl")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "rb") as fh:
                    m = pickle.load(fh)
                m["vcp_cache"] = {}
                print(f"Veri DİSK CACHE'ten yüklendi: {cache_file} · {len(m['data'])} hisse · {len(m['calendar'])} bar")
                return m
            except Exception as e:
                print(f"Cache okunamadı ({e}), yeniden indiriliyor...")

    # ---- İndirme ----
    frames = {}
    if cfg.price_source == "fmp":
        key = _fmp_key()
        if not key:
            raise SystemExit("FMP_API_KEY yok (~/.portfolio_keys.json veya env). "
                             "price_source='yfinance' ile yfinance'e dönebilirsin.")
        fmp_start = dl_start or _period_to_start(cfg.period, cfg.warmup_calendar_buffer)
        fmp_end = cfg.end_date or today.strftime("%Y-%m-%d")
        print(f"Veri indiriliyor (FMP /stable): {len(tickers)} sembol · {fmp_start}→{fmp_end} · "
              f"{cfg.download_workers} işçi ...", flush=True)
        # Büyük evrende eşzamanlılığı düşür (FMP bağlantı/limit sıkışmasını önler; veri aynı)
        _w = 6 if len(tickers) > 150 else cfg.download_workers
        frames = fetch_daily_fmp(tickers, key, fmp_start, fmp_end, workers=_w)
        got = sum(1 for v in frames.values() if v is not None and len(v))
        if got == 0:
            raise SystemExit("FMP indirme başarısız (anahtar/plan/ağ).")
    elif cfg.per_ticker_download:
        print(f"Veri indiriliyor (TEK TEK, izole): {len(tickers)} sembol · {win_tag} · {cfg.download_workers} işçi ...", flush=True)
        ex = _cf.ThreadPoolExecutor(max_workers=cfg.download_workers)
        fut = {ex.submit(_download_one, t, cfg.period, cfg.interval, 20, 2, dl_start, dl_end): t for t in tickers}
        budget = 60 + 6 * len(tickers)   # toplam indirme bütçesi (sn) — asılı kalmayı önler
        try:
            for f in _cf.as_completed(fut, timeout=budget):
                t = fut[f]
                try:
                    d = f.result()
                except Exception:
                    d = None
                frames[t] = d
                if cfg.debug_download and d is not None and len(d):
                    print(f"DEBUG: {t} ilk Close ({d.index[0].date()}) = {float(d['Close'].iloc[0]):.2f} · "
                          f"son ({d.index[-1].date()}) = {float(d['Close'].iloc[-1]):.2f}", flush=True)
        except _cf.TimeoutError:
            done = set(frames)
            stuck = [tt for tt in tickers if tt not in done]
            print(f"⚠️ İndirme bütçesi ({budget}s) aşıldı — asılı/eksik: {', '.join(stuck) or '-'}", flush=True)
        ex.shutdown(wait=False, cancel_futures=True)   # asılı thread'leri bekleme
    else:
        # Yedek: batch indirme. group_by="ticker" → raw[t] o sembolün düz çerçevesi.
        print(f"Veri indiriliyor (batch): {len(tickers)} sembol · {win_tag} ...", flush=True)
        raw = None
        for _ in range(3):                         # throttle/ağ hatasına karşı retry
            try:
                if use_dates:
                    raw = yf.download(tickers, start=dl_start, end=dl_end, interval=cfg.interval,
                                      auto_adjust=True, progress=False, group_by="ticker",
                                      threads=True, timeout=30)
                else:
                    raw = yf.download(tickers, period=cfg.period, interval=cfg.interval,
                                      auto_adjust=True, progress=False, group_by="ticker",
                                      threads=True, timeout=30)
                if raw is not None and not raw.empty:
                    break
            except Exception:
                raw = None
        if raw is None or raw.empty:
            raise SystemExit("Batch indirme başarısız (yfinance throttle/ağ). Sonra tekrar dene.")
        multi = isinstance(raw.columns, pd.MultiIndex)
        avail = set(raw.columns.get_level_values(0)) if multi else set()
        for t in tickers:
            if multi:
                frames[t] = _flatten_ohlcv(raw[t], t) if t in avail else None
            else:
                frames[t] = _flatten_ohlcv(raw, t)

    # ---- Temizle + hizala + indikatör (önceden-çekilmiş çerçevelerden; artımlı depo da bunu kullanır) ----
    result = build_market_from_frames(frames, cfg, today)
    if cfg.disk_cache and cache_file:
        try:
            os.makedirs(cfg.cache_dir, exist_ok=True)
            with open(cache_file, "wb") as fh:
                pickle.dump(result, fh)
            print(f"Veri DİSK CACHE'e yazıldı: {cache_file}")
        except Exception as e:
            print(f"Cache yazılamadı: {e}")
    return result


# Geriye dönük uyumluluk
def attach_watchlist(market: dict, cfg: Config) -> dict:
    """RS evren kapısını (watchlist) market dict'ine ekle. download_and_align_data ve
    build_market_from_frames watchlist ÜRETMEZ → hem load_market hem artımlı depo (qulla_paper)
    bunu çağırmalı; yoksa _in_watchlist kapısı kapanır ve YANLIŞ evren seçilir."""
    if getattr(cfg, "use_rs_universe", False):
        from rs_universe import build_watchlist
        pool = cfg.rs_pool or cfg.universe
        pool_data = {s: market["data"][s] for s in pool if s in market["data"]}
        market["watchlist"] = build_watchlist(
            pool_data, market["calendar"],
            n=cfg.rs_n, weights=cfg.rs_weights, skip=cfg.rs_skip,
            windows=cfg.rs_windows, dollar_vol_floor=cfg.rs_dollar_vol_floor)
        print(f"RS izleme listesi: {len(market['watchlist'])} gün · havuz {len(pool_data)} · top-{cfg.rs_n}", flush=True)
    else:
        market["watchlist"] = None
    return market


def load_market(cfg: Config) -> dict:
    return attach_watchlist(download_and_align_data(cfg), cfg)


# =========================================================================
# 15-DAKİKALIK INTRADAY: GÜNLÜK 15:45 ET (22:45 TR) FİYATI
# Yahoo limiti: 15dk veri YALNIZCA son ~60 gün. Her gün için 15:45 barının
# Open'ı (= tam 15:45:00 anlık fiyatı) çıkarılır → {sym: Series(date→px)}.
# =========================================================================
def fetch_intraday_1545(tickers, mark="15:45", interval="15m", lookback_days=58,
                        tz="America/New_York", workers=8, timeout=30):
    """Son ~60 günün 15dk barlarından her gün 'mark' (15:45 ET) anının fiyatını döndürür.
    Dönen: {sym: pd.Series(index=naive günlük Timestamp, value=15:45 fiyatı)}."""
    import datetime as _dt
    hh, mm = (int(x) for x in mark.split(":"))
    want = _dt.time(hh, mm)
    period = f"{min(int(lookback_days), 59)}d"

    def _one(t):
        df = None
        for _ in range(2):
            try:
                df = yf.download(t, period=period, interval=interval, auto_adjust=True,
                                 progress=False, threads=False, timeout=timeout)
                if df is not None and not df.empty:
                    break
            except Exception:
                df = None
        if df is None or df.empty:
            return t, None
        if isinstance(df.columns, pd.MultiIndex):
            try:
                df = df.xs(t, axis=1, level=-1)
            except Exception:
                df.columns = df.columns.get_level_values(0)
        if "Open" not in df.columns:
            return t, None
        idx = df.index
        idx = idx.tz_localize("UTC") if idx.tz is None else idx
        idx = idx.tz_convert(tz)
        df = df.copy(); df.index = idx
        sel = df[[ti == want for ti in df.index.time]]    # yalnız 15:45 barları
        if sel.empty:
            return t, None
        s = sel["Open"].astype(float)
        s.index = pd.DatetimeIndex([ts.normalize().tz_localize(None) for ts in s.index])  # naive gün
        s = s[~s.index.duplicated(keep="last")]
        return t, s

    print(f"15dk intraday çekiliyor: {len(tickers)} sembol · {period} · {mark} ET anı ...", flush=True)
    out, got = {}, 0
    ex = _cf.ThreadPoolExecutor(max_workers=workers)
    futs = {ex.submit(_one, t): t for t in tickers}
    try:
        for f in _cf.as_completed(futs, timeout=60 + 4 * len(tickers)):
            t, s = f.result()
            if s is not None and len(s):
                out[t] = s; got += 1
    except _cf.TimeoutError:
        print("⚠️ intraday indirme bütçesi aşıldı (kısmi sonuç).", flush=True)
    ex.shutdown(wait=False, cancel_futures=True)
    print(f"15dk hazır: {got}/{len(tickers)} sembol · gün başına 1 nokta ({mark} ET).", flush=True)
    return out


# =========================================================================
# ALPHA VANTAGE: GEÇMİŞ 15dk INTRADAY (60 gün sınırı YOK — aylık dilimler, ~20 yıl)
# TIME_SERIES_INTRADAY + month=YYYY-MM. Zaman damgası bar-SONU (US/Eastern) →
# 15:45 barının CLOSE'u = tam 15:45:00 fiyatı.  (yfinance: bar-başı Open ile aynı an.)
# =========================================================================
def _av_key(explicit=None):
    if explicit:
        return explicit
    import os, json
    k = os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("AV_API_KEY")
    if k:
        return k
    p = os.path.expanduser("~/.portfolio_keys.json")
    if os.path.exists(p):
        try:
            return json.load(open(p)).get("ALPHAVANTAGE_API_KEY")
        except Exception:
            return None
    return None


def entry_months_from_trades(trades, extra_back=1):
    """Backtest işlemlerinin giriş tarihlerinden {sembol: set('YYYY-MM')} üretir.
    extra_back: emin olmak için bir önceki ayı da ekle (ay sınırındaki günler)."""
    sm = {}
    for t in trades:
        if t.outcome == "PARTIAL":   # aynı pozisyonun girişi zaten tam-kapanışta sayılır
            pass
        d = t.entry_date
        for k in range(extra_back + 1):
            mdate = (d - pd.DateOffset(months=k))
            sm.setdefault(t.symbol, set()).add(f"{mdate.year:04d}-{mdate.month:02d}")
    return sm


def fetch_intraday_1545_av(symbol_months, mark="15:45", interval="15min",
                           adjusted=True, extended_hours=False,
                           reqs_per_min=5, api_key=None, verbose=True):
    """Alpha Vantage'ten (sembol, 'YYYY-MM') çiftleri için her gün 'mark' (15:45 ET) fiyatı.
    symbol_months: {sembol: iterable('YYYY-MM')} — yalnız gerekli ay/sembol indirilir.
    reqs_per_min : tier hız limiti (ücretsiz=5, premium=75/150/300/600/1200).
    Döner: {sembol: pd.Series(index=naive gün, value=15:45 fiyatı)}.
    Hız limiti / hata durumunda o dilim atlanır (kısmi sonuç döner)."""
    import time, io, urllib.parse, urllib.request, datetime as _dt
    key = _av_key(api_key)
    if not key:
        raise SystemExit("Alpha Vantage anahtarı yok. ~/.portfolio_keys.json içine "
                         "'ALPHAVANTAGE_API_KEY' ekle veya api_key= ver.")
    want = ":".join(f"{int(x):02d}" for x in mark.split(":"))   # '15:45' → '15:45'
    gap = 60.0 / max(1, reqs_per_min)
    base = "https://www.alphavantage.co/query"
    out, calls, hit_limit = {}, 0, False
    total = sum(len(set(ms)) for ms in symbol_months.values())
    if verbose:
        print(f"Alpha Vantage 15dk: {total} sembol-ay · ~{reqs_per_min} istek/dk · ~{total*gap/60:.1f} dk ...", flush=True)
    for sym, months in symbol_months.items():
        per_sym = {}
        for mon in sorted(set(months)):
            params = {"function": "TIME_SERIES_INTRADAY", "symbol": sym, "interval": interval,
                      "month": mon, "outputsize": "full", "datatype": "csv",
                      "adjusted": str(adjusted).lower(), "extended_hours": str(extended_hours).lower(),
                      "apikey": key}
            url = base + "?" + urllib.parse.urlencode(params)
            txt = None
            for _ in range(2):
                try:
                    with urllib.request.urlopen(url, timeout=30) as r:
                        txt = r.read().decode("utf-8", "replace")
                    break
                except Exception:
                    txt = None; time.sleep(gap)
            calls += 1
            if not txt or not txt.lstrip().lower().startswith("timestamp"):
                low = (txt or "").lower()
                if any(w in low for w in ("rate limit", "information", "premium", "thank you")):
                    hit_limit = True
                    if verbose: print(f"  ⚠️ {sym} {mon}: hız limiti/uyarı — atlandı.", flush=True)
                if calls < total: time.sleep(gap)
                continue
            try:
                df = pd.read_csv(io.StringIO(txt))
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                sel = df[df["timestamp"].dt.strftime("%H:%M") == want]
                for _, rr in sel.iterrows():
                    day = rr["timestamp"].normalize()
                    per_sym[day] = float(rr["close"])     # 15:45 barının CLOSE'u = 15:45:00 fiyatı
            except Exception:
                pass
            if calls < total: time.sleep(gap)
        if per_sym:
            s = pd.Series(per_sym).sort_index()
            s.index = pd.DatetimeIndex(s.index)
            out[sym] = s
    if verbose:
        print(f"AV 15dk hazır: {len(out)} sembol · {calls} istek" + (" · ⚠️ limit görüldü" if hit_limit else ""), flush=True)
    return out


# =========================================================================
# TIINGO: GEÇMİŞ 15dk INTRADAY (IEX) — sembol başına TEK istekle tüm tarih aralığı
# /iex/<t>/prices?resampleFreq=15min&startDate&endDate. Geçmiş ~2017'ye kadar.
# IEX barları başlangıç-etiketli → 15:45 barının OPEN'ı = 15:45:00 fiyatı.
# =========================================================================
def _tiingo_key(explicit=None):
    if explicit:
        return explicit
    import os, json
    k = os.environ.get("TIINGO_API_KEY") or os.environ.get("TIINGO_TOKEN")
    if k:
        return k
    p = os.path.expanduser("~/.portfolio_keys.json")
    if os.path.exists(p):
        try:
            d = json.load(open(p))
            return d.get("TIINGO_API_KEY") or d.get("TIINGO_TOKEN")
        except Exception:
            return None
    return None


def fetch_intraday_1545_tiingo(tickers, start, end, mark="15:45", resample="15min",
                               which="open", reqs_per_hour=None, api_key=None,
                               tz="America/New_York", workers=4, max_days_per_req=330,
                               frame=False, wait_on_limit_s=0, max_waits=40, verbose=True):
    """Tiingo IEX'ten her sembol için [start,end] 15dk barları, her gün 'mark' (15:45 ET) fiyatı.
    which: '15:45 barının' hangi alanı ('open'=başlangıç-etiketli IEX'te 15:45:00 anı).
    reqs_per_hour: ücretsiz tier ~50/sa → gap koyar; None = limitsiz (paralel).
    max_days_per_req: Tiingo istek-başı satır cap'ine karşı tarih aralığı bu kadar günlük
        dilimlere bölünür (1 yıl 15dk ≈ 6500 satır < cap). Her sembol = birkaç istek.
    frame=False: {sembol: Series(date→15:45 HAM fiyatı)}.
    frame=True : {sembol: DataFrame[['p1545','rclose']]} — p1545=15:45 ham, rclose=o günün
        ham kapanışı (son bar). Ayarlı bazına çevirmek için: adj = p1545 × (yf_adjclose/rclose).
    NOT: Tiingo IEX fiyatları HAM (split/temettü ayarsız). yfinance günlük AYARLI → bazları
        eşitlemeden karşılaştırma yanlıştır (bkz. adjust_px1545_to_daily)."""
    import urllib.request, urllib.parse, json as _json, time
    key = _tiingo_key(api_key)
    if not key:
        raise SystemExit("Tiingo anahtarı yok. ~/.portfolio_keys.json içine 'TIINGO_API_KEY' ekle.")
    want = ":".join(f"{int(x):02d}" for x in mark.split(":"))
    gap = (3600.0 / reqs_per_hour) if reqs_per_hour else 0.0
    state = {"rate_limited": False}

    s0, e0 = pd.Timestamp(start), pd.Timestamp(end)
    chunks, a = [], s0
    while a <= e0:
        b = min(a + pd.Timedelta(days=max_days_per_req - 1), e0)
        chunks.append((a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")))
        a = b + pd.Timedelta(days=1)

    def _fetch(t, sd, ed):
        url = f"https://api.tiingo.com/iex/{urllib.parse.quote(t)}/prices?" + urllib.parse.urlencode({
            "startDate": sd, "endDate": ed, "resampleFreq": resample,
            "columns": "open,high,low,close,volume", "token": key})
        waits = 0
        while True:
            try:
                req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=40) as r:
                    return _json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                if e.code == 429:                     # saatlik kota doldu
                    if wait_on_limit_s and waits < max_waits:
                        waits += 1
                        print(f"  ⏳ 429 — {wait_on_limit_s}s bekle ve tekrar dene ({waits}/{max_waits})...", flush=True)
                        time.sleep(wait_on_limit_s); continue
                    state["rate_limited"] = True
                    return "RATE_LIMIT"
                time.sleep(1.0); return None
            except Exception:
                time.sleep(1.0); return None

    def _one(t):
        if state["rate_limited"]:
            return t, None
        rows = []
        for (sd, ed) in chunks:
            d = _fetch(t, sd, ed)
            if d == "RATE_LIMIT":
                return t, None
            if d:
                rows.extend(d)
            if gap and len(chunks) > 1:
                time.sleep(gap)
        if not rows:
            return t, None
        df = pd.DataFrame(rows)
        if "date" not in df.columns:
            return t, None
        ts = pd.to_datetime(df["date"], utc=True).dt.tz_convert(tz)
        df = df.assign(_day=[x.normalize().tz_localize(None) for x in ts],
                       _hm=ts.dt.strftime("%H:%M").values)
        m = df["_hm"].values == want
        if not m.any():
            return t, None
        col = which if which in df.columns else "open"
        p1545 = pd.Series(df[col].values[m].astype(float),
                          index=pd.DatetimeIndex(df["_day"].values[m]))
        p1545 = p1545[~p1545.index.duplicated(keep="last")].sort_index()
        if not frame:
            return t, p1545
        rclose = df.sort_values("date").groupby("_day")["close"].last().astype(float)  # ham günlük kapanış
        out_df = pd.DataFrame({"p1545": p1545, "rclose": rclose}).dropna(subset=["p1545"])
        return t, out_df

    out, got = {}, 0
    tickers = list(dict.fromkeys(tickers))
    n_req = len(tickers) * len(chunks)
    if verbose:
        est = (n_req * gap / 60.0) if gap else 0.0
        print(f"Tiingo 15dk: {len(tickers)} sembol × {len(chunks)} dilim = {n_req} istek · "
              f"{start}→{end} · {resample} · "
              f"{'limitsiz (paralel)' if not gap else f'~{reqs_per_hour}/sa (~{est:.0f} dk)'} ...", flush=True)
    if gap:                                   # hız-limitli → sıralı + gap
        for i, t in enumerate(tickers, 1):
            tt, s = _one(t)
            if s is not None and len(s):
                out[tt] = s; got += 1
    else:                                     # limitsiz → paralel
        ex = _cf.ThreadPoolExecutor(max_workers=workers)
        futs = {ex.submit(_one, t): t for t in tickers}
        try:
            for f in _cf.as_completed(futs, timeout=120 + 4 * n_req):
                tt, s = f.result()
                if s is not None and len(s):
                    out[tt] = s; got += 1
        except _cf.TimeoutError:
            print("⚠️ Tiingo indirme bütçesi aşıldı (kısmi).", flush=True)
        ex.shutdown(wait=False, cancel_futures=True)
    if verbose:
        warn = "  ⚠️ HTTP 429 — saatlik kota doldu (kısmi sonuç). ~1 saat sonra tekrar dene." if state["rate_limited"] else ""
        print(f"Tiingo 15dk hazır: {got}/{len(tickers)} sembol · gün başına 1 nokta ({mark} ET).{warn}", flush=True)
    return out


def adjust_px1545_to_daily(frames, market, calib=False):
    """Tiingo HAM 15:45 fiyatını yfinance AYARLI günlük bazına çevirir.
    frames: fetch_intraday_1545_tiingo(..., frame=True) çıktısı {sym: DF[['p1545','rclose']]}.
    Her gün faktör = yf_adjclose / tiingo_rclose → adj_1545 = p1545 × faktör.
    Döner: {sym: Series(date→AYARLI 15:45 fiyatı)}  (engine'in px1545'i bunu bekler).
    calib=True ise ayrıca (adj_1545 / yf_close − 1) bps listesini döndürür (2. eleman)."""
    data = market["data"]; out = {}; gaps = []
    for sym, df in frames.items():
        dd = data.get(sym)
        if dd is None or df is None or not len(df):
            continue
        adj = {}
        for d, r in df.iterrows():
            if d not in dd.index:
                continue
            yc = dd.loc[d, "Close"]
            rc, p = r.get("rclose"), r.get("p1545")
            if pd.isna(yc) or pd.isna(rc) or pd.isna(p) or rc == 0:
                continue
            factor = yc / rc                       # ham → ayarlı (split+temettü)
            a = float(p) * factor
            adj[d] = a
            if calib:
                gaps.append((a / yc - 1) * 1e4)    # ayarlı 15:45 vs ayarlı kapanış (bps)
        if adj:
            out[sym] = pd.Series(adj).sort_index()
    return (out, gaps) if calib else out


# =========================================================================
# SİMÜLATÖR
# =========================================================================
class Swing2Backtester:
    def __init__(self, cfg: Config, market: dict | None = None):
        self.cfg = cfg
        self.market = market if market is not None else load_market(cfg)
        self.data = self.market["data"]; self.spy = self.market["spy"]
        self.sectors = self.market["sectors"]; self.earnings = self.market["earnings"]
        self.calendar = self.market["calendar"]; self.vcp_cache = self.market["vcp_cache"]
        self.watchlist = self.market.get("watchlist")   # {date→set} veya None
        self.cash = cfg.initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_curve = []
        self._slip = cfg.slippage_bps / 10_000.0
        self._entry_slip = cfg.entry_slippage_bps / 10_000.0   # girişe özel (kapanış oynaklığı)
        self._stop_slip = cfg.stop_slippage_bps / 10_000.0
        self.px1545 = self.market.get("px1545", {})            # {sym: Series(date→gerçek 15:45 fiyatı)}

    def _in_watchlist(self, sym, date):
        """RS evreni açıkken yalnız o günün top-N listesindeki semboller YENİ pozisyon açabilir.
        Kapalıysa daima True (eski statik-evren davranışı). Çıkışları ASLA kapılamaz."""
        if not getattr(self.cfg, "use_rs_universe", False) or self.watchlist is None:
            return True
        return sym in self.watchlist.get(date, set())

    # ---- piyasa bağlamı --------------------------------------------------
    def _common(self, date):
        s = self.spy.loc[date]
        _ratr = s.get("ATR20_PCT")   # eski disk-cache'lerde olmayabilir → güvenli erişim
        return {"spy_above_sma200": bool((not pd.isna(s["SMA200"])) and s["Close"] > s["SMA200"]),
                "spy_atr_pct": None if pd.isna(s["ATR_PCT"]) else float(s["ATR_PCT"]),
                "spy_regime_atr_pct": None if (_ratr is None or pd.isna(_ratr)) else float(_ratr),
                "spy_ret60": None if pd.isna(s["RET60"]) else float(s["RET60"])}

    def _vol_regime_locked(self, common):
        """ATR-REJİM kilidi (hard-switch): SPY 20g ATR% eşiği aşarsa piyasa aşırı
        çalkantılı/testere → YENİ İŞLEM AÇILMAZ. Filtre kapalıysa (vars.) daima False."""
        if not self.cfg.regime_atr_filter:
            return False
        v = common.get("spy_regime_atr_pct")
        return v is not None and v > self.cfg.regime_atr_threshold

    def _mctx(self, sym, row, date, common):
        etf = SECTOR_MAP.get(sym); sec = None
        if etf is None: sec = None
        elif etf in self.sectors:
            sr = self.sectors[etf].loc[date]
            sec = ({"ok": True, "above50": bool(sr["Close"] > sr["SMA50"]), "above200": bool(sr["Close"] > sr["SMA200"])}
                   if not pd.isna(sr["SMA50"]) and not pd.isna(sr["SMA200"]) else {"ok": False})
        else: sec = {"ok": False}
        rs60 = (float(row["RET60"]) - common["spy_ret60"]) if (not pd.isna(row["RET60"]) and common["spy_ret60"] is not None) else None
        ed = earnings_days_until(self.earnings.get(sym, []), date) if self.cfg.use_earnings else None
        return {**common, "sector": sec, "rs60": rs60, "earnings_days": ed}

    def _vcp(self, sym, df, date):
        key = (sym, date)
        if key not in self.vcp_cache:
            loc = df.index.get_loc(date)
            # No-fill hizalama sonrası pencere NaN (işlem görmeyen gün) içerebilir → at
            window = df.iloc[max(0, loc - 79):loc + 1].dropna(subset=["Close", "Volume"])
            self.vcp_cache[key] = detect_vcp(window) if len(window) >= 4 else {"found": False, "strong": False}
        return self.vcp_cache[key]

    # ---- pozisyon yönetimi (trailing + kısmi + stop/hedef) ---------------
    def _manage(self, date):
        cfg = self.cfg
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            if date == pos.entry_date: continue
            row = self.data[sym].loc[date]
            op, low, high, close, atr_v = row["Open"], row["Low"], row["High"], row["Close"], row["ATR"]
            if pd.isna(low) or pd.isna(high): continue

            # ===== v6: BÖLÜNMÜŞ ÇIKIŞ (½ + ½, iki bağımsız atomik kural) =====
            if cfg.exit_mode == "split":
                self._manage_split(sym, pos, date, row); continue
            # ===== /v6 =====

            # ===== v6b: TAM POZİSYON ATR-TRAIL (şamdan; partial yok) =====
            if cfg.exit_mode == "atr_full":
                if pos.atr_peak <= 0: pos.atr_peak = pos.entry
                if not pd.isna(high): pos.atr_peak = max(pos.atr_peak, high)
                if not pd.isna(atr_v) and not pd.isna(close) and close < pos.atr_peak - cfg.atr_trail_mult * atr_v:
                    self._close(sym, date, close, "ATR", slip=self._stop_slip)
                continue
            # ===== /v6b =====

            # ===== v7: ATR-REJİM ÇIKIŞI (saf ATR — sabit kâr-al / zarar-kes, trailing YOK) =====
            # Stop/target girişte ATR0'dan SABİTLENDİ (pos.stop/pos.target). Pozisyon bölünmez;
            # fiyat ya sabit hedefe ya sabit stopa değene kadar beklenir (gürültüden uzak).
            if cfg.exit_mode == "atr_regime":
                if low <= pos.stop:                                    # zarar-kes (gün-içi market)
                    fill = op if (cfg.gap_fills and not pd.isna(op) and op < pos.stop) else pos.stop
                    self._close(sym, date, fill, "STOP", slip=self._stop_slip); continue
                if high >= pos.target:                                 # kâr-al (gün-içi limit)
                    fill = op if (cfg.gap_fills and not pd.isna(op) and op > pos.target) else pos.target
                    self._close(sym, date, fill, "TARGET", slip=self._slip)
                continue
            # ===== /v7 =====

            # ===== v4: 8-MA TRAILING ÇIKIŞ MODU =====
            if cfg.exit_mode == "ma_trail":
                ma = row["EMA8" if cfg.ma_trail_type == "ema" else "SMA8"]
                # a) İlk koruma stopu (felaket-zemini, gün-içi market emri)
                if cfg.ma_keep_initial_stop and low <= pos.stop:
                    fill = op if (cfg.gap_fills and not pd.isna(op) and op < pos.stop) else pos.stop
                    self._close(sym, date, fill, "STOP", slip=self._stop_slip); continue
                # b) İsteğe bağlı kısmi kâr (runner modeli) — limit emri
                if cfg.partial_tp and not pos.partial_done:
                    pt = pos.entry + pos.risk0 * cfg.partial_rr
                    if high >= pt:
                        fill = op if (cfg.gap_fills and not pd.isna(op) and op > pt) else pt
                        self._sell_partial(sym, date, fill, cfg.partial_pct); pos.partial_done = True
                # c) 8-MA çıkışı
                if sym in self.positions and not pd.isna(ma):
                    if cfg.ma_confirm_close:
                        if close < ma:   # günü MA altında kapattı → MOC ile çık
                            self._close(sym, date, close, "MA8", slip=self._stop_slip)
                    elif low <= ma:      # gün-içi MA'ya değdi → MA fiyatından çık
                        fill = op if (cfg.gap_fills and not pd.isna(op) and op < ma) else ma
                        self._close(sym, date, fill, "MA8", slip=self._stop_slip)
                continue
            # ===== /v4 =====

            # ===== v5: 8-EMA SABİT STOP + TP-MODU GRID =====
            if cfg.exit_mode == "tp_grid":
                ema8, ema21 = row["EMA8"], row["EMA21"]
                rsi_v = row["RSI"]
                kk, dd_ = row["STOCH_K"], row["STOCH_D"]
                kp, dp = row["STOCH_K_PREV"], row["STOCH_D_PREV"]

                def _ma_break(ma):  # 8/21-EMA kırılımı (kapanış-teyidi opsiyonlu)
                    if pd.isna(ma): return False
                    return (close < ma) if cfg.ma_confirm_close else (low <= ma)

                def _ma_fill(ma):   # kırılımda gerçekçi dolum fiyatı
                    if cfg.ma_confirm_close: return close
                    return op if (cfg.gap_fills and not pd.isna(op) and op < ma) else ma

                # ---- D) HYBRID_TREND: 50% 8-EMA gövde + 50% 21-EMA gövde (sabit TP yok) ----
                if cfg.tp_mode == "HYBRID_TREND":
                    if not pos.partial_done and _ma_break(ema8):      # ilk yarı 8-EMA'da
                        self._sell_partial(sym, date, _ma_fill(ema8), 0.5); pos.partial_done = True
                    if sym in self.positions and _ma_break(ema21):    # gövde yarısı 21-EMA'da
                        self._close(sym, date, _ma_fill(ema21), "EMA21", slip=self._stop_slip)
                    continue

                # ---- D2) HYBRID_TREND2: 8-EMA(KAPANIŞ) %50 + runner BE-kilidi/21-EMA + LOW10 felaket stopu ----
                # Kurallar (kullanıcı tanımı):
                #  • İlk %50 SADECE 8-EMA altında KAPANIŞ ile satılır (gün-içi iğne elemez).
                #  • Felaket stopu (LOW10/ATR plan stopu) gün-içi İĞNEDE (touch) aktif kalır.
                #  • İlk %50 satılınca kalan runner'ın stopu giriş fiyatına (BREAKEVEN) çekilir;
                #    runner ya BE'ye değince (gün-içi) ya da 21-EMA altında KAPANINCA çıkar.
                if cfg.tp_mode == "HYBRID_TREND2":
                    # 0) Stop (gün-içi touch): partial öncesi=felaket(LOW10), sonrası=breakeven(giriş)
                    if not pd.isna(pos.stop) and low <= pos.stop:
                        fill = op if (cfg.gap_fills and not pd.isna(op) and op < pos.stop) else pos.stop
                        self._close(sym, date, fill, ("BE" if pos.partial_done else "STOP"),
                                    slip=self._stop_slip); continue
                    # 1) İlk %50: yalnız 8-EMA altında KAPANIŞ → sat + stopu breakeven'a çek
                    if not pos.partial_done:
                        if not pd.isna(ema8) and close < ema8:
                            self._sell_partial(sym, date, close, 0.5); pos.partial_done = True
                            pos.stop = max(pos.stop, pos.entry)       # kâr kilidi: runner stop = giriş
                        continue
                    # 2) Runner (%50): 21-EMA altında KAPANINCA çık (BE stopu yukarıda kontrol edildi)
                    if not pd.isna(ema21) and close < ema21:
                        self._close(sym, date, close, "EMA21", slip=self._stop_slip)
                    continue

                # ---- Diğer modlar: ÖNCE 8-EMA stop (koruma + süren stop) ----
                if _ma_break(ema8):
                    self._close(sym, date, _ma_fill(ema8), "EMA8", slip=self._stop_slip); continue

                # ---- A) RR_BASED: kısmi @partial_rr, kalan rr_target hedefi ----
                if cfg.tp_mode == "RR_BASED":
                    if cfg.partial_tp and not pos.partial_done:
                        pt = pos.entry + pos.risk0 * cfg.partial_rr
                        if high >= pt:
                            fill = op if (cfg.gap_fills and not pd.isna(op) and op > pt) else pt
                            self._sell_partial(sym, date, fill, cfg.partial_pct); pos.partial_done = True
                    if sym in self.positions:
                        tgt = pos.entry + pos.risk0 * cfg.rr_target
                        if high >= tgt:
                            fill = op if (cfg.gap_fills and not pd.isna(op) and op > tgt) else tgt
                            self._close(sym, date, fill, "TP", slip=self._slip)

                # ---- B) MOMENTUM_OSCILLATOR: RSI aşırı-alım veya Stoch>80 aşağı kesişim ----
                elif cfg.tp_mode == "MOMENTUM_OSCILLATOR":
                    rsi_hot = (not pd.isna(rsi_v)) and rsi_v >= cfg.rsi_overbought_limit
                    stoch_cross = (not pd.isna(kp) and not pd.isna(dp) and not pd.isna(kk)
                                   and not pd.isna(dd_) and kp >= 80 and kp > dp and kk < dd_)
                    if (rsi_hot or stoch_cross) and close > pos.entry:   # 'kârla kapat'
                        self._close(sym, date, close, "MOM", slip=self._slip)

                # ---- C) ATR_CLIMAX: 8-EMA'dan yukarı aşırı sapma → kâr al ----
                elif cfg.tp_mode == "ATR_CLIMAX":
                    if (not pd.isna(ema8) and not pd.isna(atr_v)
                            and close > ema8 + cfg.climax_atr_mult * atr_v and close > pos.entry):
                        self._close(sym, date, close, "CLIMAX", slip=self._slip)
                continue
            # ===== /v5 =====

            # 1) Trailing stop (yalnız yukarı ratchet, +trail_after_r sonrası)
            if cfg.trailing_stop and not pd.isna(atr_v) and close >= pos.entry + cfg.trail_after_r * pos.risk0:
                new_stop = close - cfg.atr_trail_mult * atr_v
                if new_stop > pos.stop: pos.stop = new_stop

            # 2) Hard stop (muhafazakâr: önce stop) — market emri, gap'te açılıştan dol
            if low <= pos.stop:
                fill = op if (cfg.gap_fills and not pd.isna(op) and op < pos.stop) else pos.stop
                self._close(sym, date, fill, "STOP" if pos.stop < pos.entry else "TRAIL", slip=self._stop_slip)
                continue

            # 3) Kısmi kâr alma (1:partial_rr) — limit emri, gap-up'ta açılıştan dol
            if cfg.partial_tp and not pos.partial_done:
                pt = pos.entry + pos.risk0 * cfg.partial_rr
                if high >= pt:
                    fill = op if (cfg.gap_fills and not pd.isna(op) and op > pt) else pt
                    self._sell_partial(sym, date, fill, cfg.partial_pct)
                    pos.partial_done = True
                    # Kısmi sonrası koruma stopu: agresif (girişe) vs yarı-risk (nefes payı)
                    if cfg.breakeven_mode == "half_risk":
                        be = pos.entry - pos.risk0 / 2.0   # Entry − Risk/2 (retest marjı)
                    else:                                  # 'strict_entry'
                        be = pos.entry                      # tam giriş (mevcut agresif kural)
                    pos.stop = max(pos.stop, be)

            # 4) Ana hedef (kalan pozisyon) — limit emri, gap-up'ta açılıştan dol
            if sym in self.positions and high >= self.positions[sym].target:
                tgt = self.positions[sym].target
                fill = op if (cfg.gap_fills and not pd.isna(op) and op > tgt) else tgt
                self._close(sym, date, fill, "TP", slip=self._slip)

    def _sell_partial(self, sym, date, price, frac, slip=None):
        cfg = self.cfg; pos = self.positions[sym]
        sell_sh = pos.shares * frac
        fill = price * (1 - (self._slip if slip is None else slip))
        proceeds = sell_sh * fill - cfg.commission_per_trade
        cost_part = pos.cost * frac
        self.cash += proceeds
        self.trades.append(Trade(sym, pos.entry_date, date, pos.entry, fill, sell_sh,
                                 proceeds - cost_part, (fill / pos.entry - 1) * 100,
                                 "PARTIAL", pos.score, SECTOR_MAP.get(sym, "—")))
        pos.shares -= sell_sh; pos.cost -= cost_part

    def _close(self, sym, date, price, outcome, slip=None):
        cfg = self.cfg; pos = self.positions.pop(sym)
        fill = price * (1 - (self._slip if slip is None else slip))
        proceeds = pos.shares * fill - cfg.commission_per_trade
        self.cash += proceeds
        self.trades.append(Trade(sym, pos.entry_date, date, pos.entry, fill, pos.shares,
                                 proceeds - pos.cost, (fill / pos.entry - 1) * 100,
                                 outcome, pos.score, SECTOR_MAP.get(sym, "—")))

    # ---- v6: BÖLÜNMÜŞ ÇIKIŞ yardımcıları ----
    def _build_split_legs(self, tag, rule, param, shares, cost, fill):
        """Bir yarı için bacak(lar) üret. 'hybrid' = o yarıyı kendi içinde 8-EMA / 21-EMA
        runner olarak ikiye böler (HYBRID_TREND mantığı); diğer kurallar tek bacak."""
        if rule == "hybrid":
            return [
                {"tag": tag, "rule": "ema8",  "param": 0, "shares": shares / 2, "cost": cost / 2, "peak": fill},
                {"tag": tag, "rule": "ema21", "param": 0, "shares": shares - shares / 2, "cost": cost - cost / 2, "peak": fill},
            ]
        return [{"tag": tag, "rule": rule, "param": param, "shares": shares, "cost": cost, "peak": fill}]

    def _close_leg(self, sym, pos, leg, date, price, label, slip=None):
        """Bir yarı-bacağı kapat: işlem kaydı + nakit + pozisyon toplamından düş.
        İki bacak da bittiğinde pozisyon silinir."""
        cfg = self.cfg
        fill = price * (1 - (self._slip if slip is None else slip))
        proceeds = leg["shares"] * fill - cfg.commission_per_trade
        self.cash += proceeds
        self.trades.append(Trade(sym, pos.entry_date, date, pos.entry, fill, leg["shares"],
                                 proceeds - leg["cost"], (fill / pos.entry - 1) * 100,
                                 f"{leg['tag']}:{label}", pos.score, SECTOR_MAP.get(sym, "—")))
        pos.shares -= leg["shares"]; pos.cost -= leg["cost"]; leg["shares"] = 0.0

    def _split_leg_exit(self, leg, pos, row):
        """Atomik kural değerlendir. Tetiklenirse (fill, etiket, market_mi) döndür; yoksa None.
        Kapanış-teyitli kurallar (ema/ma/atr_trail) close ile çıkar (market); 'target' limittir."""
        cfg = self.cfg
        rule = leg["rule"]; p = leg["param"]
        close, high, op, atr_v = row["Close"], row["High"], row["Open"], row["ATR"]
        if rule in ("ema8", "ema21", "ma10", "ma20", "ma50"):
            col = {"ema8": "EMA8", "ema21": "EMA21", "ma10": "SMA10", "ma20": "SMA20", "ma50": "SMA50"}[rule]
            ma = row.get(col)
            if ma is not None and not pd.isna(ma) and close < ma:
                return (close, col.replace("SMA", "MA"), True)         # kapanış altında → market çıkış
            return None
        if rule == "target":
            r = p if p > 0 else 2.0
            tgt = pos.entry + r * pos.risk0
            if not pd.isna(high) and high >= tgt:
                fill = op if (cfg.gap_fills and not pd.isna(op) and op > tgt) else tgt
                return (fill, f"+{r:g}R", False)                       # limit emir
            return None
        if rule == "atr_trail":
            m = p if p > 0 else 2.5
            if not pd.isna(high):
                leg["peak"] = max(leg["peak"], high)                   # şamdan tepe (en yüksek HIGH)
            if not pd.isna(atr_v) and not pd.isna(close) and close < leg["peak"] - m * atr_v:
                return (close, f"ATR{m:g}x", True)
            return None
        return None

    def _manage_split(self, sym, pos, date, row):
        """İki yarı-bacağı bağımsız yönet. Ortak felaket stopu YOK — her bacak kendi kuralıyla."""
        for leg in pos.legs:
            if leg["shares"] <= 0:
                continue
            res = self._split_leg_exit(leg, pos, row)
            if res is not None:
                fill, label, market = res
                self._close_leg(sym, pos, leg, date, fill, label,
                                slip=(self._stop_slip if market else self._slip))
        if all(l["shares"] <= 0 for l in pos.legs):
            self.positions.pop(sym, None)

    def _size(self, date):
        eq = self._equity(date) if self.cfg.compounding else self.cfg.initial_capital
        return eq * self.cfg.max_position_pct

    def _qswing_entry_ok(self, row, spy_ret60):
        """Qullamaggie kırılım girişi. Geçerse görece-güç (RS) sıralama değerini, yoksa None döndürür.
        (Trend ön-filtreleri çağrı yerinde: rejim açık + fiyat>SMA20/50/200 + SLOPE200>0 = Aşama 2.)"""
        cfg = self.cfg
        c = row["Close"]; hi52 = row["HIGH52"]; r60 = row["RET60"]
        h = row.get(f"HIGH_PRIOR_{cfg.qswing_breakout_lb}")
        if h is None:
            h = row["HIGH_PRIOR"]
        if pd.isna(h) or pd.isna(hi52) or pd.isna(r60):
            return None
        if c <= h:                                   # N-gün tepe kırılımı (yeni alan)
            return None
        if c < cfg.qswing_near_high * hi52:          # 52H zirveye yakınlık
            return None
        if cfg.qswing_vdu_max < 9.0:                 # hacim kuruması şartı (açıksa)
            vdu = row["VDU"]
            if pd.isna(vdu) or vdu > cfg.qswing_vdu_max:
                return None
        sp = spy_ret60 if (spy_ret60 is not None and not pd.isna(spy_ret60)) else 0.0
        rs = r60 - sp                                # 60-gün görece güç (SPY'a karşı)
        if r60 <= 0 or rs < cfg.qswing_rs_min:       # pozitif momentum + RS eşiği
            return None
        return float(rs)

    def _open(self, sym, date, row, plan, score):
        cfg = self.cfg
        if plan["risk"] <= 0: return False
        base = plan["entry"]                              # plan girişi = T-Close
        if cfg.entry_fill_mode == "real_1545":
            rp = self.px1545.get(sym)
            v = rp.get(date) if rp is not None else None  # o güne ait GERÇEK 15:45 fiyatı
            if v is not None and not pd.isna(v):
                base = float(v)                           # gerçek intraday 15:45 dolum
            elif not pd.isna(row["Open"]):
                base = row["Open"] + cfg.preclose_frac * (plan["entry"] - row["Open"])  # eksikse proxy
        elif cfg.entry_fill_mode == "preclose":
            op = row["Open"]
            if not pd.isna(op):
                base = op + cfg.preclose_frac * (plan["entry"] - op)  # 15:45 ET proxy
        fill = base * (1 + self._entry_slip)              # girişe özel 8bps (kapanış anı)
        # ---- Pozisyon boyutlandırma ----
        eq = self._equity(date) if cfg.compounding else cfg.initial_capital
        cap = eq * cfg.max_position_pct                   # poz tavanı (her iki modda)
        if cfg.exit_mode == "atr_regime":
            # SABİT-DOLAR RİSK: lot = 1000$ / (giriş − ATR-stop mesafesi); stop = entry − atr_stop_mult×ATR0
            atr0 = row["ATR"]
            a_stop = (fill - cfg.atr_stop_mult * atr0) if (not pd.isna(atr0) and atr0 > 0) else plan["stop"]
            if a_stop >= fill: a_stop = plan["stop"]
            rps = fill - a_stop
            if rps <= 0: return False
            shares = cfg.risk_per_trade_usd / rps
            size = shares * fill + cfg.commission_per_trade
            if size > cap:                                # poz tavanını aşarsa kırp (aşırı kaldıraç koruması)
                size = cap; shares = (size - cfg.commission_per_trade) / fill
        elif cfg.sizing_mode == "risk":
            # ilk stop referansı: 8-EMA modlarında 8-EMA, diğerlerinde plan stop (LOW10/ATR)
            sref = row["EMA8"] if cfg.exit_mode == "tp_grid" else plan["stop"]
            if pd.isna(sref) or sref >= fill: sref = plan["stop"]
            rps = fill - sref                             # lot başına dolar risk
            if rps <= 0: return False
            shares = (eq * cfg.risk_per_trade_pct / 100.0) / rps
            size = shares * fill + cfg.commission_per_trade
            if size > cap:                                # poz tavanını aşarsa kırp
                size = cap; shares = (size - cfg.commission_per_trade) / fill
        else:
            size = cap                                    # sabit: sermaye × poz%
            shares = (size - cfg.commission_per_trade) / fill
        if self.cash < size or shares <= 0: return False
        self.cash -= size
        pos = Position(sym, date, fill, plan["stop"], plan["target"],
                       shares, size, score, risk0=fill - plan["stop"])
        if cfg.exit_mode == "atr_regime":
            # girişte SABİT ATR seviyeleri (ATR0 = giriş barı ATR'si, nedensel)
            atr0 = row["ATR"]
            if not pd.isna(atr0) and atr0 > 0:
                pos.stop = fill - cfg.atr_stop_mult * atr0
                pos.target = fill + cfg.atr_target_mult * atr0
                pos.risk0 = fill - pos.stop
        if cfg.exit_mode == "split":
            ra = cfg.split_ratio
            sa, ca = shares * ra, size * ra
            pos.legs = (self._build_split_legs("A", cfg.split_a, cfg.split_a_param, sa, ca, fill)
                        + self._build_split_legs("B", cfg.split_b, cfg.split_b_param, shares - sa, size - ca, fill))
        self.positions[sym] = pos
        return True

    def _equity(self, date):
        eq = self.cash
        for sym, pos in self.positions.items():
            px = self.data[sym].loc[date, "Close"]
            eq += pos.shares * (px if not pd.isna(px) else pos.entry)
        return eq

    # ---- ANA DÖNGÜ -------------------------------------------------------
    def _slot_count(self):
        """Aktif slot sayısı. free_runner_slots açıksa +2R (A) yarısı çıkmış 'runner-only'
        pozisyonlar slotu işgal etmez → boşalan sermaye yeni girişe konuşlanabilir.
        Kapalıyken (varsayılan) klasik davranış: her açık pozisyon = 1 slot."""
        if not getattr(self.cfg, "free_runner_slots", False):
            return len(self.positions)
        n = 0
        for pos in self.positions.values():
            legs = getattr(pos, "legs", None)
            if legs:
                if any(l["tag"] == "A" and l["shares"] > 0 for l in legs):
                    n += 1        # hedef (A) bacağı hâlâ açık → tam slot
            else:
                n += 1            # split olmayan pozisyon = 1 slot
        return n

    def _step(self, date):
        """Tek işlem gününü işle: çıkış yönetimi + (rejim açıksa) yeni girişler + equity kaydı.
        Hem toplu backtest (run) hem ARTIMLI defter (qulla_paper) bu metodu kullanır →
        strateji mantığı tek yerde, defter ile backtest birebir aynı kuralı çalıştırır."""
        cfg = self.cfg
        self._manage(date)
        common = self._common(date)
        # ATR-REJİM kilidi: SPY oynaklığı eşiği aşarsa (testere) bu bar YENİ alım YOK
        if (common["spy_above_sma200"] and not self._vol_regime_locked(common)
                and self._slot_count() < cfg.max_positions and self.cash >= self._size(date)):
            cands = []
            qmode = cfg.entry_mode == "qswing_breakout"
            spy_ret60 = self.spy.loc[date, "RET60"] if qmode else None
            for sym, df in self.data.items():
                if sym in self.positions: continue
                if not self._in_watchlist(sym, date): continue   # v6: RS evren kapısı
                row = df.loc[date]
                if (pd.isna(row["Close"]) or pd.isna(row["SMA200"]) or row["Close"] <= row["SMA200"]
                        or row["Close"] <= row["SMA50"] or row["Close"] <= row["SMA20"]
                        or pd.isna(row["SLOPE200"]) or row["SLOPE200"] <= 0): continue
                plan = compute_trade_plan(row, cfg)
                dist = (row["Close"] - row["SMA20"]) / row["SMA20"]
                if qmode:
                    # ----- qswing GİRİŞ: Qullamaggie kırılım (20g tepe + 52H yakın + SPY'ı geçen momentum) -----
                    rs = self._qswing_entry_ok(row, spy_ret60)
                    if rs is None: continue
                    # 0–100 öncelik skoru (canlı tarayıcıyla AYNI formül) → filtre + sıralama
                    _risk = plan["entry"] - plan["stop"]
                    _rec = {"rs": rs,
                            "dist_52h_pct": (row["Close"] / row["HIGH52"] - 1) * 100,
                            "dist_sma20_pct": dist * 100,
                            "risk_pct": (_risk / plan["entry"] * 100) if plan["entry"] else None}
                    qscore, _ = _qswing_priority_score(_rec)
                    if cfg.qswing_min_score > 0 and qscore < cfg.qswing_min_score: continue
                    cands.append((qscore, -dist, sym, row, plan))
                else:
                    # ----- swing2 GİRİŞ: 8-katman skor + kill-switch -----
                    stage = detect_stage(row); vcp = self._vcp(sym, df, date)
                    mctx = self._mctx(sym, row, date, common)
                    layers, total = score_layers(row, stage, vcp, plan, mctx)
                    dec = decision_from_score(total, layers)
                    if total < cfg.min_score: continue
                    if cfg.require_not_killswitch and not dec["tradeable"]: continue
                    if cfg.max_dist_sma20 > 0 and dist > cfg.max_dist_sma20: continue  # aşırı uzama (chase) kapısı
                    cands.append((total, -dist, sym, row, plan))
            cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
            for total, _nd, sym, row, plan in cands:
                if self._slot_count() >= cfg.max_positions or self.cash < self._size(date): break
                self._open(sym, date, row, plan, total)
        self.equity_curve.append((date, self._equity(date)))

    def run(self):
        cfg = self.cfg
        cal = self.calendar
        # İşlem penceresi: warmup sonrası + (varsa) el ile [start_date, end_date]
        start = cfg.warmup_bars
        if cfg.start_date:
            start = max(start, int(cal.searchsorted(pd.Timestamp(cfg.start_date))))
        end = len(cal)
        if cfg.end_date:
            end = int(cal.searchsorted(pd.Timestamp(cfg.end_date), side="right"))
        trading = cal[start:end]
        if len(trading) == 0:
            raise SystemExit("Seçilen tarih aralığında işlem günü yok (warmup sonrası boş).")
        for date in trading:
            self._step(date)
        last = trading[-1]
        if cfg.liquidate_at_end:
            for sym in list(self.positions.keys()):
                # Pencere sonunda kapanış NaN olabilir → o tarihe kadarki son GEÇERLİ kapanışı kullan
                closes = self.data[sym]["Close"].loc[:last].dropna()
                px = float(closes.iloc[-1]) if len(closes) else self.positions[sym].entry
                self._close(sym, last, px, "EOD")

    # ---- metrik özeti (grid-search için sade dict) -----------------------
    def metrics(self):
        eq = pd.Series(dict(self.equity_curve)).sort_index()
        roi = (self.cash / self.cfg.initial_capital - 1) * 100
        closed = self.trades
        wins = [t for t in closed if t.pnl > 0]; losses = [t for t in closed if t.pnl <= 0]
        wr = (len(wins) / len(closed) * 100) if closed else 0.0
        dd = ((eq / eq.cummax() - 1) * 100).min() if len(eq) else 0.0
        gp = sum(t.pnl for t in wins); gl = abs(sum(t.pnl for t in losses))
        pf = (gp / gl) if gl else float("inf")
        sc = self.spy["Close"]; spy_roi = (sc.loc[eq.index[-1]] / sc.loc[eq.index[0]] - 1) * 100
        return {"roi": roi, "spy_roi": spy_roi, "alpha": roi - spy_roi, "max_dd": dd,
                "win_rate": wr, "trades": len(closed), "profit_factor": pf, "equity": eq}


# =========================================================================
# AYLIK GETİRİ TABLOSU
# =========================================================================
def monthly_returns_table(eq: pd.Series) -> pd.DataFrame:
    m = eq.resample("ME").last()
    rets = m.pct_change().dropna() * 100
    df = pd.DataFrame({"y": rets.index.year, "m": rets.index.month, "r": rets.values})
    pivot = df.pivot_table(index="y", columns="m", values="r", aggfunc="first")
    pivot = pivot.reindex(columns=range(1, 13))
    pivot.columns = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
    yearly = df.groupby("y")["r"].apply(lambda s: (np.prod(1 + s / 100) - 1) * 100)
    pivot["Yıl%"] = yearly
    return pivot


def print_monthly(eq):
    pivot = monthly_returns_table(eq)
    print("\n  AYLIK GETİRİ (%)")
    print("  " + "-" * 92)
    hdr = "  Yıl  " + "".join(f"{c:>7}" for c in pivot.columns)
    print(hdr)
    for y, rowp in pivot.iterrows():
        cells = "".join((f"{v:>+7.1f}" if pd.notna(v) else f"{'·':>7}") for v in rowp.values)
        print(f"  {y}{cells}")
    print("  " + "-" * 92)


# =========================================================================
# PARAMETRE GRID-SEARCH (veri 1 kez indirilir, bellekte yeniden kullanılır)
# =========================================================================
def grid_search(base_cfg: Config, grid: dict, market: dict) -> pd.DataFrame:
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print(f"\nGRID-SEARCH: {len(combos)} kombinasyon · parametreler={keys}")
    rows = []
    for i, combo in enumerate(combos, 1):
        cfg = copy.deepcopy(base_cfg)
        for k, v in zip(keys, combo):
            setattr(cfg, k, v)
        bt = Swing2Backtester(cfg, market=market)   # aynı veriyi tekrar kullan
        bt.run()
        mt = bt.metrics()
        rows.append({**{k: v for k, v in zip(keys, combo)},
                     "ROI%": round(mt["roi"], 2), "Alpha": round(mt["alpha"], 2),
                     "MaxDD%": round(mt["max_dd"], 2), "Win%": round(mt["win_rate"], 1),
                     "PF": round(mt["profit_factor"], 2), "İşlem": mt["trades"]})
        print(f"  [{i}/{len(combos)}] {dict(zip(keys, combo))} → ROI {mt['roi']:+.2f}% · DD {mt['max_dd']:.1f}% · {mt['trades']} işlem")
    res = pd.DataFrame(rows).sort_values("ROI%", ascending=False).reset_index(drop=True)
    return res


# =========================================================================
# 7-BOYUTLU GRID-SEARCH (giriş + çıkış/trailing/breakeven optimizasyonu)
# =========================================================================
# Kullanıcı-dostu parametre adı → Config alanı eşlemesi
GRID_ALIAS = {
    "min_score": "min_score",
    "rr_target": "rr_target",
    "atr_stop_mult": "atr_stop_mult",
    "partial_tp_ratio": "partial_pct",      # kısmi satış payı
    "partial_tp_trigger": "partial_rr",     # kısmi tetik R/R
    "trailing_atr_mult": "atr_trail_mult",  # süren stop çarpanı
    "breakeven_mode": "breakeven_mode",     # 'strict_entry' | 'half_risk'
}

DEFAULT_GRID_7D = {
    "min_score":          [16, 18],
    "rr_target":          [2.0, 2.5, 3.0],
    "atr_stop_mult":      [1.5, 2.0],
    "partial_tp_ratio":   [0.30, 0.50],
    "partial_tp_trigger": [1.5, 2.0],
    "trailing_atr_mult":  [2.5, 3.0, 3.5, 4.0],
    "breakeven_mode":     ["strict_entry", "half_risk"],
}


def run_grid_search(base_cfg: Config, market: dict, grid: dict = None, top: int = 3) -> pd.DataFrame:
    """7-boyutlu parametre optimizasyonu. Veriyi + VCP önbelleğini bellekte korur.
    En yüksek ROI / en düşük Max Drawdown veren 'Şampiyon Set'i bulur.
    Çıkış (partial/trailing/breakeven) ve giriş (skor/rr/atr) parametrelerini birlikte tarar."""
    grid = grid or DEFAULT_GRID_7D
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print(f"\n7B GRID-SEARCH: {len(combos)} kombinasyon · {len(market['data'])} hisse · "
          f"VCP cache paylaşımlı (bellekte) ...")
    rows = []
    for i, combo in enumerate(combos, 1):
        cfg = copy.deepcopy(base_cfg)
        cfg.partial_tp = True          # bu testte kısmi + trailing aktif
        cfg.trailing_stop = True
        params = {}
        for k, v in zip(keys, combo):
            setattr(cfg, GRID_ALIAS.get(k, k), v)
            params[k] = v
        bt = Swing2Backtester(cfg, market=market)   # market + vcp_cache yeniden kullanılır
        bt.run()
        mt = bt.metrics()
        pf = mt["profit_factor"]
        rows.append({
            **params,
            "trades": mt["trades"],
            "win": round(mt["win_rate"], 1),
            "pf": round(pf, 2) if pf != float("inf") else None,
            "maxdd": round(mt["max_dd"], 2),
            "roi": round(mt["roi"], 2),
            "net": round(base_cfg.initial_capital * (1 + mt["roi"] / 100.0), 2),
        })
        if i % 24 == 0 or i == len(combos):
            print(f"  {i}/{len(combos)} tamamlandı ...")

    # Sıralama: önce ROI↓, eşitlikte daha sığ drawdown (maxdd negatif → büyük=daha iyi)
    res = pd.DataFrame(rows).sort_values(["roi", "maxdd"], ascending=[False, False]).reset_index(drop=True)

    # ---- Top-N karşılaştırma matrisi ----
    line = "=" * 100
    print(f"\n{line}\n  7B GRID — ŞAMPİYON {top} SET (ROI↓ / Drawdown↑)\n{line}")
    hdr = (f"  {'#':<2} {'sc':<3} {'rr':<4} {'atr':<4} {'pTP%':<5} {'trig':<5} "
           f"{'trail':<6} {'breakeven':<13} {'İşlem':<6} {'Win%':<6} {'PF':<5} {'MaxDD%':<8} {'Net $':<12} {'ROI%':<7}")
    print(hdr)
    print("  " + "-" * 96)
    for i in range(min(top, len(res))):
        r = res.iloc[i]
        print(f"  {i+1:<2} {int(r['min_score']):<3} {r['rr_target']:<4} {r['atr_stop_mult']:<4} "
              f"{r['partial_tp_ratio']:<5} {r['partial_tp_trigger']:<5} {r['trailing_atr_mult']:<6} "
              f"{r['breakeven_mode']:<13} {int(r['trades']):<6} {r['win']:<6} "
              f"{('-' if r['pf'] is None else r['pf']):<5} {r['maxdd']:<8} "
              f"${r['net']:<11,.0f} {r['roi']:+.2f}")
    print(line)
    champ = res.iloc[0].to_dict()
    print(f"  → ŞAMPİYON: " + " · ".join(f"{k}={champ[k]}" for k in keys))
    print(f"    ROI {champ['roi']:+.2f}% · Net ${champ['net']:,.0f} · MaxDD {champ['maxdd']:.2f}% · "
          f"Win {champ['win']}% · PF {champ['pf']} · {int(champ['trades'])} işlem")
    print(line)
    return res


# =========================================================================
# 8-EMA STOP + TP-MODU GRID-SEARCH (v5)
# Stop DAİMA 8-EMA; sadece Kâr-Al (TP) tarafı taranır. Erken-eleme çözümü.
# =========================================================================
def build_tp_combos(confirm_opts=(True, False)) -> list[dict]:
    """Koşullu (mode'a bağlı) parametre uzayı. Her eleman tam bir Config-override sözlüğü."""
    combos = []
    for confirm in confirm_opts:
        base = {"ma_confirm_close": confirm}
        # A) RR_BASED: kısmi(%30/50) @1.5R/2R + kalan 3R/4R hedefi (hedef > tetik olmalı)
        for trig in (1.5, 2.0):
            for pct in (0.30, 0.50):
                for tgt in (2.0, 3.0, 4.0):
                    if tgt <= trig: continue
                    combos.append({**base, "tp_mode": "RR_BASED", "partial_tp": True,
                                   "partial_rr": trig, "partial_pct": pct, "rr_target": tgt})
        # B) MOMENTUM_OSCILLATOR: RSI 70/75 (veya Stoch>80 aşağı kesişim) → tam TP
        for lim in (70.0, 75.0):
            combos.append({**base, "tp_mode": "MOMENTUM_OSCILLATOR", "partial_tp": False,
                           "rsi_overbought_limit": lim})
        # C) ATR_CLIMAX: 8EMA+2.0/2.5×ATR aşırı uzama → tam TP
        for cm in (2.0, 2.5):
            combos.append({**base, "tp_mode": "ATR_CLIMAX", "partial_tp": False,
                           "climax_atr_mult": cm})
        # D) HYBRID_TREND: 50% 8-EMA + 50% 21-EMA (alt-parametre yok)
        combos.append({**base, "tp_mode": "HYBRID_TREND", "partial_tp": False})
    return combos


def _combo_label(c: dict) -> str:
    m = c["tp_mode"]; cf = "K" if c.get("ma_confirm_close") else "T"  # Kapanış / Touch
    if m == "RR_BASED":
        return f"RR  {int(c['partial_pct']*100)}%@{c['partial_rr']}R→{c['rr_target']}R [{cf}]"
    if m == "MOMENTUM_OSCILLATOR":
        return f"MOM RSI≥{int(c['rsi_overbought_limit'])} | Stoch↓80 [{cf}]"
    if m == "ATR_CLIMAX":
        return f"CLIMAX 8EMA+{c['climax_atr_mult']}×ATR [{cf}]"
    if m == "HYBRID_TREND":
        return f"HYBRID 8EMA/21EMA 50-50 [{cf}]"
    return m


def run_tp_grid_search(base_cfg: Config, market: dict, confirm_opts=(True, False),
                       csv_path: str = None) -> pd.DataFrame:
    """8-EMA stop sabit; 4 TP modunu + alt-parametrelerini tarar.
    Her modun erken-eleme/kârlılık dengesini kıyaslar, net-bakiyesi en yüksek seti
    '8 EMA İÇİN ŞAMPİYON ÇIKIŞ STRATEJİSİ' ilan eder."""
    combos = build_tp_combos(confirm_opts)
    print(f"\n8-EMA TP-GRID: {len(combos)} kombinasyon · stop=8EMA(daima) · {len(market['data'])} hisse ...", flush=True)
    rows = []
    for i, ov in enumerate(combos, 1):
        cfg = copy.deepcopy(base_cfg)
        cfg.exit_mode = "tp_grid"
        cfg.trailing_stop = False   # ATR-trailing devre dışı; stop = 8EMA
        for k, v in ov.items():
            setattr(cfg, k, v)
        bt = Swing2Backtester(cfg, market=market)
        bt.run(); mt = bt.metrics()
        entries = len({(t.symbol, t.entry_date) for t in bt.trades})  # gerçek poz. sayısı
        pf = mt["profit_factor"]
        rows.append({
            "mode": ov["tp_mode"], "label": _combo_label(ov), "confirm": ov.get("ma_confirm_close"),
            "params": {k: v for k, v in ov.items() if k not in ("tp_mode", "ma_confirm_close", "partial_tp")},
            "entries": entries, "legs": mt["trades"],
            "win": round(mt["win_rate"], 1),
            "pf": round(pf, 2) if pf != float("inf") else None,
            "maxdd": round(mt["max_dd"], 2), "roi": round(mt["roi"], 2),
            "net": round(base_cfg.initial_capital * (1 + mt["roi"] / 100.0), 2),
            "alpha": round(mt["alpha"], 2), "spy": round(mt["spy_roi"], 2),
        })
        print(f"  [{i}/{len(combos)}] {_combo_label(ov):<34} → ROI {mt['roi']:>+7.2f}% · "
              f"net ${rows[-1]['net']:>10,.0f} · {entries} giriş · Win {mt['win_rate']:.0f}%", flush=True)

    res = pd.DataFrame(rows).sort_values(["net", "maxdd"], ascending=[False, False]).reset_index(drop=True)
    if csv_path:
        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        res.drop(columns=["params"]).to_csv(csv_path, index=False)

    # ---- Türkçe özet tablo ----
    L = "=" * 104
    print(f"\n{L}\n  8-EMA STOP — TP-MODU KARŞILAŞTIRMASI (net bakiye↓)  ·  K=kapanış-teyidi, T=gün-içi dokunuş\n{L}", flush=True)
    hdr = (f"  {'#':<3}{'TP Stratejisi':<36}{'Giriş':>6}{'Bacak':>6}{'Win%':>7}{'PF':>6}"
           f"{'MaxDD%':>9}{'Net $':>13}{'ROI%':>9}")
    print(hdr); print("  " + "-" * 100, flush=True)
    for i in range(len(res)):
        r = res.iloc[i]
        print(f"  {i+1:<3}{r['label']:<36}{int(r['entries']):>6}{int(r['legs']):>6}{r['win']:>7}"
              f"{('-' if r['pf'] is None else r['pf']):>6}{r['maxdd']:>9}{r['net']:>13,.0f}{r['roi']:>+9.2f}", flush=True)
    print(L, flush=True)

    # ---- Mod-bazlı en iyi (her kategorinin şampiyonu) ----
    print("  MOD BAZINDA EN İYİ:", flush=True)
    for m in ("RR_BASED", "MOMENTUM_OSCILLATOR", "ATR_CLIMAX", "HYBRID_TREND"):
        sub = res[res["mode"] == m]
        if len(sub):
            b = sub.iloc[0]
            print(f"    {m:<20} {b['label']:<34} ROI {b['roi']:+.2f}% · net ${b['net']:,.0f} · "
                  f"Win {b['win']}% · PF {b['pf']} · {int(b['entries'])} giriş · DD {b['maxdd']}%", flush=True)
    print(L, flush=True)

    champ = res.iloc[0]
    print(f"  🏆 8 EMA İÇİN ŞAMPİYON ÇIKIŞ STRATEJİSİ: {champ['label']}", flush=True)
    print(f"     Net ${champ['net']:,.0f} · ROI {champ['roi']:+.2f}% (SPY {champ['spy']:+.2f}% → alpha {champ['alpha']:+.2f}) · "
          f"Win {champ['win']}% · PF {champ['pf']} · MaxDD {champ['maxdd']}% · {int(champ['entries'])} giriş / {int(champ['legs'])} bacak", flush=True)
    print(L, flush=True)
    return res


# =========================================================================
# RAPOR + ÇIKTILAR (tekli koşu)
# =========================================================================
def full_report(bt: Swing2Backtester):
    cfg = bt.cfg; mt = bt.metrics(); eq = mt["equity"]
    os.makedirs(cfg.out_dir, exist_ok=True)
    closed = bt.trades
    by = lambda o: [t for t in closed if t.outcome == o]
    pd.DataFrame([t.__dict__ for t in closed]).to_csv(os.path.join(cfg.out_dir, cfg.trades_csv), index=False)
    eq.to_frame("equity").to_csv(os.path.join(cfg.out_dir, cfg.equity_csv))
    ppath = None
    if HAVE_MPL:
        sc = bt.spy["Close"].reindex(eq.index); spy_n = cfg.initial_capital * (sc / sc.iloc[0])
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(eq.index, eq.values, label="Swing 2.0 Stratejisi", lw=1.8, color="#7c3aed")
        ax.plot(spy_n.index, spy_n.values, label="SPY Al-Tut", lw=1.4, color="#6aa9ff", alpha=0.8)
        ax.axhline(cfg.initial_capital, color="#888", ls="--", lw=0.8, alpha=0.6)
        ax.set_title("Swing Trade 2.0 — Equity Curve vs SPY"); ax.set_ylabel("Portföy ($)")
        ax.legend(); ax.grid(alpha=0.2); fig.tight_layout()
        ppath = os.path.join(cfg.out_dir, cfg.equity_png); fig.savefig(ppath, dpi=110); plt.close(fig)

    L = "=" * 70
    print(f"\n{L}\n  SWING TRADE 2.0 — BACKTEST RAPORU (8-katman + kill-switch + trailing/partial)\n{L}")
    print(f"  Dönem            : {eq.index[0].date()} → {eq.index[-1].date()}")
    smode = f"compounding (%{cfg.max_position_pct*100:.0f})" if cfg.compounding else f"sabit ${cfg.initial_capital*cfg.max_position_pct:,.0f}"
    print(f"  Havuz/Risk       : {len(bt.data)} hisse · max {cfg.max_positions} poz · {smode}")
    print(f"  Giriş            : skor≥{cfg.min_score}/24 · kill-switch={'hariç' if cfg.require_not_killswitch else 'dahil'}")
    print(f"  Çıkış            : kısmi {int(cfg.partial_pct*100)}%@1:{cfg.partial_rr} (BE'ye çek) · trailing {cfg.atr_trail_mult}×ATR (+{cfg.trail_after_r}R sonrası)")
    print(f"  Maliyet          : ${cfg.commission_per_trade}/bacak · giriş {cfg.entry_slippage_bps:.0f}bps · çıkış {cfg.slippage_bps:.0f}bps · stop {cfg.stop_slippage_bps:.0f}bps slippage")
    print("-" * 70)
    print(f"  Başlangıç → Net  : ${cfg.initial_capital:,.0f} → ${bt.cash:,.2f}")
    print(f"  Toplam ROI       : {mt['roi']:+.2f}%   (alpha vs SPY: {mt['alpha']:+.2f} puan)")
    print(f"  SPY Al-Tut ROI   : {mt['spy_roi']:+.2f}%   → {'Strateji YENDİ ✓' if mt['alpha']>0 else 'Endeks yendi ✗'}")
    print("-" * 70)
    print(f"  Toplam İşlem     : {mt['trades']}   (TP {len(by('TP'))} · PARTIAL {len(by('PARTIAL'))} · TRAIL {len(by('TRAIL'))} · STOP {len(by('STOP'))} · EOD {len(by('EOD'))})")
    print(f"  Win Rate         : {mt['win_rate']:.1f}%   ·   Profit Factor: {mt['profit_factor']:.2f}")
    print(f"  Max Drawdown     : {mt['max_dd']:.2f}%   ·   Tepe Equity: ${eq.cummax().max():,.0f}")
    print(f"{L}")
    print(f"  CSV: {os.path.join(cfg.out_dir, cfg.trades_csv)} · {os.path.join(cfg.out_dir, cfg.equity_csv)}")
    if ppath: print(f"  Grafik: {ppath}")
    print(L)
    print_monthly(eq)


# =========================================================================
# API: arayüzden (serve.py /api/backtest) çağrılan, JSON döndüren giriş noktası
# =========================================================================
import math

_MARKET_CACHE = {}   # sunucu ömrü boyunca veriyi yeniden kullan (tekrar koşu hızlı)

UNIVERSE_PRESETS = {
    "default": DEFAULT_UNIVERSE,
    "mega": ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
             "JPM", "V", "WMT", "JNJ", "XOM", "UNH", "LLY", "MA", "HD", "PG", "COST", "ORCL"),
    "tech": ("AAPL", "MSFT", "NVDA", "AMD", "AVGO", "ORCL", "CRM", "ADBE", "NOW",
             "PANW", "CRWD", "SNOW", "CSCO", "QCOM", "MU", "AMAT", "LRCX", "PLTR"),
    # Geniş evrenler (Mega+Large ~350 / NASDAQ-100). NOT: SECTOR_MAP bunların
    # bir kısmını kapsamaz → swing2 4.katman (sektör) puanı düşer; qswing girişinde etkisiz.
    "sp500": tuple("AAPL MSFT NVDA GOOGL GOOG AMZN META TSLA BRK-B LLY JPM V WMT XOM MA JNJ ORCL COST PG AVGO HD NFLX UNH BAC ABBV KO CRM CVX PFE AMD TMO ADBE ACN PEP LIN MRK MCD ABT CSCO WFC NOW IBM GS ISRG INTC INTU BX AMGN AXP DIS T RTX PM MS TXN QCOM BKNG CAT SCHW GE NEE BLK AMAT SPGI UBER BA PGR GILD LMT MO ELV HON NKE COP TJX SYK PLD ETN VRTX ADI ADP AFL AIG AJG ALL AMT ANET AON APD APH ARM AZO BDX BIIB BKR BMY BSX C CB CDNS CDW CHTR CI CL CME CMG CMI CNC COF COIN CSGP CTAS CTSH CTVA D DAL DASH DD DELL DG DHR DLR DLTR DOV DOW DUK EA EBAY ECL EFX EIX EL EMR ENPH EOG EQIX EQR EQT ESS EW EXC EXR F FANG FCX FDX FERG FI FIS FITB FSLR FTNT GD GEV GIS GLW GM GPN HAL HCA HES HIG HLT HOOD HSY HUBB HUM ICE ICLR IDXX IEX ILMN INFY IP IRM IT ITW JCI K KDP KEY KHC KKR KLAC KMB KMI KR L LDOS LEN LH LNT LRCX LULU LUV LVS LYB MAR MCHP MCK MDLZ MDT MELI MET MFC MMC MMM MNST MOH MOS MPC MPWR MRO MRVL MSCI MSI MTB MU NDAQ NEM NOC NSC NTAP NTRS NUE NVO NWS O OKE OMC ON ORLY OTIS OXY PANW PARA PAYC PAYX PCAR PCG PEG PFG PH PHM PKG PLTR PNC PNR PNW POOL PPG PPL PRU PSA PSX PTC PWR PYPL QRVO QSR RCL REGN RF RL RMD ROK ROL ROP ROST SBAC SBUX SHW SLB SMCI SNA SNOW SO SPG SQ STE STLD STM STT STX STZ SUI SWK SWKS SYF SYY TDG TDY TECH TEL TER TFC TFX TGT TKO TMUS TPR TRGP TRMB TROW TRV TSCO TSN TT TTD TTWO TXT TYL UAL UDR UHS ULTA UNM UNP UPS URI USB VFC VICI VLO VLTO VMC VRSK VRSN VTR VTRS VZ WAB WAT WBA WBD WDC WEC WELL WM WMB WRB WST WTW WY WYNN XEL XYL YUM ZBH ZBRA ZS ZTS".split()),
    "nasdaq100": tuple("AAPL MSFT NVDA GOOGL GOOG AMZN META TSLA AVGO COST NFLX AMD INTC INTU AMAT ADBE ORCL CSCO TMUS ISRG QCOM TXN BKNG PEP HON MU SBUX LRCX KLAC ADI MELI ADSK PANW ABNB CTAS ASML SNPS CDNS REGN ROP CHTR FTNT MAR PYPL PCAR ORLY AEP CRWD MNST MRVL ROST MCHP CPRT ADP DASH KDP AZN FAST EXC ODFL XEL CSGP CCEP NXPI BIIB FANG IDXX KHC CTSH WBD ANSS GEHC ON TTWO LULU GFS ZS DDOG WDAY TEAM CDW SMCI ARM PDD MDB OKTA".split()),
}
UNIVERSE_PRESETS["sp500_ndx"] = tuple(sorted(set(UNIVERSE_PRESETS["sp500"]) | set(UNIVERSE_PRESETS["nasdaq100"])))


def _jsafe(x):
    """NaN/Inf → None, numpy skaler → python."""
    if x is None:
        return None
    if isinstance(x, (np.floating, np.integer)):
        x = x.item()
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


def _get_market(cfg: Config) -> dict:
    key = (tuple(cfg.universe), cfg.period, cfg.start_date, cfg.end_date,
           cfg.interval, cfg.atr_period,
           cfg.slope_window, cfg.pivot_lookback, cfg.warmup_bars, cfg.use_earnings,
           getattr(cfg, "use_rs_universe", False), getattr(cfg, "rs_n", 50),
           tuple(getattr(cfg, "rs_pool", ()) or ()))
    if key not in _MARKET_CACHE:
        _MARKET_CACHE[key] = load_market(cfg)
    else:
        _MARKET_CACHE[key]["vcp_cache"] = {}  # grid sonrası temizle (rr'a bağlı değil ama güvenli)
    return _MARKET_CACHE[key]


def run_backtest_api(params: dict) -> dict:
    """serve.py /api/backtest → JSON-safe sonuç (metrikler + equity + trades + aylık + grid)."""
    cfg = Config()
    # Evren
    syms = params.get("symbols")
    if isinstance(syms, list) and syms:
        cfg.universe = tuple(s.strip().upper() for s in syms if s and s.strip())[:120]
    else:
        cfg.universe = UNIVERSE_PRESETS.get(params.get("preset", "default"), DEFAULT_UNIVERSE)
    # RS top-50 sistematik evren kapısı (canlı Qulla-21 ile birebir): havuz = seçilen evren,
    # her gün göreli güç (RS) ile top-N'e indirilir; yalnız o N'e giriş açılır.
    # attach_watchlist uygular (rs_pool boşsa cfg.universe havuz olur).
    cfg.use_rs_universe = bool(params.get("use_rs_universe", False))
    try:
        cfg.rs_n = int(max(5, min(200, params.get("rs_n", cfg.rs_n))))
    except (TypeError, ValueError):
        pass
    # Parametreler (clamp'li)
    cfg.min_score = int(max(0, min(24, params.get("min_score", cfg.min_score))))
    cfg.rr_target = float(max(1.0, min(6.0, params.get("rr_target", cfg.rr_target))))
    cfg.atr_stop_mult = float(max(0.5, min(5.0, params.get("atr_stop_mult", cfg.atr_stop_mult))))
    cfg.max_dist_sma20 = float(max(0.0, min(2.0, params.get("max_dist_sma20", cfg.max_dist_sma20))))
    cfg.max_positions = int(max(1, min(20, params.get("max_positions", cfg.max_positions))))
    # Boyutlandırma: 'fixed' (sermaye×poz%) | 'risk' (işlem başına sabit risk%)
    cfg.sizing_mode = "risk" if str(params.get("sizing_mode", "fixed")).lower() == "risk" else "fixed"
    cfg.risk_per_trade_pct = float(max(0.1, min(10.0, params.get("risk_per_trade_pct", cfg.risk_per_trade_pct))))
    if params.get("max_position_pct") is not None:
        cfg.max_position_pct = float(max(0.02, min(1.0, params.get("max_position_pct"))))
    cfg.free_runner_slots = bool(params.get("free_runner_slots", False))
    cfg.period = str(params.get("period", cfg.period))
    # El ile tarih aralığı (geçerli ISO ise period'u geçersiz kılar)
    def _vdate(s):
        try:
            return pd.Timestamp(str(s)).strftime("%Y-%m-%d") if s else ""
        except (ValueError, TypeError):
            return ""
    sd, ed = _vdate(params.get("start_date")), _vdate(params.get("end_date"))
    if sd and ed and pd.Timestamp(sd) >= pd.Timestamp(ed):
        sd = ed = ""   # geçersiz aralık → yok say
    cfg.start_date, cfg.end_date = sd, ed
    cfg.compounding = bool(params.get("compounding", cfg.compounding))
    cfg.entry_slippage_bps = float(max(0.0, min(50.0, params.get("entry_slippage_bps", cfg.entry_slippage_bps))))
    cfg.slippage_bps = float(max(0.0, min(50.0, params.get("slippage_bps", cfg.slippage_bps))))
    cfg.entry_fill_mode = "preclose" if str(params.get("entry_fill_mode", cfg.entry_fill_mode)) == "preclose" else "close"
    cfg.preclose_frac = float(max(0.0, min(1.0, params.get("preclose_frac", cfg.preclose_frac))))
    cfg.partial_tp = bool(params.get("partial_tp", cfg.partial_tp))
    cfg.trailing_stop = bool(params.get("trailing_stop", cfg.trailing_stop))
    cfg.use_earnings = bool(params.get("use_earnings", False))  # arayüzde varsayılan KAPALI (hız)
    # GİRİŞ modu: 'qswing' (Qullamaggie kırılım) veya 'swing2' (8-katman skor)
    cfg.entry_mode = ("qswing_breakout"
                      if str(params.get("entry_mode", "swing2")).lower() in ("qswing", "qswing_breakout", "breakout")
                      else "swing2")
    # qswing 0–100 öncelik skoru EŞİĞİ (canlı tarayıcıyla aynı formül; 0 = filtre kapalı)
    try:
        cfg.qswing_min_score = float(max(0.0, min(100.0, params.get("qswing_min_score", 0) or 0)))
    except (TypeError, ValueError):
        cfg.qswing_min_score = 0.0
    # qswing kırılım periyodu — yalnız {10,20,40,63} ön-hesaplı (HIGH_PRIOR_N); başkası 40'a düşer
    try:
        _qlb = int(params.get("qswing_breakout_lb", cfg.qswing_breakout_lb))
    except (TypeError, ValueError):
        _qlb = cfg.qswing_breakout_lb
    cfg.qswing_breakout_lb = _qlb if _qlb in (10, 20, 40, 63) else 40
    run_grid = bool(params.get("run_grid", False))

    # --- Çıkış stratejisi (UI dropdown) ---
    # 'champion'  → ATR-trail şampiyonu (8-katman + kısmi + 3×ATR trailing + half-risk BE)
    # 'rr_based'/'momentum'/'atr_climax'/'hybrid' → 8-EMA SABİT stop + seçilen TP modu
    def _clf(v, lo, hi, d):  # float clamp
        try: return float(max(lo, min(hi, v)))
        except (TypeError, ValueError): return d
    # ATR-REJİM oynaklık filtresi: her çıkışta opt-in (UI). 'atr_regime' çıkışı ayrıca zorlar.
    cfg.regime_atr_filter = bool(params.get("regime_atr_filter", False))
    cfg.regime_atr_threshold = _clf(params.get("regime_atr_threshold", 1.5), 0.3, 5.0, 1.5)
    es = str(params.get("exit_strategy", "champion")).lower()
    if es in ("champion", "optimized"):
        cfg.exit_mode = "optimized"          # FMP kalibrasyon şampiyonu (B): ATR-trail 2.5× · strict BE
        cfg.partial_tp = True; cfg.partial_pct = 0.5; cfg.partial_rr = 2.0
        cfg.trailing_stop = True; cfg.atr_trail_mult = 2.5; cfg.breakeven_mode = "strict_entry"
    elif es == "atr_trail":
        cfg.exit_mode = "atr_full"           # tam pozisyon SAF ATR-trail (şamdan, partial yok)
        cfg.atr_trail_mult = _clf(params.get("atr_trail_mult", 2.5), 0.5, 6.0, 2.5)
        cfg.partial_tp = False; cfg.trailing_stop = False
    elif es in ("atr_regime", "atr-regime", "regime"):
        # SAF ATR (sabit kâr-al / zarar-kes, trailing YOK) + sabit-dolar risk + SPY oynaklık kilidi
        cfg.exit_mode = "atr_regime"
        cfg.partial_tp = False; cfg.trailing_stop = False
        cfg.regime_atr_filter = True         # bu modda oynaklık kilidi DAİMA açık (hard-switch)
        cfg.atr_stop_mult = _clf(params.get("atr_stop_mult", 1.5), 0.5, 5.0, 1.5)
        cfg.atr_target_mult = _clf(params.get("atr_target_mult", 3.0), 0.5, 10.0, 3.0)
        cfg.risk_per_trade_usd = _clf(params.get("risk_per_trade_usd", 1000.0), 50.0, 100_000.0, 1000.0)
        # sabit-dolar risk gerçekten bağlasın diye konsantrasyon tavanını gevşet (yine de güvenlik sınırı)
        if params.get("max_position_pct") is None:
            cfg.max_position_pct = 0.5
    elif es in ("ma_trail", "qullamaggie", "ma10"):
        cfg.exit_mode = "ma_trail"           # Qullamaggie: N-gün MA altına kapanınca çık
        cfg.ma_trail_len = int(_clf(params.get("ma_trail_len", 10), 3, 50, 10))
        cfg.ma_trail_type = "sma"
        cfg.partial_tp = bool(params.get("partial_tp", True))
        cfg.partial_pct = _clf(params.get("partial_pct", 0.5), 0.1, 1.0, 0.5)
        cfg.partial_rr = _clf(params.get("partial_rr", 2.0), 0.5, 5.0, 2.0)
    else:
        cfg.exit_mode = "tp_grid"; cfg.trailing_stop = False
        cfg.ma_confirm_close = bool(params.get("ma_confirm_close", True))
        if es == "rr_based":
            cfg.tp_mode = "RR_BASED"; cfg.partial_tp = True
            cfg.partial_pct = _clf(params.get("partial_pct", 0.30), 0.1, 1.0, 0.30)
            cfg.partial_rr = _clf(params.get("partial_rr", 1.5), 0.5, 5.0, 1.5)
            cfg.rr_target = _clf(params.get("rr_target", 3.0), 1.0, 6.0, 3.0)
        elif es == "momentum":
            cfg.tp_mode = "MOMENTUM_OSCILLATOR"; cfg.partial_tp = False
            cfg.rsi_overbought_limit = _clf(params.get("rsi_overbought_limit", 70), 50, 95, 70)
        elif es == "atr_climax":
            cfg.tp_mode = "ATR_CLIMAX"; cfg.partial_tp = False
            cfg.climax_atr_mult = _clf(params.get("climax_atr_mult", 2.0), 0.5, 6.0, 2.0)
        elif es == "hybrid":
            cfg.tp_mode = "HYBRID_TREND"; cfg.partial_tp = False
        elif es == "hybrid2":
            cfg.tp_mode = "HYBRID_TREND2"; cfg.partial_tp = False
            cfg.ma_confirm_close = True   # ilk %50 daima KAPANIŞ teyitli (iğne elemez)
        elif es == "split":
            cfg.exit_mode = "split"; cfg.partial_tp = False; cfg.trailing_stop = False
            _RULES = {"ema8", "ema21", "ma10", "ma20", "ma50", "target", "atr_trail", "hybrid"}
            cfg.split_a = str(params.get("split_a", "ema8")).lower()
            cfg.split_b = str(params.get("split_b", "ema21")).lower()
            if cfg.split_a not in _RULES: cfg.split_a = "ema8"
            if cfg.split_b not in _RULES: cfg.split_b = "ema21"
            cfg.split_a_param = _clf(params.get("split_a_param", 0), 0, 10, 0)
            cfg.split_b_param = _clf(params.get("split_b_param", 0), 0, 10, 0)
            cfg.split_ratio = _clf(params.get("split_ratio", 0.5), 0.1, 0.9, 0.5)
        else:
            es = "champion"; cfg.exit_mode = "optimized"   # bilinmeyen → şampiyon (B)
            cfg.partial_tp = True; cfg.partial_pct = 0.5; cfg.partial_rr = 2.0
            cfg.trailing_stop = True; cfg.atr_trail_mult = 2.5; cfg.breakeven_mode = "strict_entry"

    market = _get_market(cfg)
    market["vcp_cache"] = {}
    bt = Swing2Backtester(cfg, market=market)
    bt.run()
    mt = bt.metrics()
    eq = mt["equity"]
    sc = bt.spy["Close"].reindex(eq.index)
    spy_norm = cfg.initial_capital * (sc / sc.iloc[0])

    equity = [{"date": d.strftime("%Y-%m-%d"),
               "equity": round(float(v), 2),
               "spy": _jsafe(round(float(spy_norm.loc[d]), 2))}
              for d, v in eq.items()]

    closed = bt.trades
    trades = [{"symbol": t.symbol, "sector": t.sector, "score": int(t.score),
               "entry_date": t.entry_date.strftime("%Y-%m-%d"),
               "exit_date": t.exit_date.strftime("%Y-%m-%d"),
               "entry": round(t.entry, 2), "exit": round(t.exit, 2),
               "pnl": round(t.pnl, 2), "pnl_pct": round(t.pnl_pct, 2),
               "outcome": t.outcome} for t in closed]

    # Aylık tablo (+ SPY al-tut yıllık kıyas → Alpha)
    monthly = []
    if len(eq) > 1:
        piv = monthly_returns_table(eq)
        spiv = monthly_returns_table(spy_norm)              # SPY al-tut aylık → yıllık
        spy_year = {int(y): float(spiv.loc[y, "Yıl%"])
                    for y in spiv.index if pd.notna(spiv.loc[y, "Yıl%"])}
        for y, rowp in piv.iterrows():
            cells = [_jsafe(round(float(v), 1)) if pd.notna(v) else None for v in rowp.values[:12]]
            yr = _jsafe(round(float(rowp.values[-1]), 1)) if pd.notna(rowp.values[-1]) else None
            sp = spy_year.get(int(y))
            monthly.append({"year": int(y), "months": cells, "year_pct": yr,
                            "spy_pct": (_jsafe(round(sp, 1)) if sp is not None else None),
                            "alpha_pct": (_jsafe(round(yr - sp, 1))
                                          if (sp is not None and yr is not None) else None)})

    def _count(o): return sum(1 for t in closed if t.outcome == o)

    result = {
        "config": {"universe_n": len(bt.data), "min_score": cfg.min_score,
                   "rr_target": cfg.rr_target, "atr_stop_mult": cfg.atr_stop_mult,
                   "max_positions": cfg.max_positions,
                   "sizing_mode": cfg.sizing_mode, "risk_per_trade_pct": cfg.risk_per_trade_pct,
                   "max_position_pct": cfg.max_position_pct,
                   "free_runner_slots": getattr(cfg, "free_runner_slots", False),
                   "entry_mode": cfg.entry_mode, "qswing_min_score": cfg.qswing_min_score,
                   "use_rs_universe": getattr(cfg, "use_rs_universe", False), "rs_n": getattr(cfg, "rs_n", 50),
                   "period": cfg.period, "compounding": cfg.compounding,
                   "date_range": bool(cfg.start_date or cfg.end_date),
                   "req_start": cfg.start_date or None, "req_end": cfg.end_date or None,
                   "partial_tp": cfg.partial_tp, "trailing_stop": cfg.trailing_stop,
                   "use_earnings": cfg.use_earnings,
                   "exit_strategy": es, "exit_mode": cfg.exit_mode,
                   "tp_mode": (cfg.tp_mode if cfg.exit_mode == "tp_grid" else None),
                   "split_a": (cfg.split_a if cfg.exit_mode == "split" else None),
                   "split_b": (cfg.split_b if cfg.exit_mode == "split" else None),
                   "regime_atr_filter": cfg.regime_atr_filter,
                   "regime_atr_threshold": cfg.regime_atr_threshold,
                   "atr_target_mult": (cfg.atr_target_mult if cfg.exit_mode == "atr_regime" else None),
                   "risk_per_trade_usd": (cfg.risk_per_trade_usd if cfg.exit_mode == "atr_regime" else None),
                   "ma_confirm_close": cfg.ma_confirm_close,
                   "start": eq.index[0].strftime("%Y-%m-%d"),
                   "end": eq.index[-1].strftime("%Y-%m-%d")},
        "metrics": {"initial": cfg.initial_capital, "final": round(float(bt.cash), 2),
                    "roi": _jsafe(round(mt["roi"], 2)), "spy_roi": _jsafe(round(mt["spy_roi"], 2)),
                    "alpha": _jsafe(round(mt["alpha"], 2)), "max_dd": _jsafe(round(mt["max_dd"], 2)),
                    "win_rate": _jsafe(round(mt["win_rate"], 1)),
                    "profit_factor": _jsafe(round(mt["profit_factor"], 2)) if mt["profit_factor"] != float("inf") else None,
                    "trades": mt["trades"], "peak": round(float(eq.cummax().max()), 2),
                    "tp": _count("TP"), "partial": _count("PARTIAL"), "trail": _count("TRAIL"),
                    "stop": _count("STOP"), "eod": _count("EOD"),
                    "ema8": _count("EMA8"), "ema21": _count("EMA21"),
                    "mom": _count("MOM"), "climax": _count("CLIMAX")},
        "equity": equity, "trades": trades, "monthly": monthly,
    }

    if run_grid:
        grid = {"min_score": [12, 14, 16, 18], "rr_target": [2.0, 3.0, 4.0], "atr_stop_mult": [1.5, 2.0, 2.5]}
        res = grid_search(cfg, grid, market)
        result["grid"] = [
            {"min_score": int(r["min_score"]), "rr_target": float(r["rr_target"]),
             "atr_stop_mult": float(r["atr_stop_mult"]),
             "roi": _jsafe(r["ROI%"]), "max_dd": _jsafe(r["MaxDD%"]),
             "win_rate": _jsafe(r["Win%"]), "pf": _jsafe(r["PF"]), "trades": int(r["İşlem"])}
            for _, r in res.iterrows()
        ]
    return result


# =========================================================================
# CANLI / DRY-RUN: KAPANIŞ-ÖNCESİ TARAMA (Live Pre-Close Scanner)
# Kapanışa ~10 dk kala (15:50 ET) çağrılır. current_market_data'daki SON bar
# 'günün kapanışı' varsayılır (gün-içi snapshot). Backtest ile AYNI değerlendirme
# yolu (Swing2Backtester yardımcıları) → tam parite, sapma yok.
# =========================================================================
def run_live_pre_close_scan(current_market_data, cfg=None, asof=None,
                            include_watch=True, held=None):
    """Kapanışa dakikalar kala anlık 'ALINABİLİR' listesi üretir.

    current_market_data: download_and_align_data ile AYNI yapıdaki sözlük
        (data/spy/sectors/earnings/calendar/vcp_cache). Piyasa AÇIKKEN çekilirse
        her sembolün SON satırı bugünün forming (gün-içi) barıdır → 'kapanış' varsayılır.
    cfg     : Config (min_score, require_not_killswitch vb. eşikler buradan).
    asof    : belirli bir tarihi değerlendir (None → son bar = canlı).
    held    : halihazırda taşınan semboller (AL listesinden düşülür).

    Dönen dict: {asof, regime_open, spy_close, n_universe, buyable[], watch[]}.
    ALINABİLİR kriteri = Rejim AÇIK (SPY>SMA200) + trend kapıları + skor≥min_score
                          + kill-switch temiz (require_not_killswitch ise).
    """
    cfg = cfg or Config()
    held = set(held or [])
    bt = Swing2Backtester(cfg, market=current_market_data)
    cal = bt.calendar
    if asof is None:
        date = cal[-1]                                   # son bar = canlı gün-içi snapshot
    else:
        pos = int(cal.searchsorted(pd.Timestamp(asof), side="right")) - 1
        date = cal[max(0, pos)]
    common = bt._common(date)
    regime_open = bool(common["spy_above_sma200"])       # piyasa rejimi (SPY>SMA200)
    spy_close = float(bt.spy.loc[date, "Close"])

    rows = []
    for sym, df in bt.data.items():
        row = df.loc[date]
        if pd.isna(row["Close"]):
            continue
        gates_ok = (not pd.isna(row["SMA200"]) and row["Close"] > row["SMA200"]
                    and not pd.isna(row["SMA50"]) and row["Close"] > row["SMA50"]
                    and not pd.isna(row["SMA20"]) and row["Close"] > row["SMA20"]
                    and not pd.isna(row["SLOPE200"]) and row["SLOPE200"] > 0)
        stage = detect_stage(row)
        vcp = bt._vcp(sym, df, date)
        plan = compute_trade_plan(row, cfg)
        mctx = bt._mctx(sym, row, date, common)
        layers, total = score_layers(row, stage, vcp, plan, mctx)
        dec = decision_from_score(total, layers)
        killswitch = not dec["tradeable"]
        dist20 = ((row["Close"] - row["SMA20"]) / row["SMA20"]) if not pd.isna(row["SMA20"]) else None
        overext = bool(cfg.max_dist_sma20 > 0 and dist20 is not None and dist20 > cfg.max_dist_sma20)
        buyable = bool(regime_open and gates_ok and total >= cfg.min_score
                       and (not cfg.require_not_killswitch or not killswitch)
                       and not overext and sym not in held)
        rows.append({
            "symbol": sym, "score": int(total), "buyable": buyable,
            "decision": dec["label"], "kill": dec.get("kill"), "overext": overext,
            "gates_ok": bool(gates_ok), "stage": int(stage["stage"]),
            "close": round(float(row["Close"]), 2),
            "entry": round(float(plan["entry"]), 2), "stop": round(float(plan["stop"]), 2),
            "target": round(float(plan["target"]), 2),
            "risk_pct": (round((plan["entry"] - plan["stop"]) / plan["entry"] * 100, 2)
                         if plan["entry"] else None),
            "rr_potential": (round(plan["rr_potential"], 2) if plan["rr_potential"] is not None else None),
            "dist_sma20_pct": (round(dist20 * 100, 2) if dist20 is not None else None),
            "earnings_days": mctx["earnings_days"], "sector_etf": SECTOR_MAP.get(sym, "—"),
            "layers": {f"L{l['id']}": l["pts"] for l in layers},
        })

    # Sıralama backtest'le AYNI: skor↓, sonra SMA20'ye yakınlık (uzaklık küçük → önce)
    buyable = sorted([r for r in rows if r["buyable"]],
                     key=lambda r: (r["score"], -(r["dist_sma20_pct"] or 0)), reverse=True)
    watch = (sorted([r for r in rows if not r["buyable"] and r["score"] >= 13 and r["gates_ok"]],
                    key=lambda r: r["score"], reverse=True) if include_watch else [])
    return {"asof": date.strftime("%Y-%m-%d"), "regime_open": regime_open,
            "spy_close": round(spy_close, 2), "n_universe": len(rows),
            "buyable": buyable, "watch": watch}


def _qswing_priority_score(rec):
    """KIRILIM adayları için 0–100 birleşik öncelik skoru (Qullamaggie hiyerarşisi).

    Bileşenler (ağırlık):
      • RS (göreli güç, 60g SPY'a karşı)        45  — birincil lider sinyali
      • 52H yakınlık (dirençsizlik)             20  — zirveye ne kadar yakın
      • Tazelik (SMA20'ye mesafe, az uzamış)    20  — kovalama değil taze giriş
      • Risk kalitesi (stop ne kadar sıkı)      15  — düşük risk% → daha iyi R:R
    Her bileşen 0–1'e normalize edilip ağırlıkla toplanır. Skor mesajda gösterilir
    ve buyable bu skora göre sıralanır.
    """
    def clip(x, lo=0.0, hi=1.0):
        return lo if x < lo else hi if x > hi else x
    rs = rec.get("rs") or 0.0
    d52 = rec.get("dist_52h_pct")
    d20 = rec.get("dist_sma20_pct")
    rk = rec.get("risk_pct")
    rs_c   = clip(rs / 60.0)                                   # RS 60+ = tam puan
    prox_c = clip(1.0 + (d52 / 10.0)) if d52 is not None else 0.5   # 0%→1, -10%→0
    fresh_c = clip(1.0 - max(0.0, (d20 - 5.0)) / 20.0) if d20 is not None else 0.5  # ≤%5→1, %25→0
    risk_c = clip(1.0 - max(0.0, (rk - 3.0)) / 6.0) if rk is not None else 0.5      # ≤%3→1, %9→0
    score = 45.0 * rs_c + 20.0 * prox_c + 20.0 * fresh_c + 15.0 * risk_c
    return round(score), {
        "rs": round(45.0 * rs_c), "near52": round(20.0 * prox_c),
        "fresh": round(20.0 * fresh_c), "risk": round(15.0 * risk_c),
    }


def run_live_qswing_scan(current_market_data, cfg=None, asof=None,
                         include_watch=True, held=None):
    """qswing KIRILIM girişi + 8/21-EMA HİBRİT çıkış — canlı tarama (son bar).

    Kapı (backtest qswing_breakout ile birebir): rejim AÇIK (SPY>SMA200) +
    Aşama 2 (fiyat > SMA20/50/200, SLOPE200>0) + `qswing_breakout_lb`-gün tepe
    KIRILIMI + 52H yakınlık + SPY'ı geçen 60g momentum (RS).
    Çıkış planı (HYBRID_TREND): %50 → **8-EMA altına KAPANINCA**,
    kalan %50 (runner) → **21-EMA altına KAPANINCA**. Sabit +2R hedefi YOK.
    İZLE = kapının diğer şartları tamam ama tepeye ≤%3 kala (henüz kırmadı).
    """
    cfg = cfg or Config()
    cfg.entry_mode = "qswing_breakout"
    cfg.exit_mode = "tp_grid"; cfg.tp_mode = "HYBRID_TREND"; cfg.ma_confirm_close = True
    held = set(held or [])
    bt = Swing2Backtester(cfg, market=current_market_data)
    cal = bt.calendar
    if asof is None:
        date = cal[-1]
    else:
        pos = int(cal.searchsorted(pd.Timestamp(asof), side="right")) - 1
        date = cal[max(0, pos)]
    common = bt._common(date)
    regime_open = bool(common["spy_above_sma200"])
    vol_locked = bt._vol_regime_locked(common)            # ATR-REJİM kilidi (opt-in; vars. kapalı)
    spy_regime_atr = common.get("spy_regime_atr_pct")
    spy_close = float(bt.spy.loc[date, "Close"])
    spy_ret60 = bt.spy.loc[date, "RET60"]
    lb = cfg.qswing_breakout_lb

    buyable, watch = [], []
    for sym, df in bt.data.items():
        if sym in held:
            continue
        row = df.loc[date]
        c = row["Close"]
        if pd.isna(c):
            continue
        pre = (regime_open and not pd.isna(row["SMA200"]) and c > row["SMA200"]
               and not pd.isna(row["SMA50"]) and c > row["SMA50"]
               and not pd.isna(row["SMA20"]) and c > row["SMA20"]
               and not pd.isna(row["SLOPE200"]) and row["SLOPE200"] > 0)
        if not pre:
            continue
        hi52, r60 = row["HIGH52"], row["RET60"]
        h = row.get(f"HIGH_PRIOR_{lb}")
        if h is None:
            h = row.get("HIGH_PRIOR")
        if pd.isna(h) or pd.isna(hi52) or pd.isna(r60):
            continue
        sp = spy_ret60 if not pd.isna(spy_ret60) else 0.0
        rs = r60 - sp
        if not (c >= cfg.qswing_near_high * hi52 and r60 > 0 and rs >= cfg.qswing_rs_min):
            continue
        if cfg.qswing_vdu_max < 9.0:
            vdu = row.get("VDU")
            if vdu is None or pd.isna(vdu) or vdu > cfg.qswing_vdu_max:
                continue
        plan = compute_trade_plan(row, cfg)
        ma10 = row.get("SMA10")
        ema8 = row.get("EMA8"); ema21 = row.get("EMA21")
        dist20 = ((c - row["SMA20"]) / row["SMA20"]) if not pd.isna(row["SMA20"]) else None
        risk = plan["entry"] - plan["stop"]
        rec = {
            "symbol": sym, "sector_etf": SECTOR_MAP.get(sym, "—"),
            "close": round(float(c), 2),
            "entry": round(float(plan["entry"]), 2), "stop": round(float(plan["stop"]), 2),
            "partial_target": round(float(plan["entry"] + 2 * risk), 2),   # referans (+2R) — hibride zorunlu değil
            "ma10": (round(float(ma10), 2) if ma10 is not None and not pd.isna(ma10) else None),
            "ema8": (round(float(ema8), 2) if ema8 is not None and not pd.isna(ema8) else None),    # %50 çıkış (hibrit)
            "ema21": (round(float(ema21), 2) if ema21 is not None and not pd.isna(ema21) else None),  # runner çıkışı (hibrit)
            # şampiyon (optimized) çıkış metni için: ATR0 + trailing çarpanı (+1R sonrası KAPANIŞ−mult×ATR)
            "atr": (round(float(row["ATR"]), 2) if not pd.isna(row["ATR"]) else None),
            "atr_trail_mult": cfg.atr_trail_mult,
            "risk_pct": (round(risk / plan["entry"] * 100, 2) if plan["entry"] else None),
            "rs": round(float(rs), 1), "ret_3m": round(float(r60), 1),
            "high40": round(float(h), 2),
            "dist_52h_pct": round((c / hi52 - 1) * 100, 1),
            "dist_sma20_pct": (round(dist20 * 100, 1) if dist20 is not None else None),
            "dist_to_breakout_pct": round((h - c) / c * 100, 2),
            "breakout_lb": lb,
            "overext": bool(dist20 is not None and dist20 > 0.25),
        }
        rec["score"], rec["score_parts"] = _qswing_priority_score(rec)
        if c > h and not rec["overext"] and vol_locked:     # kırılım var ama piyasa testere → AL'ı engelle
            rec["status"] = "İZLE"; rec["watch_reason"] = "vol_lock"; watch.append(rec)
        elif c > h and not rec["overext"]:                  # taze, sağlıklı kırılım → AL
            rec["status"] = "KIRILIM"; buyable.append(rec)
        elif c > h and rec["overext"]:                      # kırdı ama aşırı uzamış → İZLE'ye düş
            rec["status"] = "İZLE"; rec["watch_reason"] = "overext"; watch.append(rec)
        elif (h - c) / c <= 0.03:                           # tepeye ≤%3 kala → İZLE
            rec["status"] = "İZLE"; rec["watch_reason"] = "near"; watch.append(rec)
    buyable.sort(key=lambda r: r["score"], reverse=True)
    # İZLE sıralaması: önce 'tepeye yakın' (kırılıma en yakın), sonra 'aşırı uzamış' (RS güçlü)
    watch.sort(key=lambda r: (0 if r.get("watch_reason") == "near" else 1,
                              r["dist_to_breakout_pct"] if r.get("watch_reason") == "near" else -r["rs"]))
    return {"asof": date.strftime("%Y-%m-%d"), "regime_open": regime_open,
            "vol_locked": bool(vol_locked),
            "spy_atr_pct": (round(float(spy_regime_atr), 3) if spy_regime_atr is not None else None),
            "spy_close": round(spy_close, 2), "n_universe": len(bt.data),
            "buyable": buyable, "watch": (watch if include_watch else []),
            "breakout_lb": lb}


def print_live_scan(res):
    """run_live_pre_close_scan çıktısını terminale ALARM tablosu olarak basar."""
    L = "=" * 104
    flag = "AÇIK ✓" if res["regime_open"] else "KAPALI ✗  (SPY<SMA200 → yeni alım YOK)"
    print(f"\n{L}\n  CANLI KAPANIŞ-ÖNCESİ TARAMA · {res['asof']} · Rejim: {flag} · "
          f"SPY ${res['spy_close']} · {res['n_universe']} hisse\n{L}", flush=True)
    if not res["regime_open"]:
        print("  ⚠️  Piyasa rejimi KAPALI — strateji yeni pozisyon AÇMAZ; sadece açık pozisyon yönetimi.", flush=True)
    bl = res["buyable"]
    if not bl:
        print("  🟢 ALINABİLİR (skor≥16 · kill-switch temiz · kapılar açık): YOK", flush=True)
    else:
        print(f"  🟢 ALINABİLİR ({len(bl)}) — kapanışa kala (15:55 ET) gir:", flush=True)
        print(f"  {'Sembol':<8}{'Skor':>5}{'Giriş$':>10}{'Stop$':>10}{'Hedef$':>10}"
              f"{'Risk%':>7}{'R/R':>6}{'SMA20%':>8}{'Bilanço':>9}  Karar", flush=True)
        for r in bl:
            ed = "—" if r["earnings_days"] is None else f"{r['earnings_days']}g"
            print(f"  {r['symbol']:<8}{r['score']:>5}{r['entry']:>10}{r['stop']:>10}{r['target']:>10}"
                  f"{(r['risk_pct'] or 0):>6.1f}%{(r['rr_potential'] or 0):>6.1f}"
                  f"{(r['dist_sma20_pct'] or 0):>7.1f}%{ed:>9}  {r['decision']}", flush=True)
    if res["watch"]:
        print(f"\n  🟡 İZLE (skor 13-15 / eşik altı, kapılar açık) — {len(res['watch'])}:", flush=True)
        line = "  " + " · ".join(f"{r['symbol']}({r['score']}"
                                 + (f",kill:{r['kill']}" if r['kill'] else "") + ")"
                                 for r in res["watch"][:18])
        print(line, flush=True)
    print(L, flush=True)


def run_live_scan_now(cfg=None, held=None):
    """Pratik sarmalayıcı: ŞİMDİ canlı veriyi çek + kapanış-öncesi taramayı çalıştır + yazdır.
    Piyasa SAATLERİNDE, kapanışa 5-10 dk kala çağır (son bar = bugünün gün-içi barı)."""
    cfg = cfg or Config()
    market = download_and_align_data(cfg)   # piyasa açıkken SON bar = bugünün forming barı
    res = run_live_pre_close_scan(market, cfg, held=held)
    print_live_scan(res)
    return res


# =========================================================================
def main():
    cfg = Config()
    market = load_market(cfg)                      # ← veri 1 kez indirilir

    # 1) Tekli koşu (trailing + kısmi kâr alma aktif) + aylık tablo
    bt = Swing2Backtester(cfg, market=market)
    bt.run()
    full_report(bt)

    # 2) Parametre grid-search (aynı veriyle)
    grid = {"min_score": [12, 14, 16, 18], "rr_target": [2.0, 3.0, 4.0]}
    res = grid_search(cfg, grid, market)
    os.makedirs(cfg.out_dir, exist_ok=True)
    res.to_csv(os.path.join(cfg.out_dir, cfg.grid_csv), index=False)
    print("\n  GRID-SEARCH SONUÇLARI (ROI'ye göre sıralı):")
    print(res.to_string(index=False))
    print(f"\n  → En iyi: {res.iloc[0].to_dict()}")
    print(f"  CSV: {os.path.join(cfg.out_dir, cfg.grid_csv)}\n")


if __name__ == "__main__":
    main()

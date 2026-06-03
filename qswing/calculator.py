# -*- coding: utf-8 -*-
"""qswing — saf hesaplama fonksiyonları (pandas yok).

Tüm fonksiyonlar `bars` = tarihe göre ARTAN sıralı (en eski ilk) listesi bekler;
her bar bir dict: {"date": "YYYY-MM-DD", "open","high","low","close","volume"} (float).
"""
from __future__ import annotations
from typing import List, Dict, Optional


# ----------------------------------------------------------------------------- helpers
def closes_of(bars: List[Dict]) -> List[float]:
    return [float(b["close"]) for b in bars]


def sma(values: List[float], n: int) -> Optional[float]:
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / n


def sma_at(values: List[float], n: int, end: int) -> Optional[float]:
    """`end` dahil son `n` değerin ortalaması (end negatif indeks olabilir)."""
    if end < 0:
        end = len(values) + end
    start = end - n + 1
    if start < 0 or end >= len(values):
        return None
    return sum(values[start:end + 1]) / n


def ema(values: List[float], n: int) -> Optional[float]:
    """SMA tohumlu EMA; alpha = 2/(n+1). Son EMA değerini döndürür."""
    if len(values) < n:
        return None
    seed = sum(values[:n]) / n
    e = seed
    alpha = 2.0 / (n + 1)
    for v in values[n:]:
        e = v * alpha + e * (1 - alpha)
    return e


def rsi(closes: List[float], n: int = 14) -> Optional[float]:
    """Wilder RSI(14)."""
    if len(closes) < n + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(deltas)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def adr_pct(bars: List[Dict], n: int = 20) -> Optional[float]:
    """Ortalama Günlük Hareket %: mean((high-low)/low*100) son n bar."""
    if len(bars) < n:
        n = len(bars)
    if n == 0:
        return None
    seg = bars[-n:]
    vals = []
    for b in seg:
        lo = float(b["low"])
        if lo > 0:
            vals.append((float(b["high"]) - lo) / lo * 100.0)
    return sum(vals) / len(vals) if vals else None


def pct_change_n_ago(closes: List[float], n: int) -> Optional[float]:
    """`n` bar önceki kapanışa göre % değişim."""
    if len(closes) < n + 1:
        return None
    base = closes[-1 - n]
    if base == 0:
        return None
    return (closes[-1] / base - 1.0) * 100.0


def ytd_return(bars: List[Dict], year: int) -> Optional[float]:
    """Takvim yılının ilk kapanışına göre % değişim."""
    first = None
    for b in bars:
        if str(b["date"])[:4] == str(year):
            first = float(b["close"])
            break
    if first is None or first == 0:
        return None
    return (float(bars[-1]["close"]) / first - 1.0) * 100.0


# ----------------------------------------------------------------------------- RS / SPY
def rs_line(closes_t: List[float], closes_spy: List[float]) -> List[float]:
    """Hizalı (son K bar) RS çizgisi: close_t / close_spy."""
    k = min(len(closes_t), len(closes_spy))
    if k == 0:
        return []
    t = closes_t[-k:]
    s = closes_spy[-k:]
    return [t[i] / s[i] for i in range(k) if s[i] != 0]


def rs_line_is_50d_high(rs: List[float]) -> Optional[bool]:
    if len(rs) < 2:
        return None
    look = rs[-50:] if len(rs) >= 50 else rs
    return rs[-1] >= max(look)


# ----------------------------------------------------------------------------- regime
def regime_for(bars: List[Dict]) -> Dict:
    """Bir endeks (SPY/QQQ) için fiyat vs SMA50/SMA200 durumu."""
    c = closes_of(bars)
    price = c[-1] if c else None
    s50, s200 = sma(c, 50), sma(c, min(200, len(c)))
    above50 = price is not None and s50 is not None and price > s50
    above200 = price is not None and s200 is not None and price > s200
    return {"price": price, "sma50": s50, "sma200": s200,
            "above50": above50, "above200": above200,
            "healthy": above50 and above200}


# ----------------------------------------------------------------------------- ana metrikler
def compute_metrics(bars: List[Dict], spy_bars: List[Dict], quote: Dict,
                    analysis_year: int) -> Dict:
    c = closes_of(bars)
    price = float(quote.get("price") or (c[-1] if c else 0.0))
    n = len(c)

    s50 = sma(c, 50)
    s150 = sma(c, 150)
    s200_n = min(200, n)
    s200 = sma(c, s200_n)
    s200_approx = n < 200
    e10 = ema(c, 10)
    e20 = ema(c, 20)

    # SMA200 eğimi: bugünkü vs 20 bar önceki
    s200_now = sma_at(c, s200_n, -1)
    s200_prev = sma_at(c, s200_n, -21)
    s200_slope_up = (s200_now is not None and s200_prev is not None
                     and s200_now > s200_prev)

    # hacim
    vol = [float(b["volume"]) for b in bars]
    vol5 = sum(vol[-5:]) / 5 if len(vol) >= 5 else None
    vol50 = sum(vol[-50:]) / 50 if len(vol) >= 50 else None
    vdu = (vol5 / vol50 * 100.0) if (vol5 and vol50) else None

    # dolar hacmi (milyon)
    dv = None
    if n >= 1:
        seg = bars[-20:] if n >= 20 else bars
        dv = sum(float(b["close"]) * float(b["volume"]) for b in seg) / len(seg) / 1e6

    # getiriler
    ret_1m = pct_change_n_ago(c, 21)
    ret_3m = pct_change_n_ago(c, 63)
    ret_6m = pct_change_n_ago(c, 126)
    ret_ytd = ytd_return(bars, analysis_year)

    # RS vs SPY
    spy_c = closes_of(spy_bars)
    spy_ret_3m = pct_change_n_ago(spy_c, 63)
    spy_ret_6m = pct_change_n_ago(spy_c, 126)
    rs_3m = (ret_3m - spy_ret_3m) if (ret_3m is not None and spy_ret_3m is not None) else None
    rs_6m = (ret_6m - spy_ret_6m) if (ret_6m is not None and spy_ret_6m is not None) else None
    rs = rs_line(c, spy_c)
    rs50h = rs_line_is_50d_high(rs)

    # 52 hafta
    yhigh = _f(quote.get("yearHigh"))
    ylow = _f(quote.get("yearLow"))
    pct_from_high = ((price - yhigh) / yhigh * 100.0) if yhigh else None
    pct_from_low = ((price - ylow) / ylow * 100.0) if ylow else None

    adr = adr_pct(bars, 20)
    ext = None
    if s50 and adr and adr > 0:
        ext = (price - s50) / (price * adr / 100.0)

    return {
        "price": price, "n_bars": n,
        "sma50": s50, "sma150": s150, "sma200": s200, "sma200_approx": s200_approx,
        "ema10": e10, "ema20": e20,
        "rsi14": rsi(c, 14),
        "adr_pct": adr,
        "vol5": vol5, "vol50": vol50, "vdu_ratio": vdu,
        "dollar_vol_20d": dv,
        "ret_1m": ret_1m, "ret_3m": ret_3m, "ret_6m": ret_6m, "ret_ytd": ret_ytd,
        "rs_3m": rs_3m, "rs_6m": rs_6m, "rs_line_50d_high": rs50h,
        "s200_slope_up": s200_slope_up,
        "year_high": yhigh, "year_low": ylow,
        "pct_from_high": pct_from_high, "pct_from_low": pct_from_low,
        "extension_adr": ext,
        "price_above_sma200": (s200 is not None and price > s200),
        "price_above_sma150": (s150 is not None and price > s150),
        "sma150_above_sma200": (s150 is not None and s200 is not None and s150 > s200),
        "within_25pct_high": (yhigh is not None and price >= 0.75 * yhigh),
    }


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

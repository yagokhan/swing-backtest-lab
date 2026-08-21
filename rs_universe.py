"""RS evreni (günlük top-N izleme listesi).

2026-08-21: build_watchlist VEKTÖRLEŞTİRİLDİ. Orijinal uygulama
`build_watchlist_slow` adıyla AYNEN duruyor ve doğrulama/geri dönüş için
kullanılıyor. Ölçüm (canlı şekil: 373 sembol × 1543 gün):

    build_watchlist_slow : 136,7 sn
    build_watchlist_fast :   0,8 sn      (173×)
    çıktı farkı          : 1543/1543 gün BİREBİR

Canlı koşu bunu günde iki kez kuruyor (qulla_paper.load_market_incremental →
attach_watchlist), yani ~4,5 dakika/gün. Strateji DEĞİŞMEZ: aynı girdiye aynı
izleme listesi → aynı alım/satım kararları. Sadakat kapısı bunun tek güvencesi.

GÜVENLİK ANAHTARLARI (kod düzenlemeden):
    RS_WATCHLIST_SLOW=1    → anında geri dönüş, eski yolu kullan
    RS_WATCHLIST_VERIFY=1  → iki yolu da koş, farklıysa RuntimeError (fail-closed)
"""
import os

import numpy as np
import pandas as pd


def rs_score(closes, asof, weights=(0.2, 0.4, 0.4), skip=5, windows=(21, 63, 126)):
    """Blended trailing-return momentum as of `asof`, using only bars < asof."""
    prior = closes[closes.index < asof].dropna()
    need = max(windows) + skip + 1
    if len(prior) < need:
        return float("nan")
    end = len(prior) - 1 - skip            # recent bar, skipping last `skip` bars
    px = prior.iloc[end]
    total = 0.0
    for w, win in zip(weights, windows):
        total += w * (px / prior.iloc[end - win] - 1.0)
    return float(total)


def build_watchlist_slow(data, dates, n=50, weights=(0.2, 0.4, 0.4), skip=5,
                         windows=(21, 63, 126), dollar_vol_floor=0.0, vol_window=21):
    """For each date, rank the pool by rs_score (after a liquidity floor) and keep top-n.

    ORİJİNAL uygulama — DEĞİŞTİRİLMEDİ. Referans/doğrulama yolu."""
    out = {}
    for date in dates:
        ranked = []
        for sym, df in data.items():
            if dollar_vol_floor > 0.0:
                prior = df[df.index < date]
                if len(prior) < vol_window:
                    continue
                dv = (prior["Close"] * prior["Volume"]).tail(vol_window).mean()
                if not (dv >= dollar_vol_floor):
                    continue
            sc = rs_score(df["Close"], date, weights=weights, skip=skip, windows=windows)
            if sc == sc:                          # not NaN
                ranked.append((sc, sym))
        ranked.sort(reverse=True)
        out[date] = {sym for _, sym in ranked[:n]}
    return out


# =========================================================================
# VEKTÖREL YOL — build_watchlist_slow ile BİREBİR aynı semantik
# =========================================================================
def _rs_matrix(close, weights, skip, windows):
    """rs_score()'un tüm (tarih × sembol) matrisi.

    Orijinal semantik: prior = closes[index < asof].dropna();
    end = len(prior)-1-skip; score = Σ wᵢ·(prior[end]/prior[end-winᵢ] − 1).

    Sembolün KENDİ dropna'lı serisinde f = Σ wᵢ(p/p.shift(winᵢ)−1) hesaplanır,
    g = f.shift(skip) alınır; takvime reindex + shift(1) + ffill ile "d'den
    KESİNLİKLE önceki son bar" okunur. Tarih başına yeniden dilimleme yok."""
    cal = close.index
    need = max(windows) + skip + 1
    nan_col = np.full(len(cal), np.nan)
    cols = {}
    for s in close.columns:
        p = close[s].dropna().astype(np.float64)
        if len(p) < need:
            cols[s] = nan_col
            continue
        f = None
        for w, win in zip(weights, windows):
            term = w * (p / p.shift(win) - 1.0)
            f = term if f is None else f + term
        cols[s] = f.shift(skip).reindex(cal).shift(1).ffill().to_numpy(dtype=np.float64)
    return pd.DataFrame(cols, index=cal, columns=close.columns, copy=False)


def _dv_gate(close, volume, dollar_vol_floor, vol_window=21):
    """Likidite kapısının vektörel eşi (orijinalle birebir):
      prior = df[df.index < date]  (dropna YOK — takvim satırı)
      len(prior) < vol_window → ele
      dv = (prior.Close*prior.Volume).tail(vol_window).mean()  (NaN atlar)"""
    if not dollar_vol_floor or dollar_vol_floor <= 0:
        return pd.DataFrame(True, index=close.index, columns=close.columns)
    dv = close.astype(np.float64) * volume.astype(np.float64)
    roll = dv.rolling(vol_window, min_periods=1).mean().shift(1)
    gate = roll >= dollar_vol_floor
    gate.iloc[:vol_window] = False
    return gate.fillna(False)


def _topn(rs, gate, n):
    """Kapıyı geçenler arasında RS top-n.

    Eşitlik bozma orijinalle aynı: ranked.sort(reverse=True) demek (skor, sembol)
    ikilisinde skor eşitse sembol adı BÜYÜKTEN küçüğe demektir. Sütunlar isme
    göre tersten sıralanıp KARARLI argsort ile bu birebir taklit edilir."""
    cols = sorted(rs.columns, reverse=True)
    R = rs[cols].to_numpy(dtype=np.float64, copy=True)
    G = gate[cols].to_numpy(dtype=bool, copy=False)
    R[~G] = np.nan
    valid = ~np.isnan(R)
    idx = np.argsort(np.where(valid, -R, np.inf), axis=1, kind="stable")[:, :n]
    colarr = np.array(cols, dtype=object)
    out = {}
    for i, date in enumerate(rs.index):
        row = idx[i]
        out[date] = set(colarr[row[valid[i, row]]])
    return out


def build_watchlist_fast(data, dates, n=50, weights=(0.2, 0.4, 0.4), skip=5,
                         windows=(21, 63, 126), dollar_vol_floor=0.0, vol_window=21):
    """build_watchlist_slow ile aynı imza, aynı çıktı — vektörel."""
    cal = pd.DatetimeIndex(dates)
    syms = list(data.keys())
    if not syms:
        return {d: set() for d in cal}
    close = pd.DataFrame({s: data[s]["Close"].reindex(cal) for s in syms}, index=cal)
    vol = pd.DataFrame({s: data[s]["Volume"].reindex(cal) for s in syms}, index=cal)
    rs = _rs_matrix(close, weights, skip, windows)
    gate = _dv_gate(close, vol, dollar_vol_floor, vol_window)
    return _topn(rs, gate, n)


def build_watchlist(data, dates, n=50, weights=(0.2, 0.4, 0.4), skip=5,
                    windows=(21, 63, 126), dollar_vol_floor=0.0, vol_window=21):
    """Günlük top-N izleme listesi. Varsayılan: vektörel yol.

    RS_WATCHLIST_SLOW=1   → eski yol (anında geri dönüş)
    RS_WATCHLIST_VERIFY=1 → ikisini de koş, fark varsa DUR (fail-closed).
                            Yanlış evrenle sessizce yayın yapmaktansa durmak yeğdir."""
    kw = dict(n=n, weights=weights, skip=skip, windows=windows,
              dollar_vol_floor=dollar_vol_floor, vol_window=vol_window)

    if os.environ.get("RS_WATCHLIST_SLOW") == "1":
        return build_watchlist_slow(data, dates, **kw)

    fast = build_watchlist_fast(data, dates, **kw)

    if os.environ.get("RS_WATCHLIST_VERIFY") == "1":
        slow = build_watchlist_slow(data, dates, **kw)
        bad = [d for d in pd.DatetimeIndex(dates) if slow.get(d, set()) != fast.get(d, set())]
        if bad:
            raise RuntimeError(
                f"RS izleme listesi DOĞRULAMA HATASI: {len(bad)} gün farklı "
                f"(ilk: {bad[0]}). Yanlış evrenle devam edilmez. "
                f"RS_WATCHLIST_SLOW=1 ile eski yola dön.")
        print(f"RS doğrulama: {len(pd.DatetimeIndex(dates))} gün birebir ✅", flush=True)

    return fast

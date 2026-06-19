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

def build_watchlist(data, dates, n=50, weights=(0.2, 0.4, 0.4), skip=5,
                    windows=(21, 63, 126), dollar_vol_floor=0.0, vol_window=21):
    """For each date, rank the pool by rs_score (after a liquidity floor) and keep top-n."""
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

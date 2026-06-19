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

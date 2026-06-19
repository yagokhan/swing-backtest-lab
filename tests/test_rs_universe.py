import numpy as np, pandas as pd, pytest
from rs_universe import rs_score, build_watchlist

def _series(values, start="2021-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)

def _frame(close_vals, vol=1e9, start="2021-01-01"):
    idx = pd.bdate_range(start, periods=len(close_vals))
    return pd.DataFrame({"Close": close_vals, "Volume": [vol] * len(close_vals)}, index=idx)

def test_rs_score_blends_window_returns():
    # 200 bars rising 1%/bar geometrically → known trailing returns
    vals = [100 * (1.01 ** i) for i in range(200)]
    s = _series(vals)
    asof = s.index[180]                      # bars < asof = first 180
    score = rs_score(s, asof, weights=(0.2, 0.4, 0.4), skip=5, windows=(21, 63, 126))
    # end bar = last bar before asof (idx 179) minus skip(5) = idx 174
    end = 174
    r21 = vals[end] / vals[end - 21] - 1
    r63 = vals[end] / vals[end - 63] - 1
    r126 = vals[end] / vals[end - 126] - 1
    expected = 0.2 * r21 + 0.4 * r63 + 0.4 * r126
    assert score == pytest.approx(expected, rel=1e-9)

def test_rs_score_nan_when_insufficient_history():
    s = _series([100 + i for i in range(50)])   # < 126 + skip bars
    assert np.isnan(rs_score(s, s.index[40]))

def test_rs_score_ignores_asof_and_future_bars():
    vals = [100 * (1.005 ** i) for i in range(200)]
    s = _series(vals)
    asof = s.index[150]
    base = rs_score(s, asof)
    # mutate the asof bar and every bar after it
    mutated = s.copy()
    mutated.iloc[150:] = mutated.iloc[150:] * 99.0
    assert rs_score(mutated, asof) == pytest.approx(base, rel=1e-12)
    # mutating a bar within the lookback window must change the score (sanity: guard isn't trivially constant)
    mutated2 = s.copy()
    mutated2.iloc[123] = mutated2.iloc[123] * 1.5
    assert rs_score(mutated2, asof) != pytest.approx(base, rel=1e-12)

def test_build_watchlist_picks_top_n_by_score():
    n_bars = 200
    strong = _frame([100 * (1.02 ** i) for i in range(n_bars)])   # steep
    mid    = _frame([100 * (1.01 ** i) for i in range(n_bars)])
    weak   = _frame([100 * (1.001 ** i) for i in range(n_bars)])  # flat-ish
    data = {"STRONG": strong, "MID": mid, "WEAK": weak}
    date = strong.index[180]
    wl = build_watchlist(data, [date], n=2)
    assert wl[date] == {"STRONG", "MID"}        # WEAK excluded by rank

def test_build_watchlist_applies_liquidity_floor():
    n_bars = 200
    strong_illiquid = _frame([100 * (1.02 ** i) for i in range(n_bars)], vol=1.0)  # tiny $vol
    mid_liquid      = _frame([100 * (1.01 ** i) for i in range(n_bars)], vol=1e9)
    data = {"STRONG_ILLIQ": strong_illiquid, "MID_LIQ": mid_liquid}
    date = mid_liquid.index[180]
    wl = build_watchlist(data, [date], n=2, dollar_vol_floor=1e6)
    assert wl[date] == {"MID_LIQ"}              # strong-but-illiquid filtered out

def test_sp500_ndx_preset_is_union():
    import swing2_backtest as sb
    pool = set(sb.UNIVERSE_PRESETS["sp500_ndx"])
    assert set(sb.UNIVERSE_PRESETS["sp500"]).issubset(pool)
    assert set(sb.UNIVERSE_PRESETS["nasdaq100"]).issubset(pool)
    assert len(pool) == len(sb.UNIVERSE_PRESETS["sp500_ndx"])   # no dups

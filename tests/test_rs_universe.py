import numpy as np, pandas as pd, pytest
from rs_universe import rs_score

def _series(values, start="2021-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)

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

import pandas as pd
import swing2_backtest as sb
from rs_universe import build_watchlist

def _fake_market():
    idx = pd.bdate_range("2021-01-01", periods=200)
    def _frame(mult):
        return pd.DataFrame({"Close": [100 * (mult ** i) for i in range(200)],
                             "Volume": [1e9] * 200}, index=idx)
    return {"data": {"AAA": _frame(1.02), "BBB": _frame(1.01), "CCC": _frame(1.001)},
            "spy": _frame(1.005), "sectors": {}, "earnings": {},
            "calendar": idx, "vcp_cache": {}}

def test_load_market_attaches_watchlist_when_enabled(monkeypatch):
    fake = _fake_market()
    monkeypatch.setattr(sb, "download_and_align_data", lambda cfg: fake)
    cfg = sb.Config()
    cfg.use_rs_universe = True
    cfg.rs_n = 2
    cfg.universe = ("AAA", "BBB", "CCC")
    market = sb.load_market(cfg)
    assert market["watchlist"] is not None
    # top-2 by momentum on the last calendar date = the two steepest growers
    last = market["calendar"][-1]
    assert market["watchlist"][last] == {"AAA", "BBB"}

def test_load_market_no_watchlist_when_disabled(monkeypatch):
    fake = _fake_market()
    monkeypatch.setattr(sb, "download_and_align_data", lambda cfg: fake)
    cfg = sb.Config()
    cfg.use_rs_universe = False
    market = sb.load_market(cfg)
    assert market["watchlist"] is None

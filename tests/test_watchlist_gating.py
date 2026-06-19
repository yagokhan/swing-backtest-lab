import inspect
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

def test_in_watchlist_gate(monkeypatch):
    import pandas as pd
    idx = pd.bdate_range("2021-01-01", periods=10)
    cfg = sb.Config(); cfg.use_rs_universe = True
    bt = sb.Swing2Backtester.__new__(sb.Swing2Backtester)   # bypass heavy __init__
    bt.cfg = cfg
    bt.watchlist = {idx[5]: {"AAA"}}
    # member on a known date
    assert bt._in_watchlist("AAA", idx[5]) is True
    # non-member on a known date
    assert bt._in_watchlist("ZZZ", idx[5]) is False
    # date absent from watchlist → no entries allowed that day
    assert bt._in_watchlist("AAA", idx[9]) is False
    # toggle off → everything allowed (back-compat)
    cfg.use_rs_universe = False
    assert bt._in_watchlist("ZZZ", idx[9]) is True

def test_open_position_survives_leaving_watchlist(monkeypatch):
    """A held name that drops out of the watchlist must NOT be force-closed."""
    import pandas as pd
    idx = pd.bdate_range("2021-01-01", periods=3)
    cfg = sb.Config(); cfg.use_rs_universe = True
    bt = sb.Swing2Backtester.__new__(sb.Swing2Backtester)
    bt.cfg = cfg
    bt.watchlist = {idx[0]: {"AAA"}, idx[1]: set(), idx[2]: set()}
    # AAA is a member only on day 0; gating affects entries, not exits:
    assert bt._in_watchlist("AAA", idx[0]) is True
    assert bt._in_watchlist("AAA", idx[1]) is False
    # The exit path (_manage) never calls _in_watchlist — verified by code inspection:
    # the gate is only in run()'s entry-candidate loop, not in _manage().

def test_exit_path_never_consults_watchlist():
    """Invariant: the watchlist gates ENTRIES only. _manage (the exit/position-
    management path) must never reference the watchlist — a future refactor that
    gates exits would break the strategy's design and must fail here."""
    src = inspect.getsource(sb.Swing2Backtester._manage)
    assert "watchlist" not in src, "_manage must not consult the watchlist (exits are never gated)"
    assert "_in_watchlist" not in src, "_manage must not call _in_watchlist (exits are never gated)"

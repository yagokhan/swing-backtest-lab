import beklenti_lab as bl


def test_pct_rank():
    assert bl.pct_rank([1, 2, 3, 4], 2.5) == 50.0
    assert bl.pct_rank([1, 2, 3, 4], 0) == 0.0
    assert bl.pct_rank([1, 2, 3, 4], 4) == 100.0


def test_max_drawdown():
    assert bl.max_drawdown([100, 110, 99, 121]) == round((99 / 110 - 1) * 100, 4)
    assert bl.max_drawdown([100, 101, 102]) == 0.0


def test_window_starts():
    idx = bl.window_starts(n_cal=100, step=10, first_idx=5, force_idx=42, nwin=56)
    assert 42 in idx
    assert all(i + 56 - 1 < 100 for i in idx)      # pencere takvimden taşmaz
    assert all(i >= 5 for i in idx)
    assert idx == sorted(set(idx))


def test_roi():
    assert bl.roi(10000, 10224.77) == round(2.2477, 4)


def test_shares_on():
    # bugün 6 adet açık; 2 adetlik bacak 07-15'te çıkmış → 07-01'de 8, 07-20'de 6 adet tutuluyordu
    exits = [{"exit_date": "2026-07-15", "shares": 2.0}]
    assert bl.shares_on(6.0, exits, "2026-07-01") == 8.0
    assert bl.shares_on(6.0, exits, "2026-07-20") == 6.0

"""pit_universe testleri — semantik + look-ahead kanıtı. Piyasa verisi gerektirmez."""
import numpy as np
import pandas as pd
import pytest

import pit_universe as pu
import rs_universe as ru


def _cal(n=400, start="2021-01-04"):
    return pd.bdate_range(start, periods=n)


def _series(n=400, p0=50.0, drift=0.0008, seed=0):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, 0.02, n)
    return p0 * np.exp(np.cumsum(r))


# ---------------------------------------------------------------- pit_mask
def test_mask_fiyat_esigi():
    cal = _cal(300)
    close = pd.DataFrame({"A": np.r_[np.full(150, 5.0), np.full(150, 20.0)]}, index=cal)
    vol = pd.DataFrame({"A": np.full(300, 1e7)}, index=cal)
    m = pu.pit_mask(close, vol, min_dollar_vol=0, min_history=0, causal_shift=0)
    assert not m["A"].iloc[100]        # $5 < $10
    assert m["A"].iloc[200]            # $20 >= $10


def test_mask_likidite_esigi():
    cal = _cal(300)
    close = pd.DataFrame({"A": np.full(300, 100.0)}, index=cal)
    # 20g ADV: ilk yarı 100*10k=1M (düşük), ikinci yarı 100*1M=100M (yüksek)
    vol = pd.DataFrame({"A": np.r_[np.full(150, 1e4), np.full(150, 1e6)]}, index=cal)
    m = pu.pit_mask(close, vol, min_history=0, causal_shift=0)
    assert not m["A"].iloc[140]
    assert m["A"].iloc[290]


def test_mask_gecmis_sarti():
    cal = _cal(300)
    close = pd.DataFrame({"A": np.full(300, 100.0)}, index=cal)
    vol = pd.DataFrame({"A": np.full(300, 1e6)}, index=cal)
    m = pu.pit_mask(close, vol, min_history=200, causal_shift=0)
    assert not m["A"].iloc[198]        # 199 bar
    assert m["A"].iloc[199]            # 200. bar


def test_mask_islem_gormeyen_gun_elenir():
    cal = _cal(300)
    c = np.full(300, 100.0); c[250] = np.nan
    close = pd.DataFrame({"A": c}, index=cal)
    vol = pd.DataFrame({"A": np.full(300, 1e6)}, index=cal)
    m = pu.pit_mask(close, vol, min_history=0, causal_shift=0)
    assert not m["A"].iloc[250]


def test_mask_olu_hisse_olumden_sonra_kapali():
    """Delist olan hissenin ölüm gününden SONRA maskesi kapalı olmalı."""
    cal = _cal(400)
    c = np.full(400, 100.0); c[300:] = np.nan
    v = np.full(400, 1e6); v[300:] = np.nan
    m = pu.pit_mask(pd.DataFrame({"A": c}, index=cal),
                    pd.DataFrame({"A": v}, index=cal),
                    min_history=0, causal_shift=0)
    assert m["A"].iloc[299]
    assert not m["A"].iloc[300:].any()


# ------------------------------------------------------- LOOK-AHEAD KANITI
def test_maske_gelecege_bakmaz():
    """GELECEĞİ değiştir → GEÇMİŞ maske bit-bit aynı kalmalı.
    Bu, look-ahead'in yokluğunun yapısal kanıtıdır."""
    cal = _cal(400)
    px = _series(400, seed=5)
    close = pd.DataFrame({"A": px}, index=cal)
    vol = pd.DataFrame({"A": np.full(400, 2e6)}, index=cal)
    m1 = pu.pit_mask(close, vol, min_history=200)

    close2 = close.copy(); vol2 = vol.copy()
    close2.iloc[350:] = 9999.0                  # gelecekte devasa fiyat
    vol2.iloc[350:] = 1e12                      # gelecekte devasa hacim
    m2 = pu.pit_mask(close2, vol2, min_history=200)

    pd.testing.assert_series_equal(m1["A"].iloc[:350], m2["A"].iloc[:350])


def test_causal_shift_bir_gun_geriden():
    cal = _cal(300)
    close = pd.DataFrame({"A": np.r_[np.full(150, 5.0), np.full(150, 20.0)]}, index=cal)
    vol = pd.DataFrame({"A": np.full(300, 1e7)}, index=cal)
    m0 = pu.pit_mask(close, vol, min_dollar_vol=0, min_history=0, causal_shift=0)
    m1 = pu.pit_mask(close, vol, min_dollar_vol=0, min_history=0, causal_shift=1)
    assert m0["A"].iloc[150] and not m1["A"].iloc[150]     # eşiğe geçiş günü
    assert m1["A"].iloc[151]
    assert not m1["A"].iloc[0]


def test_rs_matrix_gelecege_bakmaz():
    cal = _cal(400)
    close = pd.DataFrame({"A": _series(400, seed=9)}, index=cal)
    r1 = pu.rs_matrix(close)
    close2 = close.copy(); close2.iloc[350:] = 9999.0
    r2 = pu.rs_matrix(close2)
    pd.testing.assert_series_equal(r1["A"].iloc[:350], r2["A"].iloc[:350])


# ------------------------------------------------- rs_matrix == rs_score
def test_rs_matrix_orijinalle_birebir():
    cal = _cal(400)
    close = pd.DataFrame({s: _series(400, seed=i) for i, s in enumerate("ABCDE")}, index=cal)
    fast = pu.rs_matrix(close)
    for s in close.columns:
        for i in (200, 260, 333, 399):
            d = cal[i]
            ref = ru.rs_score(close[s], d)
            got = fast[s].iloc[i]
            if ref != ref:
                assert got != got, f"{s}@{d}: orijinal NaN, vektörel {got}"
            else:
                assert got == pytest.approx(ref, rel=1e-9), f"{s}@{d}"


def test_rs_matrix_bosluklu_seride_birebir():
    """Sembolün eksik günleri (NaN) varken de dropna-pozisyonel semantik korunmalı."""
    cal = _cal(400)
    px = _series(400, seed=3)
    px[[80, 81, 150, 222, 305]] = np.nan
    close = pd.DataFrame({"A": px}, index=cal)
    fast = pu.rs_matrix(close)
    for i in (250, 300, 306, 399):
        d = cal[i]
        ref = ru.rs_score(close["A"], d)
        got = fast["A"].iloc[i]
        assert got == pytest.approx(ref, rel=1e-9), f"@{d} ref={ref} got={got}"


def test_rs_matrix_yetersiz_gecmis_nan():
    cal = _cal(400)
    close = pd.DataFrame({"A": _series(400, seed=1)}, index=cal)
    fast = pu.rs_matrix(close)
    assert np.isnan(fast["A"].iloc[:132]).all()      # 126+5+1 = 132 bar gerekir


# --------------------------------------- legacy kapı + sıralama == orijinal
def test_legacy_dv_gate_orijinalle_birebir():
    cal = _cal(300)
    close = pd.DataFrame({"A": _series(300, seed=2), "B": _series(300, p0=8, seed=4)}, index=cal)
    vol = pd.DataFrame({"A": np.full(300, 5e5), "B": np.full(300, 3e6)}, index=cal)
    floor = 1e7
    gate = pu.legacy_dv_gate(close, vol, floor)
    for s in ("A", "B"):
        df = pd.DataFrame({"Close": close[s], "Volume": vol[s]})
        for i in (10, 21, 100, 299):
            d = cal[i]
            prior = df[df.index < d]
            ref = len(prior) >= 21 and bool((prior["Close"] * prior["Volume"]).tail(21).mean() >= floor)
            assert bool(gate[s].iloc[i]) == ref, f"{s}@{d}"


def test_watchlist_esitlik_bozma_orijinalle_ayni():
    """Skorlar eşitse orijinal (skor, sembol) ikilisini TERSTEN sıralar → büyük isim önce."""
    cal = _cal(3)
    rs = pd.DataFrame({"AAA": [1.0]*3, "ZZZ": [1.0]*3, "MMM": [1.0]*3}, index=cal)
    gate = pd.DataFrame(True, index=cal, columns=rs.columns)
    got = pu.build_watchlist_fast(rs, gate, n=2)
    ranked = sorted([(1.0, s) for s in rs.columns], reverse=True)
    assert got[cal[0]] == {s for _, s in ranked[:2]} == {"ZZZ", "MMM"}


def test_watchlist_kapidan_gecemeyen_yarisa_girmez():
    cal = _cal(2)
    rs = pd.DataFrame({"A": [9.0, 9.0], "B": [1.0, 1.0]}, index=cal)
    gate = pd.DataFrame({"A": [False, False], "B": [True, True]}, index=cal)
    got = pu.build_watchlist_fast(rs, gate, n=5)
    assert got[cal[0]] == {"B"}


def test_watchlist_nan_skor_secilmez():
    cal = _cal(2)
    rs = pd.DataFrame({"A": [np.nan, np.nan], "B": [1.0, 1.0]}, index=cal)
    gate = pd.DataFrame(True, index=cal, columns=rs.columns)
    got = pu.build_watchlist_fast(rs, gate, n=5)
    assert got[cal[0]] == {"B"}


# ------------------------------------------------------------- yardımcılar
def test_peak_adv_kisa_seri_sifir():
    assert pu._peak_adv(np.array([1.0, 2.0]), np.array([1.0, 2.0]), window=20) == 0.0


def test_clean_ticker_filtresi():
    ok = ["AAPL", "F", "GOOGL", "SIVB"]
    no = ["NB2.F", "BRK-B", "ABCDEF", "aapl", "SPY.L"]
    assert all(pu._CLEAN_TICKER.match(s) for s in ok)
    assert not any(pu._CLEAN_TICKER.match(s) for s in no)


def test_to_panel_fill_yapmaz():
    cal = _cal(10)
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0},
                      index=cal[[0, 1, 5]])
    close, vol = pu.to_panel({"A": df}, cal)
    assert close["A"].notna().sum() == 3          # doldurulmadı
    assert np.isnan(close["A"].iloc[2])

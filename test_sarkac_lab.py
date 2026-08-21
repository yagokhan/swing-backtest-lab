"""Sarkaç-14 testleri — RSI doğruluğu, Pine durum makinesi, motor, look-ahead."""
import numpy as np
import pandas as pd
import pytest

import sarkac_lab as sl


def _idx(n, start="2020-01-01"):
    return pd.bdate_range(start, periods=n)


# ------------------------------------------------------------------ RSI
def test_rsi_wilder_elle_hesapla_ayni():
    rng = np.random.default_rng(3)
    px = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))), index=_idx(400))
    got = float(sl.rsi_tv(px, 14).iloc[-1])
    c = px.to_numpy(float); n = 14
    g = np.zeros(len(c)); l = np.zeros(len(c))
    for i in range(1, len(c)):
        ch = c[i] - c[i - 1]; g[i] = max(ch, 0.0); l[i] = max(-ch, 0.0)
    ag = g[1:n + 1].mean(); al = l[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        ag = (ag * (n - 1) + g[i]) / n; al = (al * (n - 1) + l[i]) / n
    assert got == pytest.approx(100 - 100 / (1 + ag / al), abs=1e-6)


def test_rsi_araligi_0_100():
    rng = np.random.default_rng(7)
    px = pd.Series(50 * np.exp(np.cumsum(rng.normal(0, 0.03, 600))), index=_idx(600))
    r = sl.rsi_tv(px, 14).dropna()
    assert r.min() >= 0.0 and r.max() <= 100.0


def test_rsi_kesintisiz_yukselis_100():
    px = pd.Series(np.arange(1, 60, dtype=float), index=_idx(59))
    assert float(sl.rsi_tv(px, 14).iloc[-1]) == pytest.approx(100.0)


def test_rsi_ilk_n_bar_nan():
    """diff() ilk barı yer; RSI ancak 14 GEÇERLİ değişimden sonra tanımlıdır → indeks 14."""
    px = pd.Series(np.linspace(10, 20, 40), index=_idx(40))
    r = sl.rsi_tv(px, 14)
    assert r.iloc[:14].isna().all()
    assert not np.isnan(r.iloc[14])


# -------------------------------------------------- Pine durum makinesi
def test_durum_makinesi_histerezis():
    """Arka arkaya aşırı-satım barları TEKRAR sinyal üretmez."""
    r = pd.Series([50, 25, 25, 25, 80, 20], index=_idx(6), dtype=float)
    st = sl.swing_states(r, 70, 30)
    assert list(st["to_os"]) == [False, False, False, False, False, True]
    assert list(st["to_ob"]) == [False, False, False, False, True, False]


def test_durum_makinesi_onceki_bara_bakar():
    """Geçiş kontrolü durum güncellenmeden ÖNCEKİ değere bakar (Pine sırası)."""
    r = pd.Series([25, 75], index=_idx(2), dtype=float)
    st = sl.swing_states(r, 70, 30)
    assert st["to_ob"].iloc[1]          # OS(2) → OB geçişi
    assert list(st["state"]) == [2, 1]


def test_sinyaller_alternans_bozulmaz():
    rng = np.random.default_rng(11)
    r = pd.Series(rng.uniform(5, 95, 3000), index=_idx(3000))
    sg = sl.signals(r, 70, 30, start_mode="flat")
    seq = sorted([(t, "AL") for t in sg.index[sg["buy"]]] +
                 [(t, "SAT") for t in sg.index[sg["sell"]]])
    assert not any(seq[i][1] == seq[i - 1][1] for i in range(1, len(seq)))


def test_start_mode_pine_ilk_alimi_atlar():
    r = pd.Series([25, 75, 25], index=_idx(3), dtype=float)
    assert not sl.signals(r, 70, 30, "pine")["buy"].iloc[0]
    assert sl.signals(r, 70, 30, "flat")["buy"].iloc[0]


def test_nan_rsi_durumu_bozmaz():
    r = pd.Series([25, np.nan, np.nan, 75], index=_idx(4))
    st = sl.swing_states(r, 70, 30)
    assert list(st["state"]) == [2, 2, 2, 1]
    assert st["to_ob"].iloc[3]


# --------------------------------------------------------------- motor
def _synth(n=400):
    idx = _idx(n)
    q = pd.Series(100 + 20 * np.sin(np.arange(n) / 12.0), index=idx)   # salınım
    t = pd.DataFrame({"Open": q * 3, "High": q * 3, "Low": q * 3,
                      "Close": q * 3, "Volume": 1e7}, index=idx)
    return q, t


def test_backtest_alternans_uygular():
    q, t = _synth()
    r = sl.backtest(q, t, start_mode="flat")
    for x in r["trades"]:
        assert x["out"] > x["in"]
        assert x["bars"] > 0


def test_backtest_nakitken_satmaz_pozisyondayken_ikinci_kez_almaz():
    q, t = _synth()
    r = sl.backtest(q, t)
    # her işlem kapanmış olmalı (açık hariç) ve üst üste binmemeli
    spans = [(x["in"], x["out"]) for x in r["trades"]]
    for i in range(1, len(spans)):
        assert spans[i][0] >= spans[i - 1][1]


def test_maliyetler_getiriyi_dusurur():
    q, t = _synth()
    ucuz = sl.backtest(q, t, commission=0.0, entry_bps=0.0, exit_bps=0.0)
    pahali = sl.backtest(q, t, commission=5.0, entry_bps=50.0, exit_bps=50.0)
    assert float(pahali["equity"].iloc[-1]) < float(ucuz["equity"].iloc[-1])


def test_exposure_0_1_arasi():
    q, t = _synth()
    r = sl.backtest(q, t)
    assert 0.0 <= r["exposure"] <= 1.0


def test_sinyal_yoksa_sermaye_sabit():
    idx = _idx(300)
    q = pd.Series(np.linspace(100, 101, 300), index=idx)     # RSI hep ortada
    t = pd.DataFrame({"Open": q * 3, "High": q * 3, "Low": q * 3,
                      "Close": q * 3, "Volume": 1e7}, index=idx)
    r = sl.backtest(q, t)
    assert r["trades"] == []
    assert float(r["equity"].iloc[-1]) == pytest.approx(sl.INITIAL_CAPITAL)


# --------------------------------------------------- LOOK-AHEAD KANITI
def test_gelecegi_degistir_gecmis_sinyaller_ayni():
    """Geleceği değiştir → geçmiş sinyaller bit-bit aynı kalmalı."""
    q, _ = _synth(400)
    a = sl.signals(sl.rsi_tv(q, 14), 70, 30)
    q2 = q.copy(); q2.iloc[300:] = 9999.0
    b = sl.signals(sl.rsi_tv(q2, 14), 70, 30)
    pd.testing.assert_series_equal(a["buy"].iloc[:300], b["buy"].iloc[:300])
    pd.testing.assert_series_equal(a["sell"].iloc[:300], b["sell"].iloc[:300])


def test_gelecegi_degistir_gecmis_islemler_ayni():
    q, t = _synth(400)
    r1 = sl.backtest(q, t, end=str(q.index[299].date()))
    q2 = q.copy(); q2.iloc[300:] = 9999.0
    t2 = t.copy(); t2.iloc[300:] = 9999.0
    r2 = sl.backtest(q2, t2, end=str(q.index[299].date()))
    assert r1["trades"] == r2["trades"]


def test_islem_fiyati_sinyal_gunu_kapanisindan():
    q, t = _synth(400)
    r = sl.backtest(q, t, entry_bps=0.0, exit_bps=0.0, commission=0.0)
    if r["trades"]:
        x = r["trades"][0]
        # defterde fiyatlar 4 haneye yuvarlanıyor
        assert x["entry"] == pytest.approx(
            round(float(t["Close"].loc[pd.Timestamp(x["in"])]), 4), abs=1e-4)


# ═══════════════════ JSON GEÇERLİLİĞİ (tarayıcı katı, Python değil) ═══════════
# Python'un json'ı Infinity/NaN'ı hem YAZAR hem OKUR — bu yüzden Python ile
# yapılan doğrulama yalancı geçer. Tarayıcının JSON.parse'ı bunları REDDEDER
# ("Unexpected token 'I'"). Testler bu yüzden allow_nan=False ile koşar.
def _strict(obj):
    import json
    return json.dumps(obj, allow_nan=False)


def test_pf_zarar_yoksa_none_olur():
    """Zarar eden işlem yoksa PF sonsuzdur → JSON'da Infinity olamaz, None döner."""
    tr = [{"pnl": 100.0, "pct": 5.0, "bars": 3, "in": "2020-01-01", "out": "2020-01-06"}]
    m = sl.metrics(pd.Series([10000.0, 10100.0], index=_idx(2)), tr, 0.5)
    assert m["profit_factor"] is None
    _strict(m)


def test_metrics_her_zaman_gecerli_json():
    q, t = _synth(400)
    r = sl.backtest(q, t)
    m = sl.metrics(r["equity"], r["trades"], r["exposure"], open_trade=r["open"])
    _strict(m)                                  # ValueError atarsa test kırılır


def test_bh_metrics_gecerli_json():
    q, t = _synth(400)
    r = sl.backtest(q, t)
    _strict(sl.bh_metrics(sl.buy_hold(t["Close"], r["calendar"])))


def test_json_safe_sonsuzu_temizler():
    """server._json_safe: inf/-inf/NaN → None, iç içe yapılarda da."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "srv_", "/home/gokhan/swing-backtest-lab/server.py")
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    kirli = {"a": float("inf"), "b": [1.0, float("-inf"), {"c": float("nan")}],
             "d": "metin", "e": 3, "f": None}
    temiz = srv._json_safe(kirli)
    assert temiz["a"] is None
    assert temiz["b"][1] is None and temiz["b"][2]["c"] is None
    assert temiz["d"] == "metin" and temiz["e"] == 3
    _strict(temiz)


# ═════════════════ giriş zamanlaması: bölgeye giriş vs bölgeden çıkış ═════════
def test_exit_signals_bolgeden_cikista_tetikler():
    """touch: 30'a değince AL · exit: 30'un üstüne DÖNÜNCE AL."""
    r = pd.Series([50, 25, 22, 28, 45, 80, 75, 60], index=_idx(8), dtype=float)
    touch = sl.signals(r, 70, 30, signal_mode="touch")
    ex = sl.signals(r, 70, 30, signal_mode="exit")
    assert touch["buy"].iloc[1] and not touch["buy"].iloc[4]      # ilk temas
    assert ex["buy"].iloc[4] and not ex["buy"].iloc[1]            # bölgeden çıkış
    assert touch["sell"].iloc[5]                                  # 80'e ilk temas
    # i=6'da RSI 75, HÂLÂ bölge içinde → çıkış i=7'de (60) gerçekleşir
    assert not ex["sell"].iloc[6]
    assert ex["sell"].iloc[7]


def test_exit_signals_bolgede_kalirken_tetiklemez():
    r = pd.Series([50, 25, 24, 23, 22], index=_idx(5), dtype=float)
    assert not sl.signals(r, 70, 30, signal_mode="exit")["buy"].any()


def test_exit_signals_alternans_bozulmaz():
    """Pozisyondayken ikinci AL, nakitteyken SAT üretilmemeli (hayalet işaret yok)."""
    rng = np.random.default_rng(5)
    r = pd.Series(rng.uniform(5, 95, 2000), index=_idx(2000))
    sg = sl.signals(r, 70, 30, signal_mode="exit")
    seq = sorted([(t, "AL") for t in sg.index[sg["buy"]]] +
                 [(t, "SAT") for t in sg.index[sg["sell"]]])
    assert not any(seq[i][1] == seq[i - 1][1] for i in range(1, len(seq)))


def test_signal_mode_gecersizse_hata():
    with pytest.raises(ValueError):
        sl.run_api({"period": "1y", "signal_mode": "saçma"})

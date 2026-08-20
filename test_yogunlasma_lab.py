import numpy as np
import pandas as pd
import pytest

import yogunlasma_lab as yl


def _sentetik_market():
    """3 sembol: A ve B birebir aynı yönde, C ters. 100 iş günü."""
    idx = pd.bdate_range("2026-01-01", periods=100)
    # gerçekten dalgalanan günlük getiri (sabit seri korelasyonu dejenere eder)
    base = pd.Series(np.sin(np.arange(100) / 3.0) * 0.01, index=idx)
    up = (1 + base).cumprod() * 100
    down = (1 - base).cumprod() * 100
    mk = {"data": {}}
    for sym, ser in (("A", up), ("B", up * 1.5), ("C", down)):
        mk["data"][sym] = pd.DataFrame({"Close": ser}, index=idx)
    return mk, idx


def test_mean_corr_np_ozdes_seriler():
    a = np.array([1.0, -2.0, 3.0, -4.0, 5.0])
    book = np.vstack([a, a])
    assert yl.mean_corr_np(a, book) == pytest.approx(1.0)


def test_mean_corr_np_ters_seri():
    a = np.array([1.0, -2.0, 3.0, -4.0, 5.0])
    assert yl.mean_corr_np(a, np.vstack([-a])) == pytest.approx(-1.0)


def test_mean_corr_np_karisik_ortalama():
    a = np.array([1.0, -2.0, 3.0, -4.0, 5.0])
    # biri +1 biri −1 → ortalama 0
    assert yl.mean_corr_np(a, np.vstack([a, -a])) == pytest.approx(0.0)


def test_mean_corr_np_bos_kitap_none():
    a = np.array([1.0, -2.0, 3.0])
    assert yl.mean_corr_np(a, np.empty((0, 3))) is None


def test_mean_corr_np_sabit_seri_none():
    a = np.array([2.0, 2.0, 2.0, 2.0])           # varyans yok
    assert yl.mean_corr_np(a, np.vstack([np.array([1.0, 2.0, 3.0, 4.0])])) is None


def test_accept_corr_bilinmezlik_ceza_degil():
    assert yl.accept_corr(None, 0.5) is True


def test_accept_corr_esik():
    assert yl.accept_corr(0.49, 0.5) is True
    assert yl.accept_corr(0.50, 0.5) is True      # sınır dahil (<= eşik geçer)
    assert yl.accept_corr(0.51, 0.5) is False


def test_accept_label_tavan():
    book = ["Semiconductors", "Semiconductors", "Banks"]
    assert yl.accept_label(book, "Semiconductors", 3) is True    # 2 var, 3'ten küçük
    assert yl.accept_label(book, "Banks", 1) is False            # 1 var, tavan 1
    assert yl.accept_label(book, None, 1) is True                # etiketi bilinmeyen takılmaz
    assert yl.accept_label(book, "Semiconductors", 0) is True    # 0 = kapalı


def test_size_multiplier():
    assert yl.size_multiplier(0.8, 0.6) == 0.5
    assert yl.size_multiplier(0.5, 0.6) == 1.0
    assert yl.size_multiplier(None, 0.6) == 1.0


def test_corr_engine_ayni_yon_yuksek():
    mk, idx = _sentetik_market()
    ce = yl.CorrEngine(mk, window=60, min_obs=40)
    mc = ce.mean_to(idx[-1], "A", ["B"])
    assert mc is not None and mc > 0.99


def test_corr_engine_ters_yon_negatif():
    mk, idx = _sentetik_market()
    ce = yl.CorrEngine(mk, window=60, min_obs=40)
    mc = ce.mean_to(idx[-1], "A", ["C"])
    assert mc is not None and mc < -0.99


def test_corr_engine_bos_kitap_none():
    mk, idx = _sentetik_market()
    ce = yl.CorrEngine(mk, window=60, min_obs=40)
    assert ce.mean_to(idx[-1], "A", []) is None


def test_corr_engine_yetersiz_gecmis_none():
    mk, idx = _sentetik_market()
    ce = yl.CorrEngine(mk, window=60, min_obs=40)
    assert ce.mean_to(idx[5], "A", ["B"]) is None      # 40 gözlem yok


def test_corr_engine_bilinmeyen_sembol_none():
    mk, idx = _sentetik_market()
    ce = yl.CorrEngine(mk, window=60, min_obs=40)
    assert ce.mean_to(idx[-1], "YOK", ["A"]) is None

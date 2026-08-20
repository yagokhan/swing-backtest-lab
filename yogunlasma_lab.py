#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yogunlasma_lab.py — TEMA/KORELASYON YOĞUNLAŞMA DENEYİ (2026-08-20).

Ölçüm (2026-08-20): canlı kaybın ~%103'ü her ismin en kötü 3 gününden geliyor ve o
günler İSİMLER ARASINDA ORTAK (2026-07-01/02'de 6-7 isim %5-14 düşerken SPY düz).
Yani kayıp kanalı idiyosinkratik haber değil, EŞ-HAREKETLİ YIĞILMA.

Bu lab üç varyant ailesini kanon standardında sınar (canlı kural DEĞİŞMEZ):
  K — korelasyon kapısı: aday, açık kitapla ort. 60g getiri korelasyonu > ρ ise alınmaz
  E — etiket tavanı: FMP endüstri etiketi başına en fazla K pozisyon
  B — yumuşak boyut: reddetme yerine korelasyonlu adaya yarım poz (%7.5 → %3.75)

Etiket değil korelasyon merkezli, çünkü birlikte çöken isimlerin etiketleri AYRI:
LRCX (yarı-iletken ekipman) · WDC/STX (donanım) · GLW (bileşen) · ENPH (güneş).

Kullanım: python3 yogunlasma_lab.py [--selftest|--etiket-cek|--grid|--jitter|--rapor|--all]
"""
import numpy as np
import pandas as pd

CORR_WINDOW = 60      # RS penceresiyle hizalı
CORR_MIN_OBS = 40     # en az ortak gözlem


def mean_corr_np(cand, book):
    """Adayın kitaptaki pozisyonlarla ORTALAMA Pearson korelasyonu.

    cand: 1B getiri dizisi · book: 2B dizi (n_poz × aynı uzunluk).
    Hesaplanamıyorsa (boş kitap / varyans yok) None — bilinmezlik ceza değildir."""
    book = np.asarray(book, dtype=float)
    cand = np.asarray(cand, dtype=float)
    if book.size == 0 or cand.size < 2:
        return None
    c = cand - cand.mean()
    cs = float(np.sqrt((c * c).sum()))
    if cs == 0:
        return None
    b = book - book.mean(axis=1, keepdims=True)
    bs = np.sqrt((b * b).sum(axis=1))
    ok = bs > 0
    if not ok.any():
        return None
    corr = (b[ok] @ c) / (bs[ok] * cs)
    return float(corr.mean())


def accept_corr(mc, rho):
    """Korelasyon kapısı. mc None (hesaplanamadı) → kabul; eşik dahil geçer."""
    return True if mc is None else bool(mc <= rho)


def accept_label(book_labels, cand_label, kmax):
    """Etiket tavanı. kmax<=0 kapalı; etiketi bilinmeyen aday tavana takılmaz."""
    if kmax <= 0 or cand_label is None:
        return True
    return sum(1 for x in book_labels if x == cand_label) < kmax


def size_multiplier(mc, rho):
    """Yumuşak boyut: eşiği aşan aday yarım pozisyonla girer."""
    return 0.5 if (mc is not None and mc > rho) else 1.0


class CorrEngine:
    """Günlük getiri matrisinden aday↔kitap korelasyonu. Market başına BİR kez kurulur
    (373 sembollük matris pahalıdır); tarih başına pencere önbelleklenir."""

    def __init__(self, market, window=CORR_WINDOW, min_obs=CORR_MIN_OBS):
        self.R = pd.DataFrame({sym: df["Close"].pct_change()
                               for sym, df in market["data"].items()})
        self.window = window
        self.min_obs = min_obs
        self._cache_date = None
        self._W = None

    def _win(self, date):
        if date != self._cache_date:
            self._W = self.R.loc[:date].tail(self.window)
            self._cache_date = date
        return self._W

    def mean_to(self, date, cand, book):
        """Adayın kitapla ortalama korelasyonu; hesaplanamıyorsa None."""
        if not book:
            return None
        W = self._win(date)
        if len(W) < self.min_obs or cand not in W.columns:
            return None
        cols = [b for b in book if b in W.columns and b != cand]
        if not cols:
            return None
        sub = W[[cand] + cols].dropna()
        if len(sub) < self.min_obs:
            return None
        arr = sub.to_numpy(dtype=float)
        return mean_corr_np(arr[:, 0], arr[:, 1:].T)


_CORR_CACHE = {}


def get_corr_engine(market):
    """Süreç ömrü boyunca market başına tek CorrEngine (matris yeniden kurulmasın)."""
    key = id(market)
    if key not in _CORR_CACHE:
        _CORR_CACHE[key] = CorrEngine(market)
    return _CORR_CACHE[key]

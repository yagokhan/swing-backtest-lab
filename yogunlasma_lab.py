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
import copy
import json
import os
import sys

sys.path.insert(0, "/home/gokhan")
os.chdir("/home/gokhan")

import numpy as np
import pandas as pd

import altguard_lab as ag
import swing2_backtest as s

CORR_WINDOW = 60      # RS penceresiyle hizalı
CORR_MIN_OBS = 40     # en az ortak gözlem

OUT_DIR = "/home/gokhan/swing2_out/yogunlasma"
OUT_JSON = os.path.join(OUT_DIR, "results.json")
LABELS_JSON = "/home/gokhan/swing2_cache/industry_labels.json"
JITTER_STARTS = ["2021-05-01", "2021-05-08", "2021-05-15", "2021-05-22", "2021-06-01"]


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


def load_labels(path=LABELS_JSON):
    """Etiket cache'i; yoksa boş sözlük (etiketsizlik ceza değildir)."""
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return json.load(fh)


def fetch_labels(symbols=None, path=LABELS_JSON):
    """FMP stable/profile → sembol başına industry etiketi; tek seferlik, cache'lenir."""
    import concurrent.futures as cf
    import urllib.request
    key = s._fmp_key()
    symbols = symbols or list(ag.base_cfg().universe)
    out = load_labels(path)
    todo = [x for x in symbols if x not in out]
    print(f"etiket çekiliyor: {len(todo)} sembol (cache'te {len(out)})")

    def one(sym):
        url = f"https://financialmodelingprep.com/stable/profile?symbol={sym}&apikey={key}"
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                d = json.loads(r.read())
            it = d[0] if isinstance(d, list) and d else d
            return sym, (it.get("industry") or None)
        except Exception:
            return sym, None

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for sym, lbl in ex.map(one, todo):
            out[sym] = lbl
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    bilinen = sum(1 for v in out.values() if v)
    print(f"etiket cache: {len(out)} sembol · {bilinen} etiketli")
    return out


class YogunlasmaBacktester(ag.GKX):
    """Aday 3 + yoğunlaşma kapısı. Kapılar kapalıyken GKX ile BİREBİR aynı olmalıdır.

    Tek kanca `_open()`: ag.GKX._step onu iki yerden çağırır (normal giriş + giyotin yolu)
    ve False dönerse döngü SIRADAKİ adaya geçer → reddedilen sermaye boşta kalmaz."""

    RHO = None        # korelasyon eşiği (None = kapalı)
    KMAX = 0          # etiket tavanı (0 = kapalı)
    SOFT = False      # True: reddetme yerine yarım poz
    LABELS = {}       # sembol → endüstri etiketi

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.corr = get_corr_engine(kw.get("market") or a[1])
        self.gate_log = []     # (tarih, sembol, mc, karar)

    def _open(self, sym, date, row, plan, score):
        book = [x for x in self.positions if x != sym]
        mc = self.corr.mean_to(date, sym, book)      # baz koşuda da ölçülür (kıyas metriği)
        if self.RHO is not None and not self.SOFT and not accept_corr(mc, self.RHO):
            self.gate_log.append((str(date)[:10], sym, mc, "red-corr"))
            return False
        if self.KMAX and not accept_label([self.LABELS.get(b) for b in book],
                                          self.LABELS.get(sym), self.KMAX):
            self.gate_log.append((str(date)[:10], sym, mc, "red-etiket"))
            return False
        mult = size_multiplier(mc, self.RHO) if (self.RHO is not None and self.SOFT) else 1.0
        self.gate_log.append((str(date)[:10], sym, mc, "kabul" if mult == 1.0 else "yarim"))
        if mult != 1.0:
            old = self.cfg.max_position_pct
            self.cfg.max_position_pct = old * mult
            try:
                return super()._open(sym, date, row, plan, score)
            finally:
                self.cfg.max_position_pct = old
        return super()._open(sym, date, row, plan, score)


def _ort_kitap_korelasyonu(bt):
    """Kapı etkinlik metriği: kabul edilen girişlerdeki ortalama kitap korelasyonu."""
    vals = [mc for _, _, mc, k in bt.gate_log if mc is not None and k in ("kabul", "yarim")]
    return round(float(np.mean(vals)), 3) if vals else None


def run_windows(rho=None, kmax=0, soft=False, label=""):
    """5 pencerede tek varyant koşusu. altguard_lab.WINS + sabit cache kullanılır."""
    ag.load_data()                       # attach_watchlist içeride — ZORUNLU
    labels = load_labels() if kmax else {}
    rows = []
    for wn, sd, ed in ag.WINS:
        c = copy.deepcopy(ag.base_cfg())
        c.start_date = sd
        c.end_date = ed
        YogunlasmaBacktester.RHO = rho
        YogunlasmaBacktester.KMAX = kmax
        YogunlasmaBacktester.SOFT = soft
        YogunlasmaBacktester.LABELS = labels
        bt = YogunlasmaBacktester(c, market=ag.MARKET)
        bt.run()
        m = bt.metrics()
        red = sum(1 for *_, k in bt.gate_log if k.startswith("red"))
        yarim = sum(1 for *_, k in bt.gate_log if k == "yarim")
        rows.append({"win": wn, "roi": round(m["roi"], 1), "max_dd": round(m["max_dd"], 1),
                     "pf": round(m["profit_factor"], 2), "trades": m["trades"],
                     "calmar": round(m["roi"] / abs(m["max_dd"]), 2) if m["max_dd"] else None,
                     "ort_corr": _ort_kitap_korelasyonu(bt), "red": red, "yarim": yarim})
        print("  %-10s %-12s roi %+7.1f · dd %6.1f · calmar %5.2f · n %4d · corr %s · red %d" %
              (label, wn, rows[-1]["roi"], rows[-1]["max_dd"], rows[-1]["calmar"] or 0,
               rows[-1]["trades"], rows[-1]["ort_corr"], red), flush=True)
    return rows


def selftest():
    """SADAKAT KAPISI (fail-closed): kapılar kapalıyken sonuç EXPECTED ile birebir."""
    print("SADAKAT: kapılar kapalı → altguard EXPECTED çapaları")
    rows = run_windows(label="baz")
    ok = ag.fidelity(rows)
    if not ok:
        raise SystemExit("SADAKAT KAPISI DÜŞTÜ — deney durdu, önce fark teşhis edilmeli.")
    print("SADAKAT OK")
    return True

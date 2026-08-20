# Yoğunlaşma Deneyi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Qulla-21'in tema yığılmasının ödediğimiz bir prim mi yoksa kârın kaynağı mı olduğunu, korelasyon/etiket tavanı varyantlarını kanon standardında (5 pencere + jitter + komşu) test ederek ölçmek.

**Architecture:** `yogunlasma_lab.py` tek dosya; motor entegrasyonu `ag.GKX`'i (altguard_lab'ın doğrulanmış Aday 3 kopyası, sabit cache) genişleten `YogunlasmaBacktester` ile yapılır ve **yalnız `_open()` kancasına** dokunur — aday reddedilirse döngü sıradaki adaya geçer (sermaye boşta kalmaz). Korelasyon, depodaki fiyatlardan türetilen tek bir getiri matrisinden hesaplanır; etiketler FMP profilinden bir kez çekilip cache'lenir.

**Tech Stack:** Python 3, pandas, numpy, pytest; mevcut `swing2_backtest` + `altguard_lab` altyapısı; FMP `stable/profile` (yalnız etiket varyantı için, tek seferlik).

**Spec:** `docs/superpowers/specs/2026-08-20-yogunlasma-deneyi-design.md`

## Global Constraints

- **SALT-OKUR:** `~/.swing_paper_qulla_ledger.json`, `~/.swing_paper_qulla.json`, `~/.swing_daily_store.pkl` dosyalarına ve `qulla_paper.load_market_incremental`'a **yazılmaz**; canlı cron/konfig değiştirilmez.
- **Sabit cache zorunlu:** tüm koşular `altguard_lab.CACHE` (`swing2_cache/market_5y_152dab0ec647.pkl`) üzerinden; `ag.load_data()` çağrılır (içinde `attach_watchlist` yapılır — bu adım atlanırsa RS top-50 kapısı kapanır ve sonuç tamamen yanlış olur).
- **Sadakat kapısı (fail-closed):** kapılar kapalıyken sonuç `altguard_lab.EXPECTED` = `[(166.3, 482), (21.3, 187), (43.3, 273), (81.3, 302), (57.4, 215)]` ile **birebir** (ROI farkı <0,05 ve işlem sayısı eşit) olmalı. Tutmazsa deney durur, yayınlanmaz.
- **Pencereler:** `altguard_lab.WINS` = 5y tam (2021-05-01→) · ayı 21-23 · topar 23-25 · son 2y · son 1y.
- **Jitter başlangıçları:** `["2021-05-01", "2021-05-08", "2021-05-15", "2021-05-22", "2021-06-01"]`.
- **Korelasyon varsayılanları:** pencere 60 işlem günü, en az 40 ortak gözlem; bilinmezlik ceza değildir (hesaplanamıyorsa aday kabul edilir).
- **Kabul kriteri (ön-kayıtlı):** 5 pencerenin ≥4'ünde bazdan iyi · ayı döneminde bozulmamış · jitter dayanıklı · komşu parametrelerde çalışıyor · risk-ayarlı (Calmar/MaxDD) iyileşme. Yalnız ROI artışı yeterli değildir. **ADAY YOK geçerli sonuçtur.**
- Dosya konumu: `*_lab.py` geleneği gereği ev dizini (`/home/gokhan/`), çıktı `~/swing2_out/yogunlasma/`.

## File Structure

| Dosya | Sorumluluk |
|---|---|
| `/home/gokhan/yogunlasma_lab.py` | Kapı matematiği (saf fonksiyonlar), `CorrEngine`, `YogunlasmaBacktester`, grid/jitter koşucuları, rapor |
| `/home/gokhan/test_yogunlasma_lab.py` | Saf fonksiyon + `CorrEngine` testleri (motor koşusundan bağımsız, sentetik veri) |
| `/home/gokhan/swing2_cache/industry_labels.json` | FMP sector/industry etiket cache'i (tek seferlik çekim) |
| `~/swing2_out/yogunlasma/results.json` | Grid + jitter ham sonuçları (yeniden koşmadan rapor derlemek için) |
| `/home/gokhan/dashboard_static/adaylar.html` | Sonuç bölümü (Task 7'de düzenlenir) |

---

### Task 1: Kapı matematiği (saf fonksiyonlar)

**Files:**
- Create: `/home/gokhan/yogunlasma_lab.py`
- Test: `/home/gokhan/test_yogunlasma_lab.py`

**Interfaces:**
- Consumes: yok (ilk task)
- Produces: `mean_corr_np(cand: np.ndarray, book: np.ndarray) -> float | None` · `accept_corr(mc: float | None, rho: float) -> bool` · `accept_label(book_labels: list, cand_label, kmax: int) -> bool` · `size_multiplier(mc: float | None, rho: float) -> float`

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pytest
import yogunlasma_lab as yl


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/gokhan && python3 -m pytest test_yogunlasma_lab.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yogunlasma_lab'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/gokhan && python3 -m pytest test_yogunlasma_lab.py -v`
Expected: PASS (10 test)

- [ ] **Step 5: Commit**

```bash
cd /home/gokhan/swing-backtest-lab
cp /home/gokhan/yogunlasma_lab.py /home/gokhan/test_yogunlasma_lab.py .
git add yogunlasma_lab.py test_yogunlasma_lab.py
git commit -m "feat(yogunlasma): kapı matematiği — korelasyon/etiket/boyut saf fonksiyonları"
```

---

### Task 2: Korelasyon motoru (`CorrEngine`)

**Files:**
- Modify: `/home/gokhan/yogunlasma_lab.py` (Task 1'in sonuna ekle)
- Test: `/home/gokhan/test_yogunlasma_lab.py` (ekle)

**Interfaces:**
- Consumes: `mean_corr_np` (Task 1)
- Produces: `CorrEngine(market: dict, window: int = 60, min_obs: int = 40)` · `CorrEngine.mean_to(date, cand: str, book: list[str]) -> float | None` · `get_corr_engine(market) -> CorrEngine` (süreç-ömrü tekil, market başına bir kez kurulur)

- [ ] **Step 1: Write the failing tests**

```python
import pandas as pd


def _sentetik_market():
    """3 sembol: A ve B birebir aynı yönde, C ters. 100 iş günü."""
    idx = pd.bdate_range("2026-01-01", periods=100)
    base = pd.Series(np.linspace(0, 1, 100), index=idx).diff().fillna(0.01)
    up = (1 + base).cumprod() * 100
    down = (1 - base).cumprod() * 100
    mk = {"data": {}}
    for sym, ser in (("A", up), ("B", up * 1.5), ("C", down)):
        mk["data"][sym] = pd.DataFrame({"Close": ser}, index=idx)
    return mk, idx


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/gokhan && python3 -m pytest test_yogunlasma_lab.py -k corr_engine -v`
Expected: FAIL — `AttributeError: module 'yogunlasma_lab' has no attribute 'CorrEngine'`

- [ ] **Step 3: Write minimal implementation**

```python
import pandas as pd

CORR_WINDOW = 60      # RS penceresiyle hizalı
CORR_MIN_OBS = 40     # en az ortak gözlem


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/gokhan && python3 -m pytest test_yogunlasma_lab.py -v`
Expected: PASS (15 test)

- [ ] **Step 5: Commit**

```bash
cd /home/gokhan/swing-backtest-lab
cp /home/gokhan/yogunlasma_lab.py /home/gokhan/test_yogunlasma_lab.py .
git add yogunlasma_lab.py test_yogunlasma_lab.py
git commit -m "feat(yogunlasma): CorrEngine — getiri matrisi + tarih önbellekli kitap korelasyonu"
```

---

### Task 3: Motor entegrasyonu + sadakat kapısı

**Files:**
- Modify: `/home/gokhan/yogunlasma_lab.py`

**Interfaces:**
- Consumes: `accept_corr`, `accept_label`, `size_multiplier`, `get_corr_engine` (Task 1-2)
- Produces: `YogunlasmaBacktester(ag.GKX)` sınıf değişkenleri `RHO: float | None`, `KMAX: int`, `SOFT: bool`, `LABELS: dict` · `run_windows(rho=None, kmax=0, soft=False, label="") -> list[dict]` · `selftest() -> bool`

**Neden `ag.GKX`:** altguard_lab'ın Aday 3 kopyası sabit cache üzerinde çalışır ve `EXPECTED` çapalarıyla **kesin** (ROI <0,05, işlem sayısı birebir) sadakat kapısı sağlar; `qulla_paper.DengeBacktester` canlı depoyu kullandığından veri revizyonları yüzünden bu kesinlik mümkün değildir. Diğer laboratuvarlar (tahsis_lab, karkilit_lab) da bu yolu kullanır.

- [ ] **Step 1: Write the implementation**

`_open()` tek kancadır: `ag.GKX._step` içinde iki yerden çağrılır (normal giriş + giyotin yolu) ve **False dönerse döngü sıradaki adaya geçer** — bu yüzden reddedilen sermaye boşta kalmaz.

```python
import copy
import json
import os
import sys

sys.path.insert(0, "/home/gokhan")
os.chdir("/home/gokhan")

import altguard_lab as ag
import swing2_backtest as s

OUT_DIR = "/home/gokhan/swing2_out/yogunlasma"
OUT_JSON = os.path.join(OUT_DIR, "results.json")
LABELS_JSON = "/home/gokhan/swing2_cache/industry_labels.json"
JITTER_STARTS = ["2021-05-01", "2021-05-08", "2021-05-15", "2021-05-22", "2021-06-01"]


class YogunlasmaBacktester(ag.GKX):
    """Aday 3 + yoğunlaşma kapısı. Kapılar kapalıyken GKX ile BİREBİR aynı olmalıdır."""

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
```

- [ ] **Step 2: Run the fidelity gate**

Run: `cd /home/gokhan && python3 yogunlasma_lab.py --selftest`
Expected: 5 satırda `OK`, sonda `SADAKAT OK`. Herhangi bir `FARK!` → dur, teşhis et, ilerleme.

- [ ] **Step 3: Verify the gate actually bites**

Run: `cd /home/gokhan && python3 -c "
import yogunlasma_lab as yl
rows = yl.run_windows(rho=0.5, label='K0.50')
assert sum(r['red'] for r in rows) > 0, 'kapı hiç reddetmedi — no-op'
print('kapı çalışıyor, toplam red:', sum(r['red'] for r in rows))
"`
Expected: red > 0 ve `ort_corr` değerleri bazdan düşük.

- [ ] **Step 4: Commit**

```bash
cd /home/gokhan/swing-backtest-lab
cp /home/gokhan/yogunlasma_lab.py .
git add yogunlasma_lab.py
git commit -m "feat(yogunlasma): YogunlasmaBacktester + sadakat kapısı (EXPECTED birebir)"
```

---

### Task 4: Endüstri etiketleri (E varyantı için)

**Files:**
- Modify: `/home/gokhan/yogunlasma_lab.py`
- Create: `/home/gokhan/swing2_cache/industry_labels.json`
- Test: `/home/gokhan/test_yogunlasma_lab.py` (ekle)

**Interfaces:**
- Consumes: yok
- Produces: `load_labels(path=LABELS_JSON) -> dict[str, str | None]` · `fetch_labels(symbols: list[str], path=LABELS_JSON) -> dict`

- [ ] **Step 1: Write the failing test**

```python
def test_load_labels_dosya_yoksa_bos(tmp_path):
    p = tmp_path / "yok.json"
    assert yl.load_labels(str(p)) == {}


def test_load_labels_okur(tmp_path):
    p = tmp_path / "lbl.json"
    p.write_text('{"LRCX": "Semiconductors", "XYZ": null}')
    d = yl.load_labels(str(p))
    assert d["LRCX"] == "Semiconductors"
    assert d["XYZ"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/gokhan && python3 -m pytest test_yogunlasma_lab.py -k labels -v`
Expected: FAIL — `AttributeError: module 'yogunlasma_lab' has no attribute 'load_labels'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run tests + fetch real labels**

Run: `cd /home/gokhan && python3 -m pytest test_yogunlasma_lab.py -v && python3 yogunlasma_lab.py --etiket-cek`
Expected: testler PASS; çekim sonunda "etiket cache: 373 sembol · N etiketli" (N ≥ 300 beklenir; belirgin düşükse FMP kapsamını logla).

- [ ] **Step 5: Commit**

```bash
cd /home/gokhan/swing-backtest-lab
cp /home/gokhan/yogunlasma_lab.py /home/gokhan/test_yogunlasma_lab.py .
git add yogunlasma_lab.py test_yogunlasma_lab.py
git commit -m "feat(yogunlasma): FMP endüstri etiketi çekimi + cache"
```

---

### Task 5: Grid koşusu (11 konfig × 5 pencere)

**Files:**
- Modify: `/home/gokhan/yogunlasma_lab.py`

**Interfaces:**
- Consumes: `run_windows` (Task 3), `load_labels` (Task 4)
- Produces: `GRID: list[tuple[str, dict]]` · `grid() -> dict` (sonuç `OUT_JSON`'a yazılır) · `save_json(obj)` / `load_json()`

- [ ] **Step 1: Write the implementation**

```python
GRID = [
    ("baz",   {}),
    ("K0.50", {"rho": 0.50}), ("K0.60", {"rho": 0.60}),
    ("K0.70", {"rho": 0.70}), ("K0.80", {"rho": 0.80}),
    ("E3", {"kmax": 3}), ("E4", {"kmax": 4}),
    ("E5", {"kmax": 5}), ("E6", {"kmax": 6}),
    ("B0.60", {"rho": 0.60, "soft": True}), ("B0.70", {"rho": 0.70, "soft": True}),
]


def save_json(obj):
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = OUT_JSON + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, OUT_JSON)
    print("yazıldı:", OUT_JSON)


def load_json():
    with open(OUT_JSON) as fh:
        return json.load(fh)


def grid():
    """Tüm varyantlar × 5 pencere. Ara sonuç her varyanttan sonra kaydedilir."""
    out = load_json() if os.path.exists(OUT_JSON) else {}
    out.setdefault("grid", {})
    for key, kw in GRID:
        if key in out["grid"]:
            print(f"[atlandı, zaten var] {key}")
            continue
        out["grid"][key] = run_windows(label=key, **kw)
        save_json(out)
    _grid_ozet(out)
    return out


def _grid_ozet(out):
    """Kapı etkinliği + kabul kriteri sayacı. no-op varyantlar işaretlenir."""
    baz = out["grid"]["baz"]
    print(f"\n{'varyant':8s}{'ROI ort':>9s}{'Calmar ort':>12s}{'MaxDD ort':>11s}"
          f"{'corr':>7s}{'bazdan iyi':>12s}{'durum':>10s}")
    for key, rows in out["grid"].items():
        roi = np.mean([r["roi"] for r in rows])
        cal = np.mean([r["calmar"] or 0 for r in rows])
        dd = np.mean([r["max_dd"] for r in rows])
        corrs = [r["ort_corr"] for r in rows if r["ort_corr"] is not None]
        corr = np.mean(corrs) if corrs else float("nan")
        iyi = sum(1 for r, b in zip(rows, baz) if (r["calmar"] or 0) > (b["calmar"] or 0))
        bazcorr = np.mean([b["ort_corr"] for b in baz if b["ort_corr"] is not None])
        noop = key != "baz" and sum(r["red"] + r["yarim"] for r in rows) == 0
        durum = "NO-OP" if noop else ("finalist" if iyi >= 4 else "elendi")
        if key == "baz":
            durum = "baz"
        print(f"{key:8s}{roi:+9.1f}{cal:12.2f}{dd:11.1f}{corr:7.3f}{iyi:9d}/5{durum:>10s}")
    print(f"\n(baz ort. kitap korelasyonu: {bazcorr:.3f} — varyantların bundan düşük olması "
          f"kapının gerçekten yoğunlaşmayı azalttığının teyididir)")
```

- [ ] **Step 2: Run the grid**

Run: `cd /home/gokhan && python3 yogunlasma_lab.py --grid 2>&1 | tail -40`
Expected: 11 varyant × 5 pencere tamamlanır; özet tablo yazılır; `NO-OP` işaretli varyant varsa sonucu sayılmaz (kapı fiilen çalışmamış).

- [ ] **Step 3: Commit**

```bash
cd /home/gokhan/swing-backtest-lab
cp /home/gokhan/yogunlasma_lab.py .
git add yogunlasma_lab.py
git commit -m "feat(yogunlasma): 11-konfig grid + kapı etkinlik özeti"
```

---

### Task 6: Jitter + komşu kontrolü (yalnız finalistlere)

**Files:**
- Modify: `/home/gokhan/yogunlasma_lab.py`

**Interfaces:**
- Consumes: `run_windows` (Task 3), `load_json`/`save_json` (Task 5)
- Produces: `jitter(finalists: list[str] | None = None) -> dict` · `_variant_kw(key: str) -> dict`

- [ ] **Step 1: Write the implementation**

Jitter, tek-tepe/şans sonuçlarını ayıklayan kanon kapısıdır: başlangıç günü kaydırılınca üstünlük ayakta kalmalı. Komşu kontrolü aynı ailenin bitişik parametresine bakar (K0.60 finalistse K0.55/K0.65 de iyileşmeli — zikzak = overfit).

```python
def _variant_kw(key):
    for k, kw in GRID:
        if k == key:
            return kw
    if key.startswith("K"):
        return {"rho": float(key[1:])}
    if key.startswith("B"):
        return {"rho": float(key[1:]), "soft": True}
    if key.startswith("E"):
        return {"kmax": int(key[1:])}
    raise ValueError(f"bilinmeyen varyant: {key}")


def jitter(finalists=None):
    """5 farklı başlangıçtan tek pencere (5y tam) koşusu — dayanıklılık testi."""
    out = load_json()
    baz = out["grid"]["baz"]
    if finalists is None:
        finalists = [k for k, rows in out["grid"].items()
                     if k != "baz"
                     and sum(1 for r, b in zip(rows, baz) if (r["calmar"] or 0) > (b["calmar"] or 0)) >= 4
                     and sum(r["red"] + r["yarim"] for r in rows) > 0]
    print("jitter adayları:", finalists or "YOK (grid'den finalist çıkmadı)")
    out.setdefault("jitter", {})
    ag.load_data()
    for key in ["baz"] + list(finalists):
        if key in out["jitter"]:
            continue
        kw = {} if key == "baz" else _variant_kw(key)
        res = []
        for sd in JITTER_STARTS:
            c = copy.deepcopy(ag.base_cfg())
            c.start_date = sd
            c.end_date = ""
            YogunlasmaBacktester.RHO = kw.get("rho")
            YogunlasmaBacktester.KMAX = kw.get("kmax", 0)
            YogunlasmaBacktester.SOFT = kw.get("soft", False)
            YogunlasmaBacktester.LABELS = load_labels() if kw.get("kmax") else {}
            bt = YogunlasmaBacktester(c, market=ag.MARKET)
            bt.run()
            m = bt.metrics()
            res.append({"start": sd, "roi": round(m["roi"], 1), "max_dd": round(m["max_dd"], 1),
                        "calmar": round(m["roi"] / abs(m["max_dd"]), 2) if m["max_dd"] else None})
            print(f"  {key:8s} {sd} roi {res[-1]['roi']:+7.1f} · calmar {res[-1]['calmar']}",
                  flush=True)
        out["jitter"][key] = res
        save_json(out)
    for key, res in out["jitter"].items():
        if key == "baz":
            continue
        kazanan = sum(1 for r, b in zip(res, out["jitter"]["baz"])
                      if (r["calmar"] or 0) > (b["calmar"] or 0))
        print(f"{key}: jitter {kazanan}/5 başlangıçta bazdan iyi "
              f"→ {'GEÇTİ' if kazanan >= 4 else 'ÇÖKTÜ'}")
    return out
```

- [ ] **Step 2: Run jitter**

Run: `cd /home/gokhan && python3 yogunlasma_lab.py --jitter 2>&1 | tail -30`
Expected: finalist yoksa "YOK (grid'den finalist çıkmadı)" yazıp temiz çıkar — bu **geçerli sonuçtur**. Finalist varsa 5 başlangıç sonucu + GEÇTİ/ÇÖKTÜ satırı.

- [ ] **Step 3: Neighbor check on any jitter survivor**

Jitter'ı geçen her varyant için komşu parametrelerini koştur (K0.60 → K0.55 ve K0.65; E4 → E3/E5 zaten grid'de var; B0.60 → B0.55/B0.65):

Run: `cd /home/gokhan && python3 -c "
import yogunlasma_lab as yl
# <ayakta kalan varyant> için komşular; zikzak varsa overfit → RET
for k in ['K0.55', 'K0.65']:
    print(k, yl.run_windows(label=k, **yl._variant_kw(k)))
"`
Expected: komşular da bazdan iyi → gerçek plato; zikzak (biri çok iyi, komşuları kötü) → overfit, aday RET.

- [ ] **Step 4: Commit**

```bash
cd /home/gokhan/swing-backtest-lab
cp /home/gokhan/yogunlasma_lab.py .
git add yogunlasma_lab.py
git commit -m "feat(yogunlasma): jitter dayanıklılık + komşu parametre kontrolü"
```

---

### Task 7: Rapor, yayın, bellek

**Files:**
- Modify: `/home/gokhan/yogunlasma_lab.py` (rapor + `main()`)
- Modify: `/home/gokhan/dashboard_static/adaylar.html`
- Create: `/home/gokhan/.claude/projects/-home-gokhan/memory/swing2-yogunlasma-deneyi.md`
- Modify: `/home/gokhan/.claude/projects/-home-gokhan/memory/MEMORY.md`

**Interfaces:**
- Consumes: `load_json` (Task 5), jitter sonuçları (Task 6)
- Produces: `rapor() -> None` · `main()` CLI (`--selftest|--etiket-cek|--grid|--jitter|--rapor|--all`)

- [ ] **Step 1: Write report + CLI**

```python
def rapor():
    """Karar özeti: grid + jitter → KARAR satırı."""
    out = load_json()
    _grid_ozet(out)
    if out.get("jitter"):
        print("\nJITTER:")
        for key, res in out["jitter"].items():
            if key == "baz":
                continue
            kaz = sum(1 for r, b in zip(res, out["jitter"]["baz"])
                      if (r["calmar"] or 0) > (b["calmar"] or 0))
            print(f"  {key}: {kaz}/5 → {'GEÇTİ' if kaz >= 4 else 'ÇÖKTÜ'}")
    ayakta = [k for k, res in out.get("jitter", {}).items()
              if k != "baz" and sum(1 for r, b in zip(res, out["jitter"]["baz"])
                                    if (r["calmar"] or 0) > (b["calmar"] or 0)) >= 4]
    print("\nKARAR:", f"ADAY: {', '.join(ayakta)} (komşu kontrolü sonrası)" if ayakta
          else "ADAY YOK — yoğunlaşma tavanı kabul kriterinden geçmedi.")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    for f in ("selftest", "etiket-cek", "grid", "jitter", "rapor", "all"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    hic = not any(vars(a).values())
    if a.selftest or a.all or hic:
        selftest()
    if getattr(a, "etiket_cek"):
        fetch_labels()
    if a.grid or a.all or hic:
        grid()
    if a.jitter or a.all or hic:
        jitter()
    if a.rapor or a.all or hic:
        rapor()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the full report**

Run: `cd /home/gokhan && python3 yogunlasma_lab.py --rapor`
Expected: grid tablosu + jitter satırları + `KARAR:` satırı.

- [ ] **Step 3: Publish to /adaylar**

`/home/gokhan/dashboard_static/adaylar.html` içine yeni bölüm; sayfanın mevcut üslubunu (sade dil, dürüstlük notu, kaynak satırı) izle. İçerik: ölçümün gerekçesi (07-01/07-02 ortak şok tablosu), test edilen 3 varyant ailesi, sonuç tablosu, KARAR satırı, dürüstlük notu (**aday çıkmasa da yayınlanır**; kanon uyarısı: kuyruğu üreten yoğunlaşma kârı üreten yoğunlaşma olabilir), kaynak: `yogunlasma_lab.py`.

Doğrula: `curl -s localhost:8061/adaylar | grep -c "Yoğunlaşma"` → ≥1 (statik dosya, restart gerekmez).

- [ ] **Step 4: Repo push**

```bash
cd /home/gokhan/swing-backtest-lab
cp /home/gokhan/yogunlasma_lab.py /home/gokhan/test_yogunlasma_lab.py .
cp /home/gokhan/dashboard_static/adaylar.html dashboard_static/
cp /home/gokhan/docs/superpowers/plans/2026-08-20-yogunlasma-deneyi.md docs/superpowers/plans/ 2>/dev/null || mkdir -p docs/superpowers/plans && cp /home/gokhan/docs/superpowers/plans/2026-08-20-yogunlasma-deneyi.md docs/superpowers/plans/
git add -A && git commit -m "exp: yoğunlaşma deneyi sonuçları + /adaylar yayını" && git push origin main
```

- [ ] **Step 5: Memory**

`swing2-yogunlasma-deneyi.md` yaz (type: project): ölçüm gerekçesi (ortak şok günleri), test edilen grid, KARAR, kapı etkinlik metriği, `[[swing2-atif-teshisi]]` · `[[swing2-beklenti-karnesi]]` · `[[swing2-tahsis-deney]]` bağlantıları; `MEMORY.md`'ye tek satır pointer ekle.

---

## Self-Review

**Spec kapsamı:** §1 motor entegrasyonu → Task 3 (spec `DengeBacktester` diyordu; plan `ag.GKX` kullanıyor — gerekçe Task 3'te yazılı, sadakat kapısı bu sayede kesinleşiyor, spec buna göre güncellenecek) · §2 varyantlar → Task 5 GRID (K×4, E×4, B×2 = 10 + baz = 11 ✓) · §3 protokol → Task 5 (5 pencere) + Task 6 (jitter + komşu) · §4.1 baz eşdeğerlik → Task 3 selftest · §4.2 kapı etkinliği → Task 5 `_grid_ozet` NO-OP işareti + `ort_corr` · §4.3 salt-okur → Global Constraints · §4.4 sessiz kısıtlama yok → Task 6 finalist yoksa açıkça yazar · Çıktılar → Task 5 (JSON) + Task 7 (rapor/adaylar/repo/bellek) · Testler → Task 1/2/4.

**Placeholder taraması:** yok — her adımda çalıştırılabilir kod/komut var.

**Tip tutarlılığı:** `mean_corr_np(cand, book) -> float|None` Task 1'de tanımlı, Task 2 `CorrEngine.mean_to` içinde aynı imzayla çağrılıyor ✓ · `accept_corr/accept_label/size_multiplier` Task 1 imzaları Task 3 `_open` içinde birebir ✓ · `run_windows(rho, kmax, soft, label)` Task 3'te tanımlı, Task 5/6'da aynı anahtar kelimelerle ✓ · `load_labels(path)` Task 4, Task 3/6'da kullanımı ✓ · `_variant_kw` Task 6'da tanımlı ve Task 6 Step 3'te kullanılıyor ✓.

"""altguard_lab.py — Stopsuz A bacağına ALTERNATİF korumalar (2026-07-08).

Dünkü 🛡️ deneyi (splitstop_lab.py) klasik stop/timeout/EMA21'in hepsinin bazı
kaybettirdiğini gösterdi. Bu lab üç fiyat-düşüşü-dışı fikri test eder:

  1) GİYOTİN / slot rotasyonu — 20/20 doluyken qscore >= Q "yıldız" sinyal gelirse
     en kötü zararda pozisyon zorla satılır, yeri yıldıza verilir.
  2) RS ÇÖKÜŞÜ — hisse pozisyondayken 21 işlem gününde SPY'nin X puan gerisine
     düşerse satılır (kendi fiyat düşüşü değil, göreli güç çöküşü).
  3) HACİM-TEYİTLİ KIRILIM — 50g ort. hacmin k katı hacimle SMA50 altında
     KAPANIRSA satılır (kurumsal satış); normal hacimli düşüşlere dokunulmaz.

Motor/canlı DEĞİŞMEZ. Spec: docs/superpowers/specs/2026-07-08-splitA-alternatif-korumalar-design.md

SADAKAT ZORUNLU: GIL=None, RSX=None, VOLK=None iken batarya blend (Aday 3) ile
5 pencerede ROI+N birebir olmalı (EXPECTED). Tutmazsa koşu durur.

Kullanım:
  python3 altguard_lab.py --selftest   # market verisiz semantik testleri
  python3 altguard_lab.py --fidelity   # none == batarya 5/5 kanıtı
  python3 altguard_lab.py --wave1      # 12 varyant x 5 pencere -> JSON
  python3 altguard_lab.py --wave2 k=3,4 q=80 rs=20 ...  # iterasyon (serbest liste)
  python3 altguard_lab.py --report     # adaylar.html bölümünü üret/güncelle
"""
import argparse
import copy
import json
import os
import pickle
import re
import sys

sys.path.insert(0, "/home/gokhan")
os.chdir("/home/gokhan")
import pandas as pd
import swing2_backtest as s

CACHE = "swing2_cache/market_5y_152dab0ec647.pkl"
BREADTH_PKL = "swing2_cache/breadth.pkl"
OUT_JSON = "/home/gokhan/swing2_out/altguard_results.json"
ADAYLAR = "/home/gokhan/dashboard_static/adaylar.html"

WINS = [("5y tam", "2021-05-01", ""), ("ayı 21-23", "2021-05-01", "2023-07-01"),
        ("topar 23-25", "2023-07-01", "2025-07-01"),
        ("son 2y", "2024-07-01", ""), ("son 1y", "2025-07-01", "")]

# Aday 3 batarya referansı (blend, sabit cache): (roi, işlem sayısı)
EXPECTED = [(166.3, 482), (21.3, 187), (43.3, 273), (81.3, 302), (57.4, 215)]

BR = None      # breadth pkl (A200: pd.Series)
MARKET = None  # sabit market cache


def base_cfg():
    """Aday 3 canlı konfiği (gen_adaylar_curves.py cfg'sinin birebir kopyası)."""
    cfg = s.Config()
    cfg.period = "5y"; cfg.price_source = "fmp"; cfg.disk_cache = True
    cfg.use_earnings = False; cfg.per_ticker_download = False
    cfg.entry_mode = "qswing_breakout"; cfg.qswing_breakout_lb = 63
    cfg.exit_mode = "split"; cfg.split_a = "target"; cfg.split_a_param = 2.0
    cfg.split_b = "ema21"; cfg.split_b_param = 0.0
    cfg.split_ratio = 0.6
    cfg.use_rs_universe = True; cfg.rs_n = 50
    cfg.rs_pool = s.UNIVERSE_PRESETS["sp500_ndx"]; cfg.universe = cfg.rs_pool
    cfg.max_positions = 20; cfg.compounding = True; cfg.liquidate_at_end = True
    cfg.max_position_pct = 0.075; cfg.free_runner_slots = True
    return cfg


class GKX(s.Swing2Backtester):
    """Aday 3 kopyası (gen_adaylar_curves.KX blend yolu) + 3 alternatif koruma.

    GIL  : None | (mode, Q)     mode='pnl' (en çok ekside %) | 'age' (en çok su-altı günü)
                                Q = yıldız qscore eşiği (0-100). Kurban: zararda + slot
                                işgal eden + >= GIL_MIN_AGE bar taşınmış. TÜM pozisyon
                                kapanıştan satılır (market/stop_slip); yıldız aynı gün girer.
    GIL_VPCT : 0 | X            kurban ZOMBİ filtresi: en az −X% ekside olmalı (0=kapalı)
    GIL_VUW  : 0 | N            kurban ZOMBİ filtresi: en az N gün su altında olmalı (0=kapalı)
    RSX  : None | (X, scope)    tetik: (RET21G_hisse − RET21G_SPY) <= −X (yüzde puan)
    VOLK : None | (k, scope)    tetik: Close < SMA50 VE Volume >= k × önceki-50g-ort-hacim
    scope: 'A' = yalnız A (target) bacağı | 'tum' = kalan TÜM pozisyon
    Öncelik (aynı bar): gün-içi +2R limiti > kapanış tetiği (RS/VOL). 'tum' kapsamında
    bacaklar önce kendi kurallarını işler (B: EMA21), kalan tetikle kapanır.
    """
    GIL = None
    RSX = None
    VOLK = None
    GIL_MIN_AGE = 5
    GIL_VPCT = 0.0
    GIL_VUW = 0

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.gil_log = []     # (tarih, kurban, yıldız, kurban_pnl_pct, uw_gün, yıldız_qscore)
        self.util_curve = []  # (tarih, yatırım oranı 0..1)
        spy = getattr(self, "spy", None)
        self._spyret21 = (spy["Close"].pct_change(21) * 100.0) if spy is not None else None

    # ---- Aday 3 davranışı: gen_adaylar_curves.KX'in blend yolunun kopyası ----
    def _common(self, date):
        c = super()._common(date)
        v = BR["A200"].get(date)
        if v is not None and not pd.isna(v):
            c["spy_above_sma200"] = c["spy_above_sma200"] and bool(v >= 50.0)
        return c

    def _rank_key(self, qscore, row):
        a = row.get("ATR_PCT")
        a = float(a) if a is not None and not pd.isna(a) else 0.0
        return qscore / 100.0 + a / 10.0          # blend10 "denge karışımı"

    # ---- tetik yardımcıları ----
    def _alt_trigger(self, row):
        """RS/VOL kapanış-tetiği bu barda ateşliyor mu? -> etiket | None."""
        close = row["Close"]
        if pd.isna(close):
            return None
        if self.RSX is not None:
            x, _sc = self.RSX
            r = row.get("RET21G")
            sp = self._spyret21.get(row.name) if self._spyret21 is not None else None
            if (r is not None and sp is not None and not pd.isna(r) and not pd.isna(sp)
                    and (float(r) - float(sp)) <= -x):
                return "RS21"
        if self.VOLK is not None:
            k, _sc = self.VOLK
            ma = row.get("SMA50"); vr = row.get("VOLR50")
            if (ma is not None and vr is not None and not pd.isna(ma) and not pd.isna(vr)
                    and close < ma and float(vr) >= k):
                return "VOLK"
        return None

    def _alt_scope(self):
        if self.RSX is not None:
            return self.RSX[1]
        if self.VOLK is not None:
            return self.VOLK[1]
        return None

    def _split_leg_exit(self, leg, pos, row):
        if leg["rule"] != "target":
            return super()._split_leg_exit(leg, pos, row)
        res = super()._split_leg_exit(leg, pos, row)      # 1) +2R (gün-içi limit) önce
        if res is None and self._alt_scope() == "A":      # 2) kapanış tetiği (yalnız A)
            lab = self._alt_trigger(row)
            if lab is not None:
                res = (row["Close"], lab, True)
        return res

    def _manage_split(self, sym, pos, date, row):
        super()._manage_split(sym, pos, date, row)        # bacaklar önce kendi kuralları
        if (self._alt_scope() == "tum" and sym in self.positions
                and not pd.isna(row["Close"])):
            lab = self._alt_trigger(row)
            if lab is not None:                           # kalan TÜM pozisyon kapanıştan
                self._close(sym, date, row["Close"], lab, slip=self._stop_slip)

    # ---- giyotin ----
    def _occupies_slot(self, pos):
        if not getattr(self.cfg, "free_runner_slots", False):
            return True
        legs = getattr(pos, "legs", None)
        if legs:
            return any(l["tag"] == "A" and l["shares"] > 0 for l in legs)
        return True

    def _pick_victim(self, date, mode):
        """Zararda + slot işgal eden + yeterince yaşlı pozisyonlardan kurban seç.
        mode='pnl': en çok ekside (%); 'age': en çok su-altı günü (eşitse en çok ekside).
        Döner: (sym, close, pnl_pct, uw) | None."""
        cands = []
        for sym, pos in self.positions.items():
            if pos.entry_date == date or getattr(pos, "_bars", 0) < self.GIL_MIN_AGE:
                continue
            if not self._occupies_slot(pos):
                continue
            c = self.data[sym].loc[date, "Close"]
            if pd.isna(c) or float(c) >= pos.entry:       # kârdakine DOKUNULMAZ
                continue
            pct = (float(c) / pos.entry - 1) * 100
            uw = getattr(pos, "_uw", 0)
            if self.GIL_VPCT and pct > -self.GIL_VPCT:    # zombi filtresi: yeterince derin mi
                continue
            if self.GIL_VUW and uw < self.GIL_VUW:        # zombi filtresi: yeterince eski mi
                continue
            cands.append((sym, float(c), pct, uw))
        if not cands:
            return None
        if mode == "age":
            cands.sort(key=lambda t: (-t[3], t[2], t[0]))   # çok su-altı > çok ekside
        else:
            cands.sort(key=lambda t: (t[2], -t[3], t[0]))   # çok ekside > çok su-altı
        return cands[0]

    # ---- ana döngü: Aday 3 _step kopyası + sayaçlar + giyotin ----
    def _step(self, date):
        cfg = self.cfg
        self._manage(date)
        for sym, pos in self.positions.items():           # sayaçlar (davranışı etkilemez)
            if date == pos.entry_date:
                continue
            pos._bars = getattr(pos, "_bars", 0) + 1
            c = self.data[sym].loc[date, "Close"]
            if not pd.isna(c) and float(c) < pos.entry:
                pos._uw = getattr(pos, "_uw", 0) + 1
        common = self._common(date)
        scan_ok = common["spy_above_sma200"] and not self._vol_regime_locked(common)
        room = (self._slot_count() < cfg.max_positions and self.cash >= self._size(date))
        if scan_ok and (room or self.GIL is not None):
            cands = []
            spy_ret60 = self.spy.loc[date, "RET60"]
            for sym, df in self.data.items():
                if sym in self.positions: continue
                if not self._in_watchlist(sym, date): continue
                row = df.loc[date]
                if (pd.isna(row["Close"]) or pd.isna(row["SMA200"]) or row["Close"] <= row["SMA200"]
                        or row["Close"] <= row["SMA50"] or row["Close"] <= row["SMA20"]
                        or pd.isna(row["SLOPE200"]) or row["SLOPE200"] <= 0): continue
                plan = s.compute_trade_plan(row, cfg)
                dist = (row["Close"] - row["SMA20"]) / row["SMA20"]
                rs = self._qswing_entry_ok(row, spy_ret60)
                if rs is None: continue
                _risk = plan["entry"] - plan["stop"]
                _rec = {"rs": rs,
                        "dist_52h_pct": (row["Close"] / row["HIGH52"] - 1) * 100,
                        "dist_sma20_pct": dist * 100,
                        "risk_pct": (_risk / plan["entry"] * 100) if plan["entry"] else None}
                qscore, _ = s._qswing_priority_score(_rec)
                if cfg.qswing_min_score > 0 and qscore < cfg.qswing_min_score: continue
                cands.append((self._rank_key(qscore, row), -dist, sym, row, plan, qscore))
            cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
            for total, _nd, sym, row, plan, qscore in cands:
                if self._slot_count() < cfg.max_positions and self.cash >= self._size(date):
                    self._open(sym, date, row, plan, total)
                    continue
                if self.GIL is None:
                    break                                  # baz davranış (sadakat)
                mode, q = self.GIL
                if qscore < q or self._slot_count() < cfg.max_positions:
                    continue                               # yıldız değil / sorun nakit
                v = self._pick_victim(date, mode)
                if v is None:
                    continue
                vsym, vpx, vpct, vuw = v
                vpos = self.positions[vsym]
                proceeds = vpos.shares * vpx * (1 - self._stop_slip) - cfg.commission_per_trade
                if self.cash + proceeds < self._size(date):
                    continue                               # boşa kurban verme
                self._close(vsym, date, vpx, "GIL", slip=self._stop_slip)
                self.gil_log.append((str(date)[:10], vsym, sym, round(vpct, 1), vuw, qscore))
                if self._slot_count() < cfg.max_positions and self.cash >= self._size(date):
                    self._open(sym, date, row, plan, total)
        eq = self._equity(date)
        self.equity_curve.append((date, eq))
        self.util_curve.append((date, (1.0 - self.cash / eq) if eq else 0.0))


# =========================================================================
# SELFTEST — market verisiz semantik testleri
# =========================================================================
def selftest():
    bt = object.__new__(GKX)
    bt.cfg = s.Config(); bt.cfg.gap_fills = True
    bt.GIL = None; bt.RSX = None; bt.VOLK = None
    bt._spyret21 = pd.Series({pd.Timestamp("2026-01-05"): 4.0})
    pos = s.Position("X", pd.Timestamp("2026-01-02"), 100.0, 95.0, 110.0,
                     10.0, 1000.0, 5, risk0=5.0)

    def mkrow(**kw):
        b = {"Open": 100.0, "High": 105.0, "Low": 98.0, "Close": 102.0,
             "ATR": 2.0, "EMA21": 90.0, "SMA50": 96.0, "RET21G": 5.0, "VOLR50": 1.0}
        b.update(kw)
        r = pd.Series(b); r.name = pd.Timestamp("2026-01-05")
        return r

    def mkleg(**kw):
        l = {"tag": "A", "rule": "target", "param": 2.0,
             "shares": 6.0, "cost": 600.0, "peak": 100.0}
        l.update(kw)
        return l

    # --- RS tetiği (kapsam A) ---
    bt.RSX = (10.0, "A")
    # 1) hisse-SPY = 5-4 = +1 -> tetik yok, sakin bar -> None
    assert bt._split_leg_exit(mkleg(), pos, mkrow()) is None
    # 2) hisse-SPY = -8-4 = -12 <= -10 -> RS21, kapanıştan
    r = bt._split_leg_exit(mkleg(), pos, mkrow(RET21G=-8.0))
    assert r is not None and r[1] == "RS21" and abs(r[0] - 102.0) < 1e-9, r
    # 3) aynı barda +2R de dokundu -> hedef kazanır (gün-içi limit önce)
    r = bt._split_leg_exit(mkleg(), pos, mkrow(RET21G=-8.0, High=111.0))
    assert r is not None and r[1] == "+2R", r
    # 4) target-dışı bacak (B/ema21) A-kapsamından ETKİLENMEZ (super'e düşer)
    r = bt._split_leg_exit({"tag": "B", "rule": "ema21", "param": 0, "shares": 4.0,
                            "cost": 400.0, "peak": 100.0}, pos, mkrow(RET21G=-8.0))
    assert r is None, r
    # 5) SPY verisi NaN -> tetik yok
    bt._spyret21 = pd.Series({pd.Timestamp("2026-01-05"): float("nan")})
    assert bt._split_leg_exit(mkleg(), pos, mkrow(RET21G=-8.0)) is None
    bt._spyret21 = pd.Series({pd.Timestamp("2026-01-05"): 4.0})
    bt.RSX = None

    # --- Hacim tetiği (kapsam A) ---
    bt.VOLK = (3.0, "A")
    # 6) SMA50 altında kapanış + 3x hacim -> VOLK
    r = bt._split_leg_exit(mkleg(), pos, mkrow(Close=95.0, VOLR50=3.5))
    assert r is not None and r[1] == "VOLK" and abs(r[0] - 95.0) < 1e-9, r
    # 7) SMA50 altı ama NORMAL hacim -> dokunma
    assert bt._split_leg_exit(mkleg(), pos, mkrow(Close=95.0, VOLR50=1.2)) is None
    # 8) devasa hacim ama SMA50 ÜSTÜNDE kapanış -> dokunma
    assert bt._split_leg_exit(mkleg(), pos, mkrow(Close=97.0, VOLR50=4.0)) is None
    bt.VOLK = None

    # --- kapsam 'tum': kalan tüm pozisyon kapanıştan ---
    bt.RSX = (10.0, "tum")
    bt.positions = {}; bt.trades = []; bt.cash = 0.0
    bt._slip = 0.0; bt._stop_slip = 0.0; bt.cfg.commission_per_trade = 0.0
    p2 = s.Position("X", pd.Timestamp("2026-01-02"), 100.0, 95.0, 110.0,
                    10.0, 1000.0, 5, risk0=5.0)
    p2.legs = [mkleg(), {"tag": "B", "rule": "ema21", "param": 0, "shares": 4.0,
                         "cost": 400.0, "peak": 100.0}]
    bt.positions["X"] = p2
    row = mkrow(RET21G=-8.0, Close=99.0)                    # EMA21(90) üstü ama RS çökmüş
    bt._manage_split("X", p2, row.name, row)
    assert "X" not in bt.positions and len(bt.trades) == 1, (bt.positions, bt.trades)
    assert bt.trades[0].outcome == "RS21" and abs(bt.trades[0].exit - 99.0) < 1e-9
    # 9b) kapsam 'A' iken B bacağı yerinde kalmalı (yalnız A kapanır)
    bt.RSX = (10.0, "A"); bt.trades = []
    p3 = s.Position("X", pd.Timestamp("2026-01-02"), 100.0, 95.0, 110.0,
                    10.0, 1000.0, 5, risk0=5.0)
    p3.legs = [mkleg(), {"tag": "B", "rule": "ema21", "param": 0, "shares": 4.0,
                         "cost": 400.0, "peak": 100.0}]
    bt.positions["X"] = p3
    bt._manage_split("X", p3, row.name, row)
    assert "X" in bt.positions and len(bt.trades) == 1 and bt.trades[0].outcome == "A:RS21"
    assert p3.legs[1]["shares"] == 4.0                      # runner dokunulmadı
    bt.RSX = None; bt.positions = {}

    # --- giyotin kurban seçimi ---
    d = pd.Timestamp("2026-01-05")
    bt.cfg.free_runner_slots = True
    def mkpos(sym, entry, close, bars, uw, a_alive=True):
        p = s.Position(sym, pd.Timestamp("2026-01-02"), entry, entry * 0.95, entry * 1.1,
                       10.0, 10 * entry, 5, risk0=entry * 0.05)
        p.legs = [{"tag": "A", "rule": "target", "param": 2.0,
                   "shares": 6.0 if a_alive else 0.0, "cost": 600.0, "peak": entry},
                  {"tag": "B", "rule": "ema21", "param": 0, "shares": 4.0,
                   "cost": 400.0, "peak": entry}]
        p._bars = bars; p._uw = uw
        return p, pd.DataFrame({"Close": [close]}, index=[d])
    bt.positions = {}; bt.data = {}
    for sym, entry, close, bars, uw, alive in [
            ("L1", 100.0, 90.0, 10, 8, True),    # -%10, 8 gün su altı
            ("L2", 100.0, 96.0, 30, 25, True),   # -%4, 25 gün su altı
            ("W1", 100.0, 120.0, 30, 0, True),   # kârda -> dokunulmaz
            ("Y1", 100.0, 92.0, 3, 3, True),     # -%8 ama 3 bar < min yaş 5
            ("R1", 100.0, 85.0, 40, 35, False)]: # -%15 ama runner-only (slot işgal etmez)
        p, df = mkpos(sym, entry, close, bars, uw, alive)
        bt.positions[sym] = p; bt.data[sym] = df
    v = bt._pick_victim(d, "pnl")
    assert v is not None and v[0] == "L1", v                # en çok ekside (uygunlar içinde)
    v = bt._pick_victim(d, "age")
    assert v is not None and v[0] == "L2", v                # en çok su-altı günü
    # 12) hepsi kârda / uygun değilse kurban yok
    bt.positions = {"W1": bt.positions["W1"]}
    assert bt._pick_victim(d, "pnl") is None

    # --- zombi filtreleri (GIL_VPCT / GIL_VUW) + parse_key ---
    bt.positions = {}; bt.data = {}
    for sym, entry, close, bars, uw, alive in [
            ("Z1", 100.0, 70.0, 200, 180, True),   # -%30, 180 gün su altı (zombi)
            ("Z2", 100.0, 90.0, 30, 20, True)]:    # -%10, 20 gün (sıradan zarar)
        p, df = mkpos(sym, entry, close, bars, uw, alive)
        bt.positions[sym] = p; bt.data[sym] = df
    bt.GIL_VPCT = 25.0
    v = bt._pick_victim(d, "pnl")
    assert v is not None and v[0] == "Z1", v                # yalnız zombi geçer
    bt.GIL_VPCT = 45.0
    assert bt._pick_victim(d, "pnl") is None                # kimse yeterince derin değil
    bt.GIL_VPCT = 0.0; bt.GIL_VUW = 100
    v = bt._pick_victim(d, "age")
    assert v is not None and v[0] == "Z1", v                # yaş filtresi
    bt.GIL_VUW = 0
    assert parse_key("gil-pnl85v25") == {"gil": ("pnl", 85), "vpct": 25.0, "vuw": 0,
                                         "min_age": 5}
    assert parse_key("gil-age90u120") == {"gil": ("age", 90), "vpct": 0.0, "vuw": 120,
                                          "min_age": 5}
    assert parse_key("gil-pnl92a21") == {"gil": ("pnl", 92), "vpct": 0.0, "vuw": 0,
                                         "min_age": 21}
    assert parse_key("gil-pnl92u200a63") == {"gil": ("pnl", 92), "vpct": 0.0, "vuw": 200,
                                             "min_age": 63}
    print("selftest: 17/17 GEÇTİ")


# =========================================================================
# VERİ + BATARYA
# =========================================================================
def load_data():
    global BR, MARKET
    if MARKET is not None:
        return
    BR = pickle.load(open(BREADTH_PKL, "rb"))
    with open(CACHE, "rb") as fh:
        MARKET = pickle.load(fh)
    MARKET = s.attach_watchlist(MARKET, base_cfg())
    for sym, df in MARKET["data"].items():                 # tetik kolonları (motor okumaz)
        df["RET21G"] = df["Close"].pct_change(21) * 100.0
        df["VOLR50"] = df["Volume"] / df["Volume"].rolling(50).mean().shift(1)
    print("cache sabit: 152dab0ec647 · %d hisse" % len(MARKET["data"]), flush=True)


ALT_LABELS = ("GIL", "RS21", "VOLK", "A:RS21", "A:VOLK")


def _tail_stats(bt):
    """Kuyruk + tetik metrikleri: en kötü tek çıkış %, tetik sayaçları, giyotin detayı."""
    worst = 0.0; counts = {}
    for t in bt.trades:
        worst = min(worst, t.pnl_pct)
        lab = t.outcome
        counts[lab] = counts.get(lab, 0) + 1
    trig = sum(v for k, v in counts.items() if k in ALT_LABELS)
    out = {"worst_pct": round(worst, 1), "trig_n": trig, "counts": counts}
    if bt.gil_log:
        pcts = [g[3] for g in bt.gil_log]
        out["gil"] = {"n": len(bt.gil_log),
                      "med_pct": round(float(pd.Series(pcts).median()), 1),
                      "med_uw": round(float(pd.Series([g[4] for g in bt.gil_log]).median()), 0)}
        assert all(p < 0 for p in pcts), "GIL kurbanı kârdaydı!"   # tutarlılık
    return out


def run_windows(gil=None, rsx=None, volk=None, vpct=0.0, vuw=0, min_age=5, label=""):
    load_data()
    rows = []
    for wi, (wn, sd, ed) in enumerate(WINS):
        c = copy.deepcopy(base_cfg()); c.start_date = sd; c.end_date = ed
        GKX.GIL = gil; GKX.RSX = rsx; GKX.VOLK = volk
        GKX.GIL_VPCT = vpct; GKX.GIL_VUW = vuw; GKX.GIL_MIN_AGE = min_age
        bt = GKX(c, market=MARKET); bt.run()
        m = bt.metrics()
        row = {"win": wn, "roi": round(m["roi"], 1), "max_dd": round(m["max_dd"], 1),
               "pf": round(m["profit_factor"], 2), "win_rate": round(m["win_rate"], 0),
               "trades": m["trades"],
               "util_med": round(pd.Series([u for _, u in bt.util_curve]).median() * 100, 1)}
        row.update(_tail_stats(bt))
        if wi in (0, 4):   # eğri yalnız 5y tam + son 1y (rapora gömülür)
            ds = [str(d)[:10] for d, _ in bt.equity_curve]
            eq = [e for _, e in bt.equity_curve]
            spy = bt.spy["Close"].reindex([d for d, _ in bt.equity_curve]).ffill()
            row["curve"] = {"d": ds,
                            "eq": [round(e / eq[0] * 100, 2) for e in eq],
                            "spy": [round(float(v) / float(spy.iloc[0]) * 100, 2) for v in spy]}
        rows.append(row)
        print("  %-11s %-12s roi %+7.1f · dd %6.1f · pf %5.2f · n %d · tetik %d" %
              (label, wn, row["roi"], row["max_dd"], row["pf"], row["trades"],
               row["trig_n"]), flush=True)
    return rows


def fidelity(rows):
    ok = True
    for row, (eroi, en) in zip(rows, EXPECTED):
        hit = (abs(row["roi"] - eroi) < 0.05) and (row["trades"] == en)
        print("  %-12s roi %+7.1f (beklenen %+7.1f) · n %d (beklenen %d) -> %s" %
              (row["win"], row["roi"], eroi, row["trades"], en, "OK" if hit else "FARK!"))
        ok = ok and hit
    return ok


WAVE1 = [
    ("none",      {}),
    ("gil-pnl85", {"gil": ("pnl", 85)}),
    ("gil-pnl90", {"gil": ("pnl", 90)}),
    ("gil-age85", {"gil": ("age", 85)}),
    ("gil-age90", {"gil": ("age", 90)}),
    ("rs10-A",    {"rsx": (10.0, "A")}),
    ("rs10-tum",  {"rsx": (10.0, "tum")}),
    ("rs15-A",    {"rsx": (15.0, "A")}),
    ("rs15-tum",  {"rsx": (15.0, "tum")}),
    ("vol2.5-A",  {"volk": (2.5, "A")}),
    ("vol2.5-tum", {"volk": (2.5, "tum")}),
    ("vol3.5-A",  {"volk": (3.5, "A")}),
    ("vol3.5-tum", {"volk": (3.5, "tum")}),
]


def save_json(obj):
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    tmp = OUT_JSON + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, OUT_JSON)
    print("yazıldı:", OUT_JSON)


def load_json():
    with open(OUT_JSON) as fh:
        return json.load(fh)


def _run_variant(out, key, kw):
    print("varyant:", key, flush=True)
    rows = run_windows(gil=kw.get("gil"), rsx=kw.get("rsx"), volk=kw.get("volk"),
                       vpct=kw.get("vpct", 0.0), vuw=kw.get("vuw", 0),
                       min_age=kw.get("min_age", 5), label=key)
    out["variants"][key] = {"kind": kw, "rows": rows}


def wave1():
    out = {"meta": {"cache": "152dab0ec647", "windows": [w[0] for w in WINS],
                    "spec": "2026-07-08-splitA-alternatif-korumalar-design.md"},
           "variants": {}}
    for key, kw in WAVE1:
        _run_variant(out, key, kw)
    if not fidelity(out["variants"]["none"]["rows"]):
        raise SystemExit("SADAKAT KANITI BAŞARISIZ — JSON yazılmadı.")
    out["fidelity_ok"] = True
    for key, kw in WAVE1[1:]:      # tutarlılık: her koruma en az bir kez tetiklenmeli
        tot = sum(r["trig_n"] for r in out["variants"][key]["rows"])
        assert tot > 0, "hiç tetiklenmedi: " + key
    save_json(out)
    _print_rank(out)


def score_variant(rows, base_rows):
    """Risk-ayarlı skor (dünkü spec ile aynı): 5 pencere ort. ( Δroi + DD-iyileşmesi )."""
    return sum((rv["roi"] - rb["roi"]) + (rb["max_dd"] - rv["max_dd"])
               for rv, rb in zip(rows, base_rows)) / len(rows)


def _print_rank(d):
    base = d["variants"]["none"]["rows"]
    rank = sorted(d["variants"], key=lambda k: score_variant(d["variants"][k]["rows"], base),
                  reverse=True)
    print("skor sıralaması:")
    for k in rank:
        print("  %+8.1f  %s" % (score_variant(d["variants"][k]["rows"], base), k))


def wave2(specs):
    """İterasyon: 'gil-pnl80' 'rs20-tum' 'vol3.0-A' 'gilminage10-pnl85' gibi ad listesi."""
    d = load_json()
    assert d.get("fidelity_ok"), "önce --wave1"
    for key in specs:
        kw = parse_key(key)
        _run_variant(d, key, kw)
    save_json(d)
    _print_rank(d)


def parse_key(key):
    """Varyant adı -> kwargs. gil-<mode><Q>[v<pct>][u<gün>] | rs<X>-<scope> | vol<k>-<scope>.
    Ör: gil-pnl90 · gil-pnl85v25 (kurban ≥ −%25 ekside) · gil-age85u120 (kurban ≥ 120 gün su altı)."""
    if key.startswith("gil-"):
        m = re.match(r"^(pnl|age)(\d+)(?:v(\d+(?:\.\d+)?))?(?:u(\d+))?(?:a(\d+))?$", key[4:])
        assert m, key
        mode, q = m.group(1), int(m.group(2))
        assert 0 < q <= 100, key
        return {"gil": (mode, q), "vpct": float(m.group(3) or 0),
                "vuw": int(m.group(4) or 0), "min_age": int(m.group(5) or 5)}
    if key.startswith("rs"):
        x, scope = key[2:].split("-")
        assert scope in ("A", "tum"), key
        return {"rsx": (float(x), scope)}
    if key.startswith("vol"):
        k, scope = key[3:].split("-")
        assert scope in ("A", "tum"), key
        return {"volk": (float(k), scope)}
    raise SystemExit("anlaşılmayan varyant adı: " + key)


# =========================================================================
# RAPOR (/adaylar — ALTAB bölümü)
# =========================================================================
TR = lambda v: ("%.1f" % v).replace(".", ",")

VLABEL = {
    "none":       "Baz — bugünkü canlı (A bacağı korumasız)",
    "gil-pnl85":  "Giyotin: yıldız (skor≥85) gelince en çok EKSİDEKİ kurban edilir",
    "gil-pnl90":  "Giyotin: yıldız (skor≥90) gelince en çok EKSİDEKİ kurban edilir",
    "gil-age85":  "Giyotin: yıldız (skor≥85) gelince en uzun SU ALTINDAKİ kurban edilir",
    "gil-age90":  "Giyotin: yıldız (skor≥90) gelince en uzun SU ALTINDAKİ kurban edilir",
    "rs10-A":     "RS çöküşü: 21 günde SPY'nin −10 puan gerisi → A bacağı satılır",
    "rs10-tum":   "RS çöküşü: 21 günde SPY'nin −10 puan gerisi → TÜM pozisyon satılır",
    "rs15-A":     "RS çöküşü: 21 günde SPY'nin −15 puan gerisi → A bacağı satılır",
    "rs15-tum":   "RS çöküşü: 21 günde SPY'nin −15 puan gerisi → TÜM pozisyon satılır",
    "vol2.5-A":   "Hacim kırılımı: ≥2,5× hacimle SMA50 altında kapanış → A bacağı satılır",
    "vol2.5-tum": "Hacim kırılımı: ≥2,5× hacimle SMA50 altında kapanış → TÜM pozisyon satılır",
    "vol3.5-A":   "Hacim kırılımı: ≥3,5× hacimle SMA50 altında kapanış → A bacağı satılır",
    "vol3.5-tum": "Hacim kırılımı: ≥3,5× hacimle SMA50 altında kapanış → TÜM pozisyon satılır",
}


def _vlabel(key):
    if key in VLABEL:
        return VLABEL[key]
    kw = parse_key(key)                                    # wave2 türetilmiş adlar
    if "gil" in kw:
        m, q = kw["gil"]
        who = "en çok EKSİDEKİ" if m == "pnl" else "en uzun SU ALTINDAKİ"
        zf = ""
        if kw.get("vpct"):
            zf += "; kurban ≥ −%%%d ekside olmalı" % int(kw["vpct"])
        if kw.get("vuw"):
            zf += "; kurban ≥ %d gün su altında olmalı" % kw["vuw"]
        if kw.get("min_age", 5) != 5:
            zf += "; kurban ≥ %d gün taşınmış olmalı" % kw["min_age"]
        return "Giyotin: yıldız (skor≥%d) gelince %s kurban edilir%s" % (q, who, zf)
    if "rsx" in kw:
        x, sc = kw["rsx"]
        return "RS çöküşü: 21 günde SPY'nin −%s puan gerisi → %s satılır" % (
            TR(x).replace(",0", ""), "A bacağı" if sc == "A" else "TÜM pozisyon")
    k, sc = kw["volk"]
    return "Hacim kırılımı: ≥%s× hacimle SMA50 altında kapanış → %s satılır" % (
        TR(k), "A bacağı" if sc == "A" else "TÜM pozisyon")


def report():
    d = load_json()
    assert d.get("fidelity_ok"), "sadakat kanıtı olmadan rapor yazılmaz"
    base = d["variants"]["none"]["rows"]
    keys = list(d["variants"])
    rank = sorted(keys, key=lambda k: score_variant(d["variants"][k]["rows"], base),
                  reverse=True)
    # eğri finalistleri: kazanan fikir + en iyi kaybeden fikir (hikâyenin iki ucu);
    # rank top-2 (pnl92/93) neredeyse aynı eğri olurdu
    finalists = [k for k in ("gil-pnl92", "vol3.5-A") if k in d["variants"]] \
        or [k for k in rank if k != "none"][:2]
    wins_tr = ["5 yıl (tümü, 2021→2026)", "Düşüş dönemi 2021-23 (zor dönem)",
               "Toparlanma 2023-25", "Son 2 yıl", "Son 1 yıl"]

    rowsh = []
    for wi, wn in enumerate(wins_tr):
        best_roi = max(d["variants"][k]["rows"][wi]["roi"] for k in keys)
        best_dd = max(d["variants"][k]["rows"][wi]["max_dd"] for k in keys)
        best_pf = max(d["variants"][k]["rows"][wi]["pf"] for k in keys)
        for k in rank:                       # her dönem içinde skor sırasıyla
            r = d["variants"][k]["rows"][wi]
            hl = ' style="background:rgba(201,133,0,.08)"' if k == "none" else ""
            def cell(v, best, fmt):
                sx = fmt(v)
                return "<b>%s</b>" % sx if abs(v - best) < 1e-9 else sx
            rowsh.append(
                "<tr%s><td>%s · %s</td><td>%s</td><td>%s</td><td>%s</td>"
                "<td>%d</td><td>%d</td><td>%s</td><td>%s</td></tr>" % (
                    hl, wn, _vlabel(k),
                    cell(r["roi"], best_roi, lambda v: ("+%" if v >= 0 else "−%") + TR(abs(v))),
                    cell(r["max_dd"], best_dd, lambda v: "−%" + TR(abs(v))),
                    cell(r["pf"], best_pf, lambda v: ("%.2f" % v).replace(".", ",")),
                    r["trades"], r["trig_n"], "%" + TR(r["util_med"]),
                    ("+%" if r["worst_pct"] >= 0 else "−%") + TR(abs(r["worst_pct"]))))
    table = ('<div style="overflow-x:auto"><table><tr><th>Dönem · Koruma</th><th>Getiri</th>'
             '<th>En derin çukur</th><th>Denge (1\'e karşı)</th><th>İşlem</th>'
             '<th>Tetik</th><th>Parada kalma</th><th>En kötü tek çıkış</th></tr>'
             + "".join(rowsh) + "</table></div>")

    top = [k for k in rank if k != "none"][0]
    droi5 = d["variants"][top]["rows"][0]["roi"] - base[0]["roi"]
    beats = [k for k in rank if k != "none"
             and score_variant(d["variants"][k]["rows"], base) > 0]
    if beats:
        verdict = ("<b>Kısa cevap: RS çöküşü ve hacim kırılımı HER ayarda ağır kaybettirdi "
                   "(5 yıllık getiride bazın 70-140 puan gerisi); tek geçen fikir GİYOTİN "
                   "gibi göründü — ama sağlamlık sorgusunda o da çöktü.</b> Skor≥92 giyotin "
                   "kâğıt üstünde 5 yılda +%%166 → +%%210 verdi; ne var ki test penceresinin "
                   "başlangıcını birkaç ay kaydırınca aynı kural bazın 9-20 puan GERİSİNE "
                   "düşüyor (aşağıda jitter tablosu). Tabloda bazı geçen %d satırın hepsi aynı "
                   "fikrin farklı eşikleri; kazanç tek şanslı takastan (MRVL→META) geliyor. "
                   "Takas dökümü, sağlamlık sorgusu ve karar aşağıda." % len(beats))
    else:
        verdict = ("<b>Kısa cevap: HAYIR — üç fikrin hiçbir varyantı bazı geçemedi.</b> "
                   "En yakını bile (%s) 5 yıllık getiride bazın %s puan gerisinde. Dünkü 🛡️ "
                   "dersinin genellemesi doğrulandı: tetik ne kadar akıllıca seçilirse seçilsin "
                   "(göreli güç, kurumsal hacim, slot rotasyonu), zarardaki A bacağını erken "
                   "kesen HER kural bu sistemde getiri kaynağını (sineye çekip +2R'de satmayı) "
                   "buduyor." % (_vlabel(top),
                                 ("−%d" if droi5 < 0 else "+%d") % abs(round(droi5))))

    gil_rows = [(k, d["variants"][k]["rows"][0].get("gil"))
                for k in keys if d["variants"][k]["rows"][0].get("gil")]
    gil_note = ""
    if gil_rows:
        parts = ["%s: %d kurban (tipik kurban −%%%s, ~%d gün su altındaydı)" % (
                     k, g["n"], TR(abs(g["med_pct"])), int(g["med_uw"])) for k, g in gil_rows]
        gil_note = ("<p><b>Giyotin gerçekte ne yaptı?</b> 5 yıllık pencerede " +
                    " · ".join(parts) + ".</p>")
        # kazananın takas dökümü (koşu log'undan birebir çıkarıldı, gil-pnl92)
        gil_note += """
<p><b>Kazananın (skor≥92) bütün takasları — hepsi bu kadar:</b></p>
<div style="overflow-x:auto"><table>
<tr><th>Dönem</th><th>Tarih</th><th>Kurban (zarar · su altı)</th><th>Yerine giren yıldız</th><th>Sonuç</th></tr>
<tr><td>5 yıl</td><td>2023-04-13</td><td>MRVL (−%51,7 · 316 gün)</td><td>META (skor 92)</td>
<td rowspan="2">5 yılda +43,5 puan — kazancın neredeyse tamamı MRVL→META takasından</td></tr>
<tr><td>5 yıl</td><td>2026-01-08</td><td>EXR (−%39,6 · 1009 gün)</td><td>GM (skor 92)</td></tr>
<tr><td>Son 2 yıl</td><td>2025-06-24</td><td>TTD (−%48,4 · 136 gün)</td><td>GEV (skor 95)</td>
<td rowspan="2">Son 2 yılda −10,1 puan — bu iki takas KAYBETTİRDİ</td></tr>
<tr><td>Son 2 yıl</td><td>2026-01-08</td><td>PAYC (−%39,0 · 153 gün)</td><td>GM (skor 92)</td></tr>
</table></div>
<p class="note">Yani 5 yıllık +43,5 puanlık fark tek bir şanslı takasa (2023'te dibe vurmuş
MRVL'den çıkıp META'nın yükselişine binmek) dayanıyor; aynı kural 2025'te TTD'den çıkıp
GEV'e binince de ters tepti. 2-4 olaydan istatistik çıkmaz — eldeki şey "kural" değil,
iki anekdot.</p>
<h3>🔬 Sağlamlık sorgusu (dalga-3): anekdot mu, kural mı?</h3>
<p>Üç ayrı test yapıldı:</p>
<p><b>1) Min-yaş taraması — etkisiz (iyi haber).</b> "Kurban en az 21/63 gün taşınmış
olmalı" şartları sonucu bir milim oynatmadı (a21 = a63 = düz skor≥92): kurbanlar zaten
136-1009 gündür su altında yatan zombiler, bu düğme hiç devreye girmiyor.</p>
<p><b>2) Su-altı filtresi — aşırı hassasiyet (kötü haber).</b> "Kurban ≥300 gün su altında
olsun" (u300) skoru +8,9'a taşıyıp yeni lider oldu — ama komşusu u200 aynı testte +4,9'a
düşüyor: giyotini TTD/PAYC yerine başka kurbanlara yönlendirdi ve o takaslar daha da kötü
çıktı (son 2 yıl +%62,5). İki komşu eşiğin son-2-yıl etkisi −19 ile +1 puan arasında
savruluyor; üstelik 300 sayısı, kaybeden takasların (136/153 gün) ile kazananın (316 gün)
tam ortasına GERİYE BAKARAK konmuş bir değer. u300'ün liderliği fikrin gücünü değil,
4 olaylık örneklemde parametrenin gürültüyü ezberlediğini gösterir.</p>
<p><b>3) Başlangıç-tarihi kaydırma (jitter) — belirleyici test, giyotin ÇÖKTÜ.</b>
5 yıllık pencerenin başlangıcı aylarla kaydırılıp her başlangıçta baz ile skor≥92 giyotin
yeniden koşuldu (veri 2021-05'te başladığı için daha erken başlangıçlar oraya kilitlenir):</p>
<div style="overflow-x:auto"><table>
<tr><th>Başlangıç</th><th>Baz getiri</th><th>Giyotin getiri</th><th>Fark</th><th>Takaslar</th></tr>
<tr><td>2021-05 (rapordaki)</td><td>+%166,3</td><td>+%209,8</td><td><b>+43,5</b></td><td>MRVL→META · EXR→GM</td></tr>
<tr><td>2021-07</td><td>+%161,2</td><td>+%179,5</td><td><b>+18,4</b></td><td>DDOG→META · INTC→TPR · MRVL→GM</td></tr>
<tr><td>2021-09</td><td>+%94,9</td><td>+%75,3</td><td><b>−19,6</b></td><td>DDOG→META · PAYC→TPR · VFC→GEV · FSLR→WDC · EXR→WBD</td></tr>
<tr><td>2021-11</td><td>+%116,1</td><td>+%103,0</td><td><b>−13,1</b></td><td>DDOG→META · INTC→TPR · MDB→RCL · TEAM→GM · BX→HUM</td></tr>
<tr><td>2022-01</td><td>+%150,4</td><td>+%141,9</td><td><b>−8,6</b></td><td>INTC→STX · FSLR→WDC · TER→RCL · DASH→HUM</td></tr>
</table></div>
<p class="note">5 farklı başlangıcın 2'sinde kazanç, 3'ünde KAYIP; işaret başlangıç tarihine
göre dönüyor (+43,5 ↔ −19,6). Kazanan pencereler META'yı yakalayan pencereler; META'sız
takasların (TPR, WBD, WDC, RCL, HUM…) toplamı eksi. Yani rapordaki +43,5, kuralın gücü
değil, pencerenin MRVL→META takasına denk gelme şansı. Bu, "giyotin geçti" hükmünü
düşürür.</p>"""

    section = """<!-- ALTAB:BEGIN -->
<h2 id="altab">♻️ Stopsuz bacağa alternatif korumalar — giyotin · RS çöküşü · hacim kırılımı (2026-07-08)</h2>
<blockquote><p><b>Soru (kullanıcı fikirleri):</b> Dünkü 🛡️ deneyi klasik stop/timeout'un
kaybettirdiğini gösterdi. Peki fiyat-düşüşü-DIŞI tetikler? <b>1) Giyotin:</b> zarardaki pozisyon
kendi başına satılmasın; ama 20 slot doluyken dışarıdan çok güçlü bir sinyal (kalite skoru ≥85/90)
gelirse, en kötü durumdaki pozisyon zorla satılıp yeri yıldıza verilsin. <b>2) RS çöküşü:</b>
hissenin kendi düşüşüne değil endekse göre gücüne bak — pozisyondayken 21 günde SPY'nin
10-15 puan gerisine düşerse sat. <b>3) Hacim-teyitli kırılım:</b> 50g ortalama hacmin
2,5-3,5 katı devasa hacimle (kurumsal satış) SMA50 altında kapanırsa sat; normal hacimli
sıradan düşüşlere dokunma. RS/hacim tetikleri hem yalnız-A hem tüm-pozisyon kapsamıyla denendi.
Aynı sabit veri, aynı 5 dönem, aynı skor kriteri (getiri + çukur-iyileşmesi).</p></blockquote>
<p>%VERDICT%</p>
%TABLE%
%GILNOTE%
<p class="note">Nasıl okunur: "Tetik" = korumanın o dönemde kaç işlemi kapattığı (giyotinde
kurban sayısı; sıfıra yakınsa kural nadiren devreye girmiş demektir). Öncelik: aynı barda
gün-içi +2R limiti kapanış-tetiğinden önce gelir; giyotin gün sonunda, kurban o günün
kapanışından satılır ve yıldız aynı gün girer; kurban yalnız ZARARDA + ≥5 gün taşınmış +
slot işgal eden pozisyonlardan seçilir, kârdakine dokunulmaz. Dürüstlük: RS/hacim eşikleri ve
giyotin yaş/eşik değerleri denenmiş birkaç değerdir (ince ayar aramadık); 2021-26 örneklemi
V-tipi toparlanmalarla dolu — "dipte satmamak kazandırır" dersi bu örnekleme bağlı olabilir;
geçmiş sonuç gelecek garantisi değildir.</p>
<div class="leg" id="altLeg"></div>
<div id="altLcharts"></div>
%DECISION%
<!-- ALTAB:END -->
""".replace("%TABLE%", table).replace("%VERDICT%", verdict).replace("%GILNOTE%", gil_note) \
   .replace("%DECISION%", d.get("decision_html", ""))

    curves = {}
    for wjs, wi in (("w0", 0), ("w4", 4)):
        c0 = d["variants"]["none"]["rows"][wi]["curve"]
        curves[wjs] = {"d": c0["d"], "spy": c0["spy"], "none": c0["eq"]}
        for k in finalists:
            curves[wjs][k] = d["variants"][k]["rows"][wi]["curve"]["eq"]
    fin_js = json.dumps([{"k": k, "n": _vlabel(k)} for k in finalists], ensure_ascii=False)
    script = """<!-- ALTABJS:BEGIN -->
<script>
(function(){
 const SC=%CURVES%;
 const FIN=%FIN%;
 const box=document.getElementById('altLcharts');
 if(!box) return;
 if(typeof LightweightCharts==='undefined'){box.innerHTML='<p class="note">Grafik kütüphanesi yüklenemedi.</p>';return;}
 const SER=[{k:'spy',n:'SPY — endeks fonu',c:'#9085e9',st:2},
            {k:'none',n:'Baz — bugünkü canlı (korumasız)',c:'#c98500',st:0}]
   .concat(FIN.map((f,i)=>({k:f.k,n:f.n,c:['#3987e5','#199e70'][i]||'#8b949e',st:0})));
 document.getElementById('altLeg').innerHTML=SER.map(s=>
  `<span><span style="display:inline-block;width:18px;border-top:2.5px ${s.st?'dashed':'solid'} ${s.c};vertical-align:3px"></span>${s.n}</span>`).join('');
 const TITLES={w0:'5 yıl (tümü, 2021→2026)',w4:'Son 1 yıl'};
 for(const w of ['w0','w4']){
  const cur=SC[w]; if(!cur) continue;
  const card=document.createElement('div'); card.className='card';
  card.innerHTML=`<div class="gt">${TITLES[w]} <span class="mut" style="font-weight:400">· başlangıç = 100</span></div><div class="lc" style="height:290px"></div>`;
  box.appendChild(card);
  const el=card.querySelector('.lc');
  const ch=LightweightCharts.createChart(el,{
   layout:{background:{color:'#161b22'},textColor:'#8b949e'},
   grid:{vertLines:{color:'#21262d'},horzLines:{color:'#21262d'}},
   rightPriceScale:{borderColor:'#30363d',mode:1},
   timeScale:{borderColor:'#30363d'}, height:290, width:el.clientWidth});
  new ResizeObserver(()=>ch.applyOptions({width:el.clientWidth})).observe(el);
  for(const s of SER){
   if(!cur[s.k]) continue;
   ch.addLineSeries({color:s.c,lineWidth:2,lineStyle:s.st,lastValueVisible:false,priceLineVisible:false})
     .setData(cur.d.map((dd,j)=>({time:dd,value:cur[s.k][j]})));
  }
  ch.timeScale().fitContent();
 }
})();
</script>
<!-- ALTABJS:END -->
""".replace("%CURVES%", json.dumps(curves)).replace("%FIN%", fin_js)

    import datetime
    html = open(ADAYLAR).read()
    bak = ADAYLAR + ".bak." + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    open(bak, "w").write(html)
    print("yedek:", bak)

    def upsert(h, begin, end, block, anchor):
        if begin in h:
            pre, rest = h.split(begin, 1)
            _, post = rest.split(end, 1)
            return pre + block.rstrip("\n") + post
        assert anchor in h, "çapa bulunamadı: " + anchor
        return h.replace(anchor, block + anchor, 1)

    html = upsert(html, "<!-- ALTAB:BEGIN -->", "<!-- ALTAB:END -->", section,
                  "<h2>Karar öncesi tartılan noktalar</h2>")
    html = upsert(html, "<!-- ALTABJS:BEGIN -->", "<!-- ALTABJS:END -->", script,
                  "</body></html>")
    open(ADAYLAR, "w").write(html)
    print("adaylar.html güncellendi · finalistler:", finalists, "· sıralama:", " > ".join(rank))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fidelity", action="store_true")
    ap.add_argument("--wave1", action="store_true")
    ap.add_argument("--wave2", nargs="+", metavar="VARYANT")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest(); return
    if args.fidelity:
        rows = run_windows(label="none")
        if not fidelity(rows):
            raise SystemExit("SADAKAT KANITI BAŞARISIZ — deney durduruldu, harness hatası ara.")
        print("SADAKAT: 5/5 birebir."); return
    if args.wave1:
        wave1(); return
    if args.wave2:
        wave2(args.wave2); return
    if args.report:
        report(); return
    ap.error("bir mod seç: --selftest / --fidelity / --wave1 / --wave2 / --report")


if __name__ == "__main__":
    main()

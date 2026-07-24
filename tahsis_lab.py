#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tahsis_lab.py — SERMAYE TAHSİSAT OPTİMİZASYONU (2026-07-09).

Fiyat-stopu arayışı kapandı (splitstop + altguard + ML seferi: giriş anında sahte/gerçek
ayrımı YOK). Bu lab iki YÖNETİMSEL kural test eder — canlı çıkış kuralları (take-profit
+2R, EMA21 runner) ASLA değişmez, kurallar yalnız giriş/portföy anında tetiklenir:

  1) GİYOTİN-2 (fırsat maliyeti çıkışı) — 20/20 doluyken qscore>QMIN "yıldız" gelirse
     Kurban_Skoru = 0.6×zarar_oranı + 0.4×tutma_süresi(60g'de doyar) ile kurban seç;
     yıldızın qscore'u kurbanın GİRİŞ qscore'unun ≥ MARGIN katıysa kurbanı kapanıştan
     sat, yeri yıldıza ver. NOT: dünkü giyotin (pnl/age sıralı, marjsız) jitter'da
     ÇÖKMÜŞTÜ — bu FARKLI formülasyon aynı titizlikle (jitter dahil) sınanır.
  2) VIX ŞALTERİ — ^VIX günlük değişim ≥ +%25 ise TÜM pozisyonlar o gün kapanıştan
     satılır, o gün yeni giriş yok (sistemik likidite krizi simülasyonu; ertesi gün
     normal kurallar).

SADAKAT ZORUNLU: iki kural da kapalıyken 5 pencerede ROI+N batarya EXPECTED ile birebir.
Kullanım: python3 tahsis_lab.py [--selftest|--fidelity|--main|--jitter|--all(varsayılan)]
"""
import argparse
import copy
import json
import os
import pickle
import sys

sys.path.insert(0, "/home/gokhan")
os.chdir("/home/gokhan")
import numpy as np
import pandas as pd

import altguard_lab as ag          # sabit cache + Aday 3 kopyası (GKX) + fidelity çapaları
import swing2_backtest as s

VIX_PKL = "swing2_cache/vix_5y.pkl"
OUT_JSON = "/home/gokhan/swing2_out/tahsis_results.json"
OUT_PNG = "/home/gokhan/swing2_out/tahsis_lab.png"

JITTER_STARTS = ["2021-05-01", "2021-05-08", "2021-05-15", "2021-05-22", "2021-06-01"]


# ---------------------------------------------------------------- VIX verisi
def load_vix():
    if os.path.exists(VIX_PKL):
        return pickle.load(open(VIX_PKL, "rb"))
    import urllib.request
    key = s._fmp_key()
    url = ("https://financialmodelingprep.com/stable/historical-price-eod/full"
           f"?symbol=%5EVIX&from=2020-06-01&to=2026-12-31&apikey={key}")
    d = json.load(urllib.request.urlopen(url, timeout=30))
    rows = d if isinstance(d, list) else d.get("historical", [])
    ser = pd.Series({pd.Timestamp(r["date"]): float(r["close"]) for r in rows}).sort_index()
    pickle.dump(ser, open(VIX_PKL, "wb"))
    return ser


# ---------------------------------------------------------------- motor varyantı
class TKX(ag.GKX):
    """Aday 3 kopyası + GİYOTİN-2 + VIX şalteri. ag.GKX'in GIL/RSX/VOLK'u hep None kalır."""
    GIL2 = None          # None | dict(qmin=90, margin=1.2, losers_only=False, min_age=5)
    VIXK = None          # None | 0.25  (günlük VIX sıçrama eşiği)
    VIX = None           # pd.Series (close)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.gil2_log = []    # dict: tarih, kurban, yıldız, kurban_pnl, kurban_skor, q'lar
        self.vix_log = []     # (tarih, vix_chg, kapatılan_n)
        self.missed_log = []  # BAZ: kaçan yıldız + o günkü formül-kurbanı (davranış değişmez)
        self.slot_curve = []  # (tarih, dolu_slot/max)
        self._vix_chg = None
        if self.VIX is not None:
            self._vix_chg = self.VIX.pct_change()

    # ---- giyotin-2 kurban formülü ----
    def _victim2(self, date):
        g = self.GIL2 or {}
        best = None
        for sym, pos in self.positions.items():
            if pos.entry_date == date or getattr(pos, "_bars", 0) < g.get("min_age", 5):
                continue
            if not self._occupies_slot(pos):
                continue                                   # slot açmayan kurban işe yaramaz
            c = self.data[sym].loc[date, "Close"]
            if pd.isna(c):
                continue
            zarar = max(0.0, 1.0 - float(c) / pos.entry)   # 0..~0.5 (kârda 0)
            if g.get("losers_only") and zarar <= 0.0:
                continue
            sure = min(getattr(pos, "_bars", 0) / 60.0, 1.0)
            skor = 0.6 * zarar + 0.4 * sure
            key = (skor, zarar, sym)
            if best is None or key > best[0]:
                best = (key, sym, float(c), (float(c) / pos.entry - 1) * 100, skor)
        if best is None:
            return None
        _, sym, px, pnl, skor = best
        return sym, px, pnl, skor, getattr(self.positions[sym], "_qscore", None)

    # ---- ana döngü: GKX._step kopyası + VIX + giyotin-2 + kaçan-yıldız günlüğü ----
    def _step(self, date):
        cfg = self.cfg
        self._manage(date)
        for sym, pos in self.positions.items():
            if date == pos.entry_date:
                continue
            pos._bars = getattr(pos, "_bars", 0) + 1
            c = self.data[sym].loc[date, "Close"]
            if not pd.isna(c) and float(c) < pos.entry:
                pos._uw = getattr(pos, "_uw", 0) + 1

        # ---- VIX ŞALTERİ: sıçrama günü her şey kapanıştan satılır, giriş yok ----
        if self.VIXK is not None and self._vix_chg is not None:
            chg = self._vix_chg.get(date)
            if chg is not None and not pd.isna(chg) and float(chg) >= self.VIXK:
                n = 0
                for sym in list(self.positions):
                    c = self.data[sym].loc[date, "Close"]
                    px = float(c) if not pd.isna(c) else self.positions[sym].entry
                    self._close(sym, date, px, "VIX", slip=self._stop_slip)
                    n += 1
                self.vix_log.append((str(date)[:10], round(float(chg) * 100, 1), n))
                self._append_curves(date)
                return

        common = self._common(date)
        scan_ok = common["spy_above_sma200"] and not self._vol_regime_locked(common)
        # NOT: tarama dolu günlerde de yapılır (kaçan-yıldız günlüğü için); baz modda
        # açılışlar yalnız yer varken olduğundan işlem seti orijinalle birebir kalır
        # (sadakat testi bunu 5 pencerede ROI+N ile kanıtlar).
        if scan_ok:
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
                    if self._open(sym, date, row, plan, total):
                        self.positions[sym]._qscore = qscore
                    continue
                if self.GIL2 is None:
                    # BAZ: davranış değişmez; yalnız kaçan yıldızı + formül-kurbanını NOT ET
                    if qscore >= 90 and self._slot_count() >= cfg.max_positions:
                        v = self._victim2(date)
                        self.missed_log.append({"t": str(date)[:10], "star": sym, "q": qscore,
                                                "victim": v[0] if v else None,
                                                "v_pnl": round(v[2], 1) if v else None})
                    continue
                g = self.GIL2
                if qscore < g["qmin"] or self._slot_count() < cfg.max_positions:
                    continue                               # yıldız değil / sorun nakit
                v = self._victim2(date)
                if v is None:
                    continue
                vsym, vpx, vpnl, vskor, vq = v
                if vq is not None and qscore < g["margin"] * vq:
                    continue                               # %20 kalite marjı yok → dokunma
                vpos = self.positions[vsym]
                proceeds = vpos.shares * vpx * (1 - self._stop_slip) - cfg.commission_per_trade
                if self.cash + proceeds < self._size(date):
                    continue                               # boşa kurban verme
                self._close(vsym, date, vpx, "GIL2", slip=self._stop_slip)
                self.gil2_log.append({"t": str(date)[:10], "victim": vsym, "star": sym,
                                      "v_pnl": round(vpnl, 1), "v_skor": round(vskor, 3),
                                      "v_q": vq, "s_q": qscore})
                if self._slot_count() < cfg.max_positions and self.cash >= self._size(date):
                    if self._open(sym, date, row, plan, total):
                        self.positions[sym]._qscore = qscore
        self._append_curves(date)

    def _append_curves(self, date):
        eq = self._equity(date)
        self.equity_curve.append((date, eq))
        self.util_curve.append((date, (1.0 - self.cash / eq) if eq else 0.0))
        self.slot_curve.append((date, self._slot_count() / self.cfg.max_positions))


# ---------------------------------------------------------------- metrikler
def run_one(sd="2021-05-01", ed="", gil2=None, vixk=None, label=""):
    ag.load_data()
    c = copy.deepcopy(ag.base_cfg()); c.start_date = sd; c.end_date = ed
    TKX.GIL2 = gil2; TKX.VIXK = vixk; TKX.VIX = load_vix() if vixk else None
    TKX.GIL = None; TKX.RSX = None; TKX.VOLK = None      # üst sınıf kuralları kapalı
    bt = TKX(c, market=ag.MARKET); bt.run()
    m = bt.metrics()
    eqs = pd.Series({d: e for d, e in bt.equity_curve})
    years = (eqs.index[-1] - eqs.index[0]).days / 365.25
    sells = sum(t.exit * t.shares for t in bt.trades)
    row = {"label": label, "roi": round(m["roi"], 1), "max_dd": round(m["max_dd"], 1),
           "pf": round(m["profit_factor"], 2), "trades": m["trades"],
           "turnover_yil": round(sells / eqs.mean() / years, 2),
           "slot_doluluk": round(float(np.mean([v for _, v in bt.slot_curve])) * 100, 1),
           "util_med": round(pd.Series([u for _, u in bt.util_curve]).median() * 100, 1),
           "gil2_n": len(bt.gil2_log), "vix_n": len(bt.vix_log)}
    print("  %-14s roi %+7.1f · dd %6.1f · pf %5.2f · n %4d · turnover %.2f/y · "
          "slot %%%.1f · gil2 %d · vix %d" %
          (label, row["roi"], row["max_dd"], row["pf"], row["trades"],
           row["turnover_yil"], row["slot_doluluk"], row["gil2_n"], row["vix_n"]), flush=True)
    return row, bt


def fwd_ret(sym, t, h=63):
    df = ag.MARKET["data"].get(sym)
    if df is None:
        return np.nan
    idx = df.index; ts = pd.Timestamp(t)
    i = idx.searchsorted(ts)
    if i >= len(idx) or idx[i] != ts or i + h >= len(idx):
        return np.nan
    return float((df["Close"].iloc[i + h] / df["Close"].iloc[i] - 1) * 100)


def rotation_edge(log, star_key="star", victim_key="victim", h=63):
    """Olay başına: yıldızın ileri getirisi − kurbanın ileri getirisi (yüzde puan)."""
    diffs = []
    for e in log:
        if not e.get(victim_key):
            continue
        a, b = fwd_ret(e[star_key], e["t"], h), fwd_ret(e[victim_key], e["t"], h)
        if a == a and b == b:
            diffs.append(a - b)
    if not diffs:
        return {"n": 0}
    ser = pd.Series(diffs)
    return {"n": len(ser), "ort": round(float(ser.mean()), 1),
            "medyan": round(float(ser.median()), 1),
            "pozitif_pct": round(float((ser > 0).mean() * 100), 0)}


# ---------------------------------------------------------------- selftest
def selftest():
    bt = object.__new__(TKX)
    bt.cfg = s.Config(); bt.cfg.max_positions = 20; bt.cfg.free_runner_slots = True
    bt.GIL2 = {"qmin": 90, "margin": 1.2, "losers_only": False, "min_age": 5}

    class P:  # sahte pozisyon
        def __init__(self, entry, bars, q, a_alive=True):
            self.entry = entry; self._bars = bars; self._qscore = q
            self.legs = [{"tag": "A", "shares": 1.0 if a_alive else 0.0, "rule": "target"},
                         {"tag": "B", "shares": 1.0, "rule": "ema21"}]
            self.entry_date = pd.Timestamp("2020-01-01"); self.shares = 2.0

    d = pd.Timestamp("2024-01-10")
    idx = pd.DatetimeIndex([d])
    def mkdf(close): return pd.DataFrame({"Close": [close]}, index=idx)

    # 1) derin zarar + yaşlı > küçük zarar + genç
    bt.positions = {"ESKI": P(100, 60, 70), "YENI": P(100, 6, 70)}
    bt.data = {"ESKI": mkdf(80.0), "YENI": mkdf(95.0)}
    v = bt._victim2(d); assert v[0] == "ESKI", v
    # 2) kârda ama ÇOK yaşlı pozisyon, formülde kurban OLABİLİR (süre×0.4)
    bt.positions = {"KARLI": P(100, 60, 70), "GENC": P(100, 6, 70)}
    bt.data = {"KARLI": mkdf(120.0), "GENC": mkdf(99.0)}
    v = bt._victim2(d); assert v[0] == "KARLI", v          # 0.4 > 0.6*0.01+0.04
    # 3) losers_only=True kârlıyı korur
    bt.GIL2 = dict(bt.GIL2, losers_only=True)
    v = bt._victim2(d); assert v[0] == "GENC", v
    # 4) runner-only (A bacağı kapalı) slot açmaz → kurban OLAMAZ
    bt.GIL2 = dict(bt.GIL2, losers_only=False)
    bt.positions = {"RUNNER": P(100, 60, 70, a_alive=False), "GENC": P(100, 6, 70)}
    bt.data = {"RUNNER": mkdf(80.0), "GENC": mkdf(99.0)}
    v = bt._victim2(d); assert v[0] == "GENC", v
    # 5) min_age koruması
    bt.positions = {"BEBEK": P(100, 3, 70)}
    bt.data = {"BEBEK": mkdf(50.0)}
    assert bt._victim2(d) is None
    # 6) VIX sıçrama hesabı
    vser = pd.Series([20.0, 26.0], index=pd.DatetimeIndex(["2024-01-09", "2024-01-10"]))
    assert float(vser.pct_change().iloc[-1]) >= 0.25
    print("selftest: 6/6 OK", flush=True)


# ---------------------------------------------------------------- akış
def fidelity():
    """Kurallar kapalıyken 5 pencerede batarya EXPECTED ile birebir — sadakat kanıtı."""
    ag.load_data()
    ok = True
    for (wn, sd, ed), (eroi, en) in zip(ag.WINS, ag.EXPECTED):
        row, _ = run_one(sd, ed, gil2=None, vixk=None, label=f"baz/{wn}")
        good = abs(row["roi"] - eroi) < 0.1 and row["trades"] == en
        ok &= good
        if not good:
            print(f"  ⚠️ SADAKAT KIRIK: {wn} beklenen ({eroi},{en})", flush=True)
    print("SADAKAT:", "5/5 OK" if ok else "KIRIK — SONUÇLAR GEÇERSİZ", flush=True)
    return ok


def main_runs(res):
    print("— ana koşular (5y tam) —", flush=True)
    variants = [
        ("baz", None, None),
        ("gil2-spec", {"qmin": 90, "margin": 1.2, "losers_only": False, "min_age": 5}, None),
        ("gil2-zarar", {"qmin": 90, "margin": 1.2, "losers_only": True, "min_age": 5}, None),
        ("vix25", None, 0.25),
        ("gil2+vix", {"qmin": 90, "margin": 1.2, "losers_only": False, "min_age": 5}, 0.25),
    ]
    curves = {}
    for label, g, v in variants:
        row, bt = run_one(gil2=g, vixk=v, label=label)
        res["main"][label] = row
        curves[label] = [(str(d)[:10], e) for d, e in bt.equity_curve]
        if label == "baz":
            res["firsat_baz"] = {"kacan_yildiz_n": len(bt.missed_log),
                                 "rotasyon_63g": rotation_edge(bt.missed_log)}
        if g is not None and bt.gil2_log:
            res["main"][label]["rotasyon_63g"] = rotation_edge(bt.gil2_log)
            res["main"][label]["kurban_pnl_medyan"] = round(
                float(pd.Series([e["v_pnl"] for e in bt.gil2_log]).median()), 1)
        if v is not None and bt.vix_log:
            res["main"][label]["vix_gunleri"] = bt.vix_log
    res["_curves"] = curves


def jitter(res):
    print("— jitter (5 başlangıç × baz/gil2-spec) —", flush=True)
    out = []
    for sd in JITTER_STARTS:
        b, _ = run_one(sd=sd, label=f"baz@{sd[5:]}")
        g, _ = run_one(sd=sd, gil2={"qmin": 90, "margin": 1.2, "losers_only": False,
                                    "min_age": 5}, label=f"gil2@{sd[5:]}")
        out.append({"start": sd, "baz_roi": b["roi"], "gil2_roi": g["roi"],
                    "fark": round(g["roi"] - b["roi"], 1)})
    res["jitter"] = out
    wins = sum(1 for r in out if r["fark"] > 0)
    print(f"  jitter özeti: gil2 {wins}/{len(out)} başlangıçta önde", flush=True)


def make_png(res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 5.5), facecolor="#0d1117")
    ax.set_facecolor("#0d1117")
    cols = {"baz": "#8b949e", "gil2-spec": "#d29922", "gil2-zarar": "#c98500",
            "vix25": "#58a6ff", "gil2+vix": "#3fb950"}
    for label, curve in res["_curves"].items():
        d = [pd.Timestamp(x) for x, _ in curve]
        e0 = curve[0][1]
        ax.plot(d, [e / e0 * 100 for _, e in curve], label=label,
                color=cols.get(label, "#fff"), lw=1.4)
    ax.legend(facecolor="#161b22", labelcolor="#e6edf3", edgecolor="#30363d")
    ax.set_title("Sermaye Tahsisi Deneyi — 5y kümülatif (100=başlangıç)", color="#e6edf3")
    ax.tick_params(colors="#8b949e")
    for sp in ax.spines.values():
        sp.set_color("#30363d")
    ax.grid(alpha=0.15)
    fig.tight_layout(); fig.savefig(OUT_PNG, dpi=110)
    print(f"grafik: {OUT_PNG}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fidelity", action="store_true")
    ap.add_argument("--main", action="store_true", dest="mainr")
    ap.add_argument("--jitter", action="store_true")
    args = ap.parse_args()
    hepsi = not (args.selftest or args.fidelity or args.mainr or args.jitter)

    if args.selftest or hepsi:
        selftest()
    res = {"main": {}}
    if args.fidelity or hepsi:
        if not fidelity():
            sys.exit("sadakat kırık — dur")
    if args.mainr or hepsi:
        main_runs(res)
    if args.jitter or hepsi:
        jitter(res)
    if res["main"]:
        make_png(res)
        curves = res.pop("_curves", None)
        with open(OUT_JSON, "w") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        print(f"kayıt: {OUT_JSON}", flush=True)


if __name__ == "__main__":
    main()

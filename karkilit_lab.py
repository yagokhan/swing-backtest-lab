#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""karkilit_lab.py — KÂR-ŞARTLI KORUMA (2026-07-09).

Splitstop (07-07) A bacağına KOŞULSUZ stopların kaybettirdiğini göstermişti. Bu lab
FARKLI bir soruyu test eder: pozisyon belirli KÂRA geçtikten SONRA (arm eşiği, ör. +15%)
devreye giren break-even ya da trailing stop kârı korur mu?

Yapısal not: A bacağı +2R'de (~+%8-12) satıldığından +15% tetiği fiilen RUNNER (B/EMA21)
bacağının konusudur — B bacağı +%50 yapıp EMA21 kesişimine kadar geri verebilir (TER örneği).
Koruma KAPANIŞ-bazlıdır (EMA21 kuralıyla aynı semantik): armed olduktan sonra
  BE   : Close < giriş → kapanıştan çık
  TRAIL: Close < zirve-kapanış×(1−t%) → kapanıştan çık  (zirve = arm SONRASI en yüksek kapanış;
         bu barın kapanışı bir SONRAKİ barın kararına girer — aynı-bar artefaktı yok)
EMA21 kuralı AYNEN aktif kalır; hangisi önce tetiklerse o çıkar.

SADAKAT: PROT=None iken batarya EXPECTED ile 5/5 birebir (KKX yalnız _split_leg_exit
passthrough'u genişletir, _step'e dokunmaz).
Kullanım: python3 karkilit_lab.py [--selftest|--fidelity|--grid|--jitter|--all]
"""
import argparse
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

OUT_JSON = "/home/gokhan/swing2_out/karkilit_results.json"
# tahsis_lab jitter'ından bilinen baz ROI'ler (aynı sabit cache + aynı başlangıçlar)
JITTER_STARTS = ["2021-05-01", "2021-05-08", "2021-05-15", "2021-05-22", "2021-06-01"]
BAZ_JITTER = {"2021-05-01": 166.3, "2021-05-08": 166.3, "2021-05-15": 178.9,
              "2021-05-22": 146.9, "2021-06-01": 173.1}


class KKX(ag.GKX):
    """Aday 3 kopyası + kâr-şartlı bacak koruması. GIL/RSX/VOLK hep None."""
    PROT = None   # None | dict(scope='B'|'A', arm=15.0, mode='be'|'trail', trail=10.0)

    def _split_leg_exit(self, leg, pos, row):
        res = super()._split_leg_exit(leg, pos, row)
        P = self.PROT
        if P is None:
            return res
        if leg["rule"] != ("ema21" if P["scope"] == "B" else "target"):
            return res
        close = row["Close"]
        if pd.isna(close):
            return res
        close = float(close)
        out = res
        if out is None and leg.get("_armed"):              # baz kural öncelikli
            if P["mode"] == "be":
                if close < pos.entry:
                    out = (close, "BE", True)
            else:
                stop = leg["_pk"] * (1.0 - P["trail"] / 100.0)
                if close < stop:
                    out = (close, "TRL%g" % P["trail"], True)
        # durum güncelle — bu barın kapanışı SONRAKİ barın kararına girer
        if not leg.get("_armed"):
            if close >= pos.entry * (1.0 + P["arm"] / 100.0):
                leg["_armed"] = True
                leg["_pk"] = close
        else:
            leg["_pk"] = max(leg.get("_pk", close), close)
        return out


# ---------------------------------------------------------------- koşu + metrik
def run_one(prot=None, sd="2021-05-01", ed="", label=""):
    ag.load_data()
    c = copy.deepcopy(ag.base_cfg()); c.start_date = sd; c.end_date = ed
    KKX.PROT = prot
    KKX.GIL = None; KKX.RSX = None; KKX.VOLK = None
    bt = KKX(c, market=ag.MARKET); bt.run()
    m = bt.metrics()
    prot_tr = [t for t in bt.trades if t.outcome.split(":")[-1].startswith(("TRL", "BE"))]
    row = {"label": label, "roi": round(m["roi"], 1), "max_dd": round(m["max_dd"], 1),
           "pf": round(m["profit_factor"], 2), "trades": m["trades"],
           "prot_n": len(prot_tr),
           "prot_med_pnl": round(float(pd.Series([t.pnl_pct for t in prot_tr]).median()), 1)
                           if prot_tr else None}
    print("  %-16s roi %+7.1f · dd %6.1f · pf %5.2f · n %4d · koruma-çıkışı %3d (medyan %s%%)" %
          (label, row["roi"], row["max_dd"], row["pf"], row["trades"],
           row["prot_n"], row["prot_med_pnl"]), flush=True)
    return row


# ---------------------------------------------------------------- selftest
def selftest():
    bt = object.__new__(KKX)
    bt.cfg = s.Config()

    class Pos:
        entry = 100.0; risk0 = 5.0
    pos = Pos()

    def row(close, ema21=1.0, high=None):   # ema21 çok düşük → EMA kuralı tetiklemez
        return pd.Series({"Close": close, "High": high if high else close,
                          "Open": close, "ATR": 1.0, "EMA21": ema21})

    # 1) arm olmadan derin düşüş → koruma TETİKLEMEZ (stopsuzluk korunur)
    bt.PROT = {"scope": "B", "arm": 15.0, "mode": "trail", "trail": 10.0}
    leg = {"tag": "B", "rule": "ema21", "param": 0, "shares": 1.0, "cost": 100.0, "peak": 100.0}
    assert bt._split_leg_exit(leg, pos, row(60.0)) is None and not leg.get("_armed")
    # 2) +15 kapanış → arm; aynı bar stop YOK
    assert bt._split_leg_exit(leg, pos, row(115.0)) is None and leg["_armed"] and leg["_pk"] == 115.0
    # 3) zirve 130'a, sonra 116 kapanış (<130×0.9=117) → TRL
    assert bt._split_leg_exit(leg, pos, row(130.0)) is None
    r = bt._split_leg_exit(leg, pos, row(116.0))
    assert r is not None and r[1] == "TRL10" and r[0] == 116.0, r
    # 4) EMA21 önceliği: kapanış EMA21 altındaysa etiket EMA
    leg2 = {"tag": "B", "rule": "ema21", "param": 0, "shares": 1.0, "cost": 100.0,
            "peak": 100.0, "_armed": True, "_pk": 130.0}
    r = bt._split_leg_exit(leg2, pos, row(116.0, ema21=120.0))
    assert r is not None and r[1] == "EMA21", r
    # 5) BE: armed sonra girişin altına kapanış → BE
    bt.PROT = {"scope": "B", "arm": 10.0, "mode": "be"}
    leg3 = {"tag": "B", "rule": "ema21", "param": 0, "shares": 1.0, "cost": 100.0,
            "peak": 100.0, "_armed": True, "_pk": 112.0}
    r = bt._split_leg_exit(leg3, pos, row(99.0))
    assert r is not None and r[1] == "BE", r
    # 6) A-scope: +2R limit önceliği (High hedefe değdi) → +2R etiketi
    bt.PROT = {"scope": "A", "arm": 8.0, "mode": "be"}
    legA = {"tag": "A", "rule": "target", "param": 2.0, "shares": 1.0, "cost": 100.0,
            "peak": 100.0, "_armed": True, "_pk": 109.0}
    r = bt._split_leg_exit(legA, pos, row(105.0, high=111.0))
    assert r is not None and r[1] == "+2R", r
    print("selftest: 6/6 OK", flush=True)


# ---------------------------------------------------------------- akış
def fidelity():
    ag.load_data()
    ok = True
    for (wn, sd, ed), (eroi, en) in zip(ag.WINS, ag.EXPECTED):
        r = run_one(None, sd, ed, label=f"baz/{wn}")
        ok &= abs(r["roi"] - eroi) < 0.1 and r["trades"] == en
    print("SADAKAT:", "5/5 OK" if ok else "KIRIK — SONUÇLAR GEÇERSİZ", flush=True)
    return ok


def grid(res):
    print("— grid (5y tam) — baz +166.3 referans —", flush=True)
    variants = []
    for arm in (10, 15, 20):
        for tr in (6, 10, 15):
            variants.append((f"B-arm{arm}-trl{tr}",
                             {"scope": "B", "arm": arm, "mode": "trail", "trail": tr}))
    variants += [("B-arm10-BE", {"scope": "B", "arm": 10, "mode": "be"}),
                 ("B-arm15-BE", {"scope": "B", "arm": 15, "mode": "be"}),
                 ("A-arm8-BE",  {"scope": "A", "arm": 8, "mode": "be"})]
    for label, p in variants:
        res["grid"][label] = run_one(p, label=label)
        res["grid"][label]["prot"] = p


def jitter(res, best_label):
    p = res["grid"][best_label]["prot"]
    print(f"— jitter ({best_label}) —", flush=True)
    out = []
    for sd in JITTER_STARTS:
        r = run_one(p, sd=sd, label=f"{best_label}@{sd[5:]}")
        out.append({"start": sd, "baz_roi": BAZ_JITTER[sd], "prot_roi": r["roi"],
                    "fark": round(r["roi"] - BAZ_JITTER[sd], 1)})
    res["jitter"] = {best_label: out}
    wins = sum(1 for r in out if r["fark"] > 0)
    print(f"  jitter özeti: {wins}/{len(out)} başlangıçta önde", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fidelity", action="store_true")
    ap.add_argument("--grid", action="store_true", dest="gridr")
    ap.add_argument("--jitter", action="store_true")
    args = ap.parse_args()
    hepsi = not (args.selftest or args.fidelity or args.gridr or args.jitter)

    if args.selftest or hepsi:
        selftest()
    res = {"grid": {}}
    if args.fidelity or hepsi:
        if not fidelity():
            sys.exit("sadakat kırık — dur")
    if args.gridr or hepsi:
        grid(res)
        best = max(res["grid"], key=lambda k: res["grid"][k]["roi"])
        print(f"en iyi varyant: {best} (roi {res['grid'][best]['roi']})", flush=True)
        if args.jitter or hepsi:
            jitter(res, best)
        with open(OUT_JSON, "w") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        print(f"kayıt: {OUT_JSON}", flush=True)


if __name__ == "__main__":
    main()

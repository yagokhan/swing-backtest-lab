#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
📏 DENEY 2 — SÜREKLİ HEDEF + RUNNER UFKU (spec: 2026-07-09-ml-uc-deney-design.md).

İkili "sahte/gerçek" yerine 21g ve 63g İLERİ TOPLAM GETİRİ regresyonu; metrik AUC değil
Spearman IC (havuz + günlük kesit). Tabanlar: blend10 (canlı sıralama formülü, motorla
birebir yeniden üretilir) ve rs_scan. Purge hedef ufkuna göre ölçekli (21g→35, 63g→95
takvim günü) — ileri-bakan hedefin test dönemine taşmasını keser.

Ayrıca ortak veri kümesini `~/.swing_ml/lab_dataset.pkl`'e cache'ler (deney 1/3 de kullanır).
Kullanım: python3 ml_horizon_lab.py [--rebuild]
"""
import argparse
import json
import os
import pickle
from collections import OrderedDict
from datetime import datetime

import numpy as np
import pandas as pd

import ml_backfill as bf
import ml_feature_lab as fl
import ml_shadow_report as m
import swing2_backtest as s

DATASET = os.path.join(m.ML_DIR, "lab_dataset.pkl")
HORIZONS = OrderedDict([("fwd21", 21), ("fwd63", 63)])
PURGE = {"fwd21": 35, "fwd63": 95}          # takvim günü; ufuk + pay
ALL_FEATS = m.FEATURES + fl.F_VCP + fl.F_SEC + fl.F_CAT + fl.F_I2H + fl.F_H5   # 22
REG_PARAMS = dict(n_estimators=300, max_depth=3, learning_rate=0.05,
                  subsample=0.8, colsample_bytree=0.8)


# ---------------------------------------------------------------- veri kümesi
def add_blend10(df, frames):
    """Canlı sıralama skoru (Aday 3 'denge karışımı') — motor formülüyle birebir:
    qscore(rs, 52H-yakınlık, tazelik, risk)/100 + ATR%/10."""
    hi52c, s20c = {}, {}
    vals = []
    for r in df.itertuples():
        f = frames.get(r.symbol)
        if f is None:
            vals.append(np.nan); continue
        if r.symbol not in hi52c:
            hi52c[r.symbol] = f["High"].rolling(252).max()
            s20c[r.symbol] = f["Close"].rolling(20).mean()
        past = f[f.index <= r.asof_ts]
        if past.empty:
            vals.append(np.nan); continue
        ts = past.index[-1]
        c0 = float(f["Close"].loc[ts])
        h52, s20 = hi52c[r.symbol].loc[ts], s20c[r.symbol].loc[ts]
        rec = {"rs": (r.rs_scan if r.rs_scan == r.rs_scan else 0.0),
               "dist_52h_pct": (c0 / h52 - 1) * 100 if h52 == h52 else None,
               "dist_sma20_pct": (c0 - s20) / s20 * 100 if s20 == s20 else None,
               "risk_pct": (r.risk_pct if r.risk_pct == r.risk_pct else None)}
        q, _ = s._qswing_priority_score(rec)
        atrp = r.atr_pct / 10.0 if r.atr_pct == r.atr_pct else 0.0
        vals.append(q / 100.0 + atrp)
    df["blend10"] = vals
    return df


def add_forward(df, frames):
    """Ham depo kapanışından ileri getiriler (%); ufuk dolmadıysa NaN."""
    out = {k: [] for k in HORIZONS}
    for r in df.itertuples():
        f = frames.get(r.symbol)
        vals = dict.fromkeys(HORIZONS, np.nan)
        if f is not None:
            idx = f.index
            i = idx.searchsorted(r.asof_ts)
            if i < len(idx) and idx[i] == r.asof_ts:
                c = f["Close"]
                for k, h in HORIZONS.items():
                    if i + h < len(idx):
                        vals[k] = float((c.iloc[i + h] / c.iloc[i] - 1) * 100)
        for k in HORIZONS:
            out[k].append(vals[k])
    for k in HORIZONS:
        df[k] = out[k]
    return df


def load_dataset(rebuild=False):
    """Gölge günlüğü + 22 özellik (cache'lerden) + blend10 + ileri getiriler; pkl cache."""
    if not rebuild and os.path.exists(DATASET):
        with open(DATASET, "rb") as fh:
            return pickle.load(fh)
    rows = m._read_log()                      # etiket ŞART DEĞİL (hedef = ileri getiri)
    df = pd.DataFrame(rows)
    df["asof_ts"] = pd.to_datetime(df["asof"])
    for c in m.FEATURES + ["label"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    frames = m.load_frames()
    df = fl.enrich(df, frames)
    df = fl.intraday_lite(df)
    df = fl.hourly_struct(df, frames)
    df = add_blend10(df, frames)
    df = add_forward(df, frames)
    with open(DATASET, "wb") as fh:
        pickle.dump(df, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return df


# ---------------------------------------------------------------- metrikler
def spearman(a, b):
    d = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(d) < 10:
        return np.nan
    return float(d["a"].corr(d["b"], method="spearman"))


def daily_ic(te, pred_col, ycol):
    """Gün-içi (kesit) Spearman ortalaması — yalnız ≥2 adaylı günler."""
    ics = []
    for _, g in te.groupby("asof"):
        g = g[[pred_col, ycol]].dropna()
        if len(g) < 2:
            continue
        v = g[pred_col].corr(g[ycol], method="spearman")
        if v == v:
            ics.append(float(v))
    return (float(np.mean(ics)), len(ics)) if ics else (np.nan, 0)


def folds(df, purge_days):
    cuts = bf.FOLD_CUTS
    for i, cut in enumerate(cuts):
        c = pd.Timestamp(cut)
        e = pd.Timestamp(cuts[i + 1]) if i + 1 < len(cuts) else pd.Timestamp("2099-01-01")
        tr = df[df["asof_ts"] < c - pd.Timedelta(days=purge_days)]
        te = df[(df["asof_ts"] >= c) & (df["asof_ts"] < e)]
        if len(tr) >= 200 and len(te) >= 50:
            yield cut, tr, te


# ---------------------------------------------------------------- deney
def run(df):
    from xgboost import XGBRegressor
    results = OrderedDict()
    for tgt, h in HORIZONS.items():
        rows = []
        for cut, tr, te in folds(df, PURGE[tgt]):
            trv = tr.dropna(subset=[tgt])
            tev = te.dropna(subset=[tgt])
            if len(trv) < 200 or len(tev) < 50:
                continue
            mod = XGBRegressor(**REG_PARAMS)
            mod.fit(trv[ALL_FEATS].astype(float), trv[tgt].astype(float))
            tev = tev.copy()
            tev["pred"] = mod.predict(tev[ALL_FEATS].astype(float))
            row = {"cut": cut, "n": len(tev),
                   "ic_ml": round(spearman(tev["pred"], tev[tgt]), 3),
                   "ic_blend": round(spearman(tev["blend10"], tev[tgt]), 3),
                   "ic_rs": round(spearman(tev["rs_scan"], tev[tgt]), 3)}
            d_ml, nd = daily_ic(tev, "pred", tgt)
            d_bl, _ = daily_ic(tev, "blend10", tgt)
            row.update({"dic_ml": round(d_ml, 3), "dic_blend": round(d_bl, 3), "n_gun": nd})
            rows.append(row)
        results[tgt] = rows
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="lab_dataset.pkl'i yeniden kur")
    args = ap.parse_args()

    df = load_dataset(rebuild=args.rebuild)
    n_f = {k: int(df[k].notna().sum()) for k in HORIZONS}
    print(f"• veri: {len(df)} aday-gün · hedef doluluğu {n_f} · blend10 doluluk "
          f"%{df['blend10'].notna().mean()*100:.0f}", flush=True)

    results = run(df)
    for tgt, rows in results.items():
        print(f"\n═══ {tgt} (purge {PURGE[tgt]}g) — havuz IC · günlük-kesit IC ═══")
        print(f"{'kesim':10s} {'n':>5s}  {'ML':>6s} {'blend':>6s} {'rs':>6s} │ {'gML':>6s} {'gBlend':>6s} {'gün':>4s}")
        for r in rows:
            print(f"{r['cut']:10s} {r['n']:5d}  {r['ic_ml']:6.3f} {r['ic_blend']:6.3f} "
                  f"{r['ic_rs']:6.3f} │ {r['dic_ml']:6.3f} {r['dic_blend']:6.3f} {r['n_gun']:4d}")
        mean = {k: round(float(np.nanmean([r[k] for r in rows])), 3)
                for k in ("ic_ml", "ic_blend", "ic_rs", "dic_ml", "dic_blend")}
        print(f"{'ORT':10s} {'':5s}  {mean['ic_ml']:6.3f} {mean['ic_blend']:6.3f} "
              f"{mean['ic_rs']:6.3f} │ {mean['dic_ml']:6.3f} {mean['dic_blend']:6.3f}")

    mt = json.load(open(m.META_PATH)) if os.path.exists(m.META_PATH) else {}
    mt["horizon_lab"] = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                         "purge": PURGE, "results": results}
    json.dump(mt, open(m.META_PATH, "w"), ensure_ascii=False, indent=1)
    print(f"\nkayıt: {m.META_PATH} → horizon_lab")


if __name__ == "__main__":
    main()

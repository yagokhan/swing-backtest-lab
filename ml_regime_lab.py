#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌡️ DENEY 3 — REJİM SEVİYESİ SAHTE-ORAN (spec: 2026-07-09-ml-uc-deney-design.md).

Soru: tek tek sinyaller yerine "bu haftaki kırılımların TOPLAM sahte-oranı" öngörülebilir mi?
Hedef: haftalık sahte-oran (≥3 etiketli sinyalli haftalar). Girdiler hafta başında bilinenler:
A200 (seviye + 4h Δ), SPY/SMA200 mesafesi, SPY 20g gerçekleşen vol, SPY 63g getirisi ve —
etiket 15 iş günü gecikmeli çözüldüğünden — YALNIZ ≥4 hafta önceki gerçekleşen oranların
ortalaması (daha yakını sızıntı). Modeller: Ridge + küçük XGB. TABANLAR: eğitim-ortalaması
ve gecikmeli-4h ortalamasının kendisi. Başarı = tabanı zaman-sıralı WF'de tutarlı geçmek.
"""
import json
import os
from collections import OrderedDict
from datetime import datetime

import numpy as np
import pandas as pd

import ml_backfill as bf
import ml_feature_lab as fl
import ml_shadow_report as m
import qulla_paper as qp

MIN_SIG = 3          # haftada en az bu kadar etiketli sinyal
LAG_W = 4            # girdi olarak kullanılabilecek en yakın geçmiş oran (hafta)
PURGE_DAYS = 28
FEATS = ["a200", "a200_d4w", "spy_dist200", "spy_vol20", "spy_ret63", "lag_rate"]


def weekly_table():
    """Hafta → (sahte-oran, n) + hafta başı rejim girdileri."""
    lab = [r for r in m._read_log() if r["label"] != ""]
    df = pd.DataFrame(lab)
    df["asof_ts"] = pd.to_datetime(df["asof"])
    df["label"] = pd.to_numeric(df["label"])
    df["wk"] = df["asof_ts"].dt.to_period("W-SUN").dt.start_time   # Pzt başlangıçlı hafta
    wk = df.groupby("wk").agg(rate=("label", "mean"), n=("label", "size")).reset_index()
    wk = wk[wk["n"] >= MIN_SIG].sort_values("wk").reset_index(drop=True)

    frames = m.load_frames()
    spy = frames["SPY"]["Close"]
    sma200 = spy.rolling(200).mean()
    vol20 = spy.pct_change().rolling(20).std() * np.sqrt(252) * 100
    ret63 = (spy / spy.shift(63) - 1) * 100
    uni = set(qp.POOL)
    a200 = pd.DataFrame({t: (f["Close"] > f["Close"].rolling(200).mean()).astype(float)
                         for t, f in frames.items() if t in uni}).mean(axis=1) * 100

    rows = []
    hist = wk.set_index("wk")["rate"]
    for r in wk.itertuples():
        t0 = r.wk - pd.Timedelta(days=1)          # hafta başından önceki son bilgi
        past = hist[hist.index <= r.wk - pd.Timedelta(weeks=LAG_W)]
        rows.append({
            "wk": r.wk, "rate": r.rate, "n": r.n,
            "a200": a200.asof(t0),
            "a200_d4w": a200.asof(t0) - a200.asof(t0 - pd.Timedelta(weeks=4)),
            "spy_dist200": (spy.asof(t0) / sma200.asof(t0) - 1) * 100,
            "spy_vol20": vol20.asof(t0),
            "spy_ret63": ret63.asof(t0),
            "lag_rate": float(past.tail(LAG_W).mean()) if len(past) >= 2 else np.nan,
        })
    return pd.DataFrame(rows).dropna(subset=FEATS)


def run(w):
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    from xgboost import XGBRegressor

    def preds(tr, te):
        out = {"taban_ort": np.full(len(te), tr["rate"].mean()),
               "taban_lag": te["lag_rate"].values}
        ridge = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        ridge.fit(tr[FEATS], tr["rate"])
        out["ridge"] = ridge.predict(te[FEATS])
        xgb = XGBRegressor(n_estimators=150, max_depth=2, learning_rate=0.05,
                           subsample=0.8, colsample_bytree=0.8)
        xgb.fit(tr[FEATS], tr["rate"])
        out["xgb"] = xgb.predict(te[FEATS])
        return out

    models = ("taban_ort", "taban_lag", "ridge", "xgb")
    rows = []
    for i, cut in enumerate(bf.FOLD_CUTS):
        c = pd.Timestamp(cut)
        e = pd.Timestamp(bf.FOLD_CUTS[i + 1]) if i + 1 < len(bf.FOLD_CUTS) else pd.Timestamp("2099-01-01")
        tr = w[w["wk"] < c - pd.Timedelta(days=PURGE_DAYS)]
        te = w[(w["wk"] >= c) & (w["wk"] < e)]
        if len(tr) < 30 or len(te) < 8:
            continue
        p = preds(tr, te)
        y = te["rate"].values
        row = {"cut": cut, "n_hafta": len(te)}
        for k in models:
            row[f"mae_{k}"] = round(float(np.mean(np.abs(p[k] - y))), 3)
            sp = pd.Series(p[k]).corr(pd.Series(y), method="spearman")
            row[f"sp_{k}"] = round(float(sp), 3) if sp == sp else np.nan
        rows.append(row)
    return rows, models


def main():
    w = weekly_table()
    print(f"• haftalık örneklem: {len(w)} hafta ({w['wk'].min().date()} → {w['wk'].max().date()}) · "
          f"oran ort %{w['rate'].mean()*100:.0f} · std {w['rate'].std():.3f}", flush=True)

    rows, models = run(w)
    print(f"\n═══ haftalık sahte-oran tahmini — MAE (↓ iyi) · Spearman (↑ iyi) ═══")
    hdr = f"{'kesim':10s} {'hf':>3s}  " + "  ".join(f"{k:>9s}" for k in models)
    print(hdr + "   │  " + "  ".join(f"{k:>9s}" for k in models))
    for r in rows:
        print(f"{r['cut']:10s} {r['n_hafta']:3d}  "
              + "  ".join(f"{r['mae_'+k]:9.3f}" for k in models) + "   │  "
              + "  ".join(f"{(r['sp_'+k] if r['sp_'+k]==r['sp_'+k] else float('nan')):9.3f}" for k in models))
    mean = {f"{p}_{k}": round(float(np.nanmean([r[f"{p}_{k}"] for r in rows])), 3)
            for p in ("mae", "sp") for k in models}
    print(f"{'ORT':10s} {'':3s}  " + "  ".join(f"{mean['mae_'+k]:9.3f}" for k in models)
          + "   │  " + "  ".join(f"{mean['sp_'+k]:9.3f}" for k in models))

    mt = json.load(open(m.META_PATH)) if os.path.exists(m.META_PATH) else {}
    mt["regime_lab"] = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "n_hafta": len(w), "min_sinyal": MIN_SIG, "lag_hafta": LAG_W,
                        "folds": rows, "ortalama": mean, "features": FEATS}
    json.dump(mt, open(m.META_PATH, "w"), ensure_ascii=False, indent=1)
    print(f"\nkayıt: {m.META_PATH} → regime_lab")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🥇 DENEY 1 / AŞAMA 1 — GÜN-İÇİ KESİTSEL SIRALAMA (spec: 2026-07-09-ml-uc-deney-design.md).

Soru: kalabalık günde (≥2 aday) ML, canlı blend10 sıralamasından DAHA İYİ sıralayabiliyor mu?
Metrik: gün-içi Spearman IC (fwd21 ve fwd63'e karşı). İki ML varyantı:
  reg  = XGBRegressor (deney 2 ile aynı; tahmin gün içinde sıralanır)
  rank = XGBRanker (rank:pairwise, grup = gün)
KAPI (Aşama 2 batarya için): ML, blend10'u fold'ların ≥3/4'ünde geçecek VE gün-eşleştirmeli
ortalama fark > 1 SE olacak. Geçemezse DUR — batarya koşulmaz, rapor yazılır.
"""
import json
import os
from collections import OrderedDict
from datetime import datetime

import numpy as np
import pandas as pd

import ml_backfill as bf
import ml_horizon_lab as hl
import ml_shadow_report as m

GATE_MIN_FOLD_WINS = 3   # /4


def day_ics(te, pred_col, tgt):
    """Kalabalık günlerde gün-içi Spearman listesi (gün → IC)."""
    out = {}
    for day, g in te.groupby("asof"):
        g = g[[pred_col, tgt]].dropna()
        if len(g) < 2:
            continue
        v = g[pred_col].corr(g[tgt], method="spearman")
        if v == v:
            out[day] = float(v)
    return out


def fit_reg(tr, tgt):
    from xgboost import XGBRegressor
    mod = XGBRegressor(**hl.REG_PARAMS)
    mod.fit(tr[hl.ALL_FEATS].astype(float), tr[tgt].astype(float))
    return mod


def fit_ranker(tr, tgt):
    from xgboost import XGBRanker
    tr = tr.sort_values("asof")
    groups = tr.groupby("asof", sort=False).size().values
    mod = XGBRanker(objective="rank:pairwise", n_estimators=300, max_depth=3,
                    learning_rate=0.05, subsample=0.8, colsample_bytree=0.8)
    mod.fit(tr[hl.ALL_FEATS].astype(float), tr[tgt].astype(float), group=groups)
    return mod


def run(df):
    results = OrderedDict()
    paired = {v: {t: [] for t in hl.HORIZONS} for v in ("reg", "rank")}
    for tgt in hl.HORIZONS:
        rows = []
        for cut, tr, te in hl.folds(df, hl.PURGE[tgt]):
            trv = tr.dropna(subset=[tgt])
            tev = te.dropna(subset=[tgt]).copy()
            if len(trv) < 200 or len(tev) < 50:
                continue
            mods = {"reg": fit_reg(trv, tgt), "rank": fit_ranker(trv, tgt)}
            for v, mod in mods.items():
                tev[f"p_{v}"] = mod.predict(tev[hl.ALL_FEATS].astype(float))
            ic_b = day_ics(tev, "blend10", tgt)
            row = {"cut": cut, "n_gun": len(ic_b),
                   "dic_blend": round(float(np.mean(list(ic_b.values()))), 3) if ic_b else np.nan}
            for v in ("reg", "rank"):
                ic_m = day_ics(tev, f"p_{v}", tgt)
                ortak = sorted(set(ic_m) & set(ic_b))
                row[f"dic_{v}"] = round(float(np.mean(list(ic_m.values()))), 3) if ic_m else np.nan
                paired[v][tgt] += [ic_m[d] - ic_b[d] for d in ortak]   # gün-eşleştirmeli fark
            rows.append(row)
        results[tgt] = rows
    return results, paired


def gate(results, paired):
    """Kapı kararı varyant×hedef başına: fold galibiyeti + eşleştirmeli fark testi."""
    out = {}
    for v in ("reg", "rank"):
        for tgt in hl.HORIZONS:
            rows = results[tgt]
            wins = sum(1 for r in rows if r[f"dic_{v}"] == r[f"dic_{v}"]
                       and r["dic_blend"] == r["dic_blend"] and r[f"dic_{v}"] > r["dic_blend"])
            d = np.array(paired[v][tgt], float)
            d = d[~np.isnan(d)]
            md = float(d.mean()) if len(d) else np.nan
            se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 3 else np.nan
            ok = bool(wins >= GATE_MIN_FOLD_WINS and md == md and se == se and md > se)
            out[f"{v}/{tgt}"] = {"fold_galibiyet": f"{wins}/{len(rows)}",
                                 "eslestirmeli_fark": round(md, 4) if md == md else None,
                                 "SE": round(se, 4) if se == se else None,
                                 "n_gun": int(len(d)), "KAPI": "GEÇTİ" if ok else "KALDI"}
    return out


def main():
    df = hl.load_dataset()
    # kalabalık gün istatistiği (bilgi)
    sz = df.groupby("asof").size()
    print(f"• {len(df)} aday-gün · {len(sz)} gün · kalabalık gün (≥2 aday): {(sz>=2).sum()} "
          f"(%{(sz>=2).mean()*100:.0f}) · medyan aday/gün {sz.median():.0f}", flush=True)

    results, paired = run(df)
    for tgt, rows in results.items():
        print(f"\n═══ {tgt} — gün-içi IC (yalnız ≥2 adaylı günler) ═══")
        print(f"{'kesim':10s} {'gün':>4s}  {'blend10':>7s} {'ML-reg':>7s} {'ML-rank':>7s}")
        for r in rows:
            print(f"{r['cut']:10s} {r['n_gun']:4d}  {r['dic_blend']:7.3f} "
                  f"{r['dic_reg']:7.3f} {r['dic_rank']:7.3f}")

    g = gate(results, paired)
    print("\n═══ KAPI KARARI (Aşama 2 batarya için) ═══")
    for k, v in g.items():
        print(f"{k:11s}: fold {v['fold_galibiyet']} · eşleştirmeli fark {v['eslestirmeli_fark']} "
              f"(SE {v['SE']}, {v['n_gun']} gün) → {v['KAPI']}")
    any_pass = any(v["KAPI"] == "GEÇTİ" for v in g.values())
    print(f"\nSONUÇ: {'en az bir varyant kapıyı GEÇTİ → Aşama 2 (batarya) koşulacak' if any_pass else 'hiçbir varyant kapıyı geçemedi → Aşama 2 KOŞULMAZ (spec kuralı)'}")

    mt = json.load(open(m.META_PATH)) if os.path.exists(m.META_PATH) else {}
    mt["rank_lab"] = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                      "stage1": results, "gate": g, "stage2_run": bool(any_pass)}
    json.dump(mt, open(m.META_PATH, "w"), ensure_ascii=False, indent=1)
    print(f"kayıt: {m.META_PATH} → rank_lab")


if __name__ == "__main__":
    main()

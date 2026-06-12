# -*- coding: utf-8 -*-
"""Deney sonuç analizörü: ayrık pencereler (W1/W2/W3) üzerinden dayanıklılık sıralaması.
Kullanım: python3 exp_analyze.py swing2_out/exp_a_results.csv [baseline_adı]"""
import sys
import pandas as pd

path = sys.argv[1] if len(sys.argv) > 1 else "swing2_out/exp_a_results.csv"
base_name = sys.argv[2] if len(sys.argv) > 2 else None

df = pd.read_csv(path)
p = df.pivot_table(index="exp", columns="win", values=["cagr", "dd", "pf", "roi", "n"], aggfunc="first")

out = pd.DataFrame(index=p.index)
out["roi_FULL"] = p[("roi", "FULL")]
out["dd_FULL"] = p[("dd", "FULL")]
out["roi_L2Y"] = p[("roi", "L2Y")]
out["dd_L2Y"] = p[("dd", "L2Y")]
for w in ("W1", "W2", "W3"):
    out[f"cagr_{w}"] = p[("cagr", w)]
disj = out[["cagr_W1", "cagr_W2", "cagr_W3"]]
out["cagr_min"] = disj.min(axis=1)          # en kötü ayrık pencere (dayanıklılık)
out["cagr_avg"] = disj.mean(axis=1)
out["dd_worst"] = p[("dd", "FULL")]          # FULL pencere DD (bileşik gerçek seyir)
out["mar"] = (p[("cagr", "FULL")] / p[("dd", "FULL")].abs()).round(3)  # CAGR/|DD|
out["pf_FULL"] = p[("pf", "FULL")]
out["n_FULL"] = p[("n", "FULL")]

out = out.sort_values(["cagr_min", "dd_worst"], ascending=[False, False]).round(2)
pd.set_option("display.width", 250)
print(f"\n== {path} — dayanıklılık sırası (cagr_min ↓, dd ↑) ==\n")
print(out.to_string())

if base_name and base_name in out.index:
    b = out.loc[base_name]
    print(f"\n-- Baz ({base_name}): cagr_min {b['cagr_min']:+.2f} · MAR {b['mar']:.3f} · "
          f"FULL ROI {b['roi_FULL']:+.1f}%/DD {b['dd_FULL']:.1f}% --")
    better = out[(out["cagr_min"] > b["cagr_min"]) & (out["dd_worst"] >= b["dd_worst"])]
    print(f"Bazı HEM cagr_min HEM DD'de geçenler: {list(better.index) or 'YOK'}")

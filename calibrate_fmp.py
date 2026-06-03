# -*- coding: utf-8 -*-
"""Şampiyon yeniden kalibrasyonu — FMP verisiyle 2y + 5y 7-boyutlu grid.
İki dönemde de sağlam (out-of-sample dayanıklı) kombinasyonu seçer.
Kullanım: python3 calibrate_fmp.py
"""
import copy, json
import pandas as pd
import swing2_backtest as s

# Odaklı grid (36 kombinasyon) — motor backtest başına ~5-14s, tam 384 imkânsız.
# Sabit: min_score=16 (tatlı nokta), partial%=0.5, partial_trigger=2.0 (yerleşik).
# Taranan: rr_target · atr_stop · trailing · breakeven (şampiyonu belirleyen anahtar dimler).
CUSTOM_GRID = {
    "min_score":          [16],
    "rr_target":          [2.0, 2.5, 3.0],
    "atr_stop_mult":      [1.5, 2.0],
    "partial_tp_ratio":   [0.50],
    "partial_tp_trigger": [2.0],
    "trailing_atr_mult":  [2.5, 3.0, 3.5],
    "breakeven_mode":     ["strict_entry", "half_risk"],
}
KEYS = list(CUSTOM_GRID.keys())
PERIODS = ["2y", "5y"]


def build_market(period):
    cfg = s.Config()
    cfg.universe = s.DEFAULT_UNIVERSE
    cfg.period = period
    cfg.price_source = "fmp"        # ÜCRETLİ FMP
    cfg.disk_cache = True           # bir kez indir, tekrar kullan
    cfg.use_earnings = False        # grid'de sabit (hız + tutarlı sıralama)
    cfg.per_ticker_download = False
    print(f"\n===== {period.upper()} · FMP verisi indiriliyor =====", flush=True)
    return cfg, s.download_and_align_data(cfg)


def main():
    per_results = {}
    base_cfgs = {}
    for p in PERIODS:
        cfg, market = build_market(p)
        base_cfgs[p] = cfg
        df = s.run_grid_search(cfg, market, grid=CUSTOM_GRID, top=3)   # 36 kombinasyon
        df.to_csv(f"/home/gokhan/swing2_out/calib_{p}.csv", index=False)  # dönem-başı ara kayıt
        print(f"[{p}] grid bitti → swing2_out/calib_{p}.csv", flush=True)
        per_results[p] = df.set_index(KEYS)

    # ---- İki dönemi birleştir ----
    d2, d5 = per_results["2y"], per_results["5y"]
    M = d2.join(d5, lsuffix="_2y", rsuffix="_5y")
    M["roi_min"] = M[["roi_2y", "roi_5y"]].min(axis=1)      # en kötü dönem (dayanıklılık)
    M["roi_sum"] = M["roi_2y"] + M["roi_5y"]
    M["dd_worst"] = M[["maxdd_2y", "maxdd_5y"]].min(axis=1)  # en derin DD (negatif → büyük=iyi)
    M["win_avg"] = (M["win_2y"] + M["win_5y"]) / 2

    # Şampiyon kriteri: önce en-kötü-dönem ROI yüksek (out-of-sample dayanıklı),
    # eşitlikte daha sığ en-derin-DD (risk-ayarlı). Orijinal ethos: düşük drawdown.
    robust = M.sort_values(["roi_min", "dd_worst"], ascending=[False, False])
    by_total = M.sort_values(["roi_sum", "dd_worst"], ascending=[False, False])

    def show(df, title, n=8):
        line = "=" * 116
        print(f"\n{line}\n  {title}\n{line}")
        print(f"  {'sc':<3}{'rr':<5}{'atrS':<5}{'pTP%':<6}{'trig':<5}{'trail':<6}{'breakeven':<13}"
              f"{'ROI2y':>8}{'DD2y':>7}{'ROI5y':>8}{'DD5y':>7}{'ROImin':>8}{'WinAvg':>8}")
        print("  " + "-" * 112)
        for idx, r in df.head(n).iterrows():
            sc, rr, atr, ptp, trig, trail, bem = idx
            print(f"  {int(sc):<3}{rr:<5}{atr:<5}{ptp:<6}{trig:<5}{trail:<6}{bem:<13}"
                  f"{r['roi_2y']:>+8.1f}{r['maxdd_2y']:>7.1f}{r['roi_5y']:>+8.1f}{r['maxdd_5y']:>7.1f}"
                  f"{r['roi_min']:>+8.1f}{r['win_avg']:>7.1f}%")
        print(line)

    show(robust, "ŞAMPİYON ADAYLARI — DAYANIKLILIK (en-kötü-dönem ROI ↓, sonra DD ↑)")
    show(by_total, "ALTERNATİF — TOPLAM ROI (2y+5y ↓)")

    champ_idx = robust.index[0]
    sc, rr, atr, ptp, trig, trail, bem = champ_idx
    champ = {
        "min_score": int(sc), "rr_target": rr, "atr_stop_mult": atr,
        "partial_pct": ptp, "partial_rr": trig, "atr_trail_mult": trail,
        "breakeven_mode": bem,
    }
    cr = robust.iloc[0]
    print("\n>>> FMP ŞAMPİYONU (dayanıklılık kriteri):")
    print("    " + json.dumps(champ, ensure_ascii=False))
    print(f"    2y: ROI {cr['roi_2y']:+.1f}% · DD {cr['maxdd_2y']:.1f}% · Win {cr['win_2y']:.0f}% · PF {cr['pf_2y']}")
    print(f"    5y: ROI {cr['roi_5y']:+.1f}% · DD {cr['maxdd_5y']:.1f}% · Win {cr['win_5y']:.0f}% · PF {cr['pf_5y']}")

    # ---- Eski (memory) şampiyonu FMP'de kıyasla ----
    OLD = {"min_score": 16, "rr_target": 2.5, "atr_stop_mult": 1.5,
           "partial_tp_ratio": 0.50, "partial_tp_trigger": 2.0,
           "trailing_atr_mult": 3.0, "breakeven_mode": "half_risk"}
    old_idx = tuple(OLD[k] for k in KEYS)
    if old_idx in M.index:
        o = M.loc[old_idx]
        print(f"\n    [kıyas] Eski memory-şampiyonu FMP'de: "
              f"2y ROI {o['roi_2y']:+.1f}%/DD {o['maxdd_2y']:.1f}% · "
              f"5y ROI {o['roi_5y']:+.1f}%/DD {o['maxdd_5y']:.1f}%")

    # ---- Config varsayılanını FMP'de kıyasla ----
    DEF = {"min_score": 16, "rr_target": 2.0, "atr_stop_mult": 1.5,
           "partial_tp_ratio": 0.50, "partial_tp_trigger": 1.5,
           "trailing_atr_mult": 2.5, "breakeven_mode": "strict_entry"}
    def_idx = tuple(DEF[k] for k in KEYS)
    if def_idx in M.index:
        o = M.loc[def_idx]
        print(f"    [kıyas] Mevcut Config varsayılanı FMP'de: "
              f"2y ROI {o['roi_2y']:+.1f}%/DD {o['maxdd_2y']:.1f}% · "
              f"5y ROI {o['roi_5y']:+.1f}%/DD {o['maxdd_5y']:.1f}%")

    M.reset_index().to_csv("/home/gokhan/swing2_out/calib_fmp.csv", index=False)
    print("\nTam sonuç: /home/gokhan/swing2_out/calib_fmp.csv")


if __name__ == "__main__":
    main()

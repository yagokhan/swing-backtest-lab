# -*- coding: utf-8 -*-
"""qswing kırılım girişi — eşik ızgara taraması (FMP, 2y+5y).
Taranan: kırılım periyodu · VDU sıkılık tavanı · RS eşiği · çıkış modu.
Tek market/dönem (çoklu-lookback + VDU kolonları önceden hesaplı) → rebuild yok.
"""
import copy, itertools
import pandas as pd
import swing2_backtest as s

GRID = {
    "qswing_breakout_lb": [10, 20, 40],
    "qswing_vdu_max":     [9.0, 1.0, 0.85],   # 9.0 = kapalı
    "qswing_rs_min":      [0.0, 8.0],
}
EXITS = ["optimized", "ma_trail"]             # ATR-trail şampiyon · Qullamaggie 10g MA
PERIODS = ["2y", "5y"]
KEYS = list(GRID.keys()) + ["exit"]


def build(per):
    cfg = s.Config()
    cfg.universe = s.DEFAULT_UNIVERSE; cfg.period = per
    cfg.price_source = "fmp"; cfg.disk_cache = True
    cfg.use_earnings = False; cfg.per_ticker_download = False
    cfg.entry_mode = "qswing_breakout"; cfg.ma_trail_len = 10
    print(f"\n===== {per.upper()} · market kuruluyor =====", flush=True)
    return cfg, s.download_and_align_data(cfg)


def run_combo(base, market, combo, exit_mode):
    cfg = copy.deepcopy(base)
    for k, v in zip(GRID.keys(), combo):
        setattr(cfg, k, v)
    cfg.exit_mode = exit_mode
    market["vcp_cache"] = {}
    bt = s.Swing2Backtester(cfg, market=market); bt.run(); m = bt.metrics()
    return {"qswing_breakout_lb": combo[0], "qswing_vdu_max": combo[1],
            "qswing_rs_min": combo[2], "exit": exit_mode,
            "roi": round(m["roi"], 1), "maxdd": round(m["max_dd"], 1),
            "win": round(m["win_rate"], 1),
            "pf": round(m["profit_factor"], 2) if m["profit_factor"] != float("inf") else None,
            "trades": m["trades"]}


def main():
    combos = list(itertools.product(*GRID.values()))
    total = len(combos) * len(EXITS)
    per_res = {}
    for per in PERIODS:
        base, market = build(per)
        rows = []; i = 0
        for combo in combos:
            for ex in EXITS:
                i += 1
                r = run_combo(base, market, combo, ex)
                rows.append(r)
                print(f"  [{per} {i}/{total}] lb={r['qswing_breakout_lb']} vdu={r['qswing_vdu_max']} "
                      f"rs={r['qswing_rs_min']} {ex:9s} → ROI {r['roi']:+.1f}% DD {r['maxdd']:.1f}% "
                      f"{r['trades']}iş", flush=True)
        df = pd.DataFrame(rows)
        df.to_csv(f"/home/gokhan/swing2_out/qgrid_{per}.csv", index=False)
        per_res[per] = df.set_index(KEYS)

    M = per_res["2y"].join(per_res["5y"], lsuffix="_2y", rsuffix="_5y")
    M["roi_min"] = M[["roi_2y", "roi_5y"]].min(axis=1)
    M["dd_worst"] = M[["maxdd_2y", "maxdd_5y"]].min(axis=1)
    robust = M.sort_values(["roi_min", "dd_worst"], ascending=[False, False])

    line = "=" * 104
    print(f"\n{line}\n  qswing KIRILIM — EŞİK ŞAMPİYONLARI (en-kötü-dönem ROI ↓, sonra DD ↑)\n{line}")
    print(f"  {'lb':<4}{'vduMax':<8}{'rsMin':<7}{'exit':<11}{'ROI2y':>8}{'DD2y':>7}"
          f"{'ROI5y':>8}{'DD5y':>7}{'ROImin':>8}{'Win2y':>7}{'PF2y':>6}")
    print("  " + "-" * 100)
    for idx, r in robust.head(10).iterrows():
        lb, vdu, rs, ex = idx
        print(f"  {int(lb):<4}{vdu:<8}{rs:<7}{ex:<11}{r['roi_2y']:>+8.1f}{r['maxdd_2y']:>7.1f}"
              f"{r['roi_5y']:>+8.1f}{r['maxdd_5y']:>7.1f}{r['roi_min']:>+8.1f}{r['win_2y']:>6.0f}%{r['pf_2y']:>6}")
    print(line)
    bi = robust.index[0]; br = robust.iloc[0]
    print(f"\n>>> qswing EŞİK ŞAMPİYONU: lb={bi[0]} · vdu_max={bi[1]} · rs_min={bi[2]} · exit={bi[3]}")
    print(f"    2y ROI {br['roi_2y']:+.1f}%/DD {br['maxdd_2y']:.1f}% · 5y ROI {br['roi_5y']:+.1f}%/DD {br['maxdd_5y']:.1f}%")
    M.reset_index().to_csv("/home/gokhan/swing2_out/qgrid_fmp.csv", index=False)
    print("\nTam sonuç: swing2_out/qgrid_fmp.csv")


if __name__ == "__main__":
    main()

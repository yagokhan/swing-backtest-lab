#!/usr/bin/env python3
"""qswing girişi × 3 çıkış × 5 dönem = 15 backtest (sp500 ~350 hisse).
Çıkışlar: ATR-trail (tam) · 8/21-EMA hibrit (tam) · ½hibrit+½ATR (bölünmüş).
Dönemler: 5y · 3y · 2y · 1y · 6mo. Trade ledger'ları CSV'ye + özet CSV.
Veri bir kez (6y) indirilir, 15 koşuda paylaşılır (start_date ile pencere sınırlanır).
"""
import csv, os, copy
import pandas as pd
import swing2_backtest as s

OUT = "/home/gokhan/swing-backtest-lab/backtests"
os.makedirs(OUT, exist_ok=True)
NOW = pd.Timestamp.now().normalize()

# ---- tek geniş indirme (6y → 5y backtest + ısınma için yeterli) ----
base = s.Config()
base.universe = s.UNIVERSE_PRESETS["sp500"]
base.price_source = "fmp"; base.period = "6y"; base.use_earnings = False
base.per_ticker_download = False; base.disk_cache = True
market = s.download_and_align_data(base)
print(f"İndirme tamam: {len(market['data'])} hisse\n")

PERIODS = [("5y", 5*365), ("3y", 3*365), ("2y", 2*365), ("1y", 365), ("6mo", 182)]
EXITS = ["atr", "hybrid", "split"]


def make_cfg(exit_key, start_date):
    c = s.Config()
    c.universe = s.UNIVERSE_PRESETS["sp500"]
    c.price_source = "fmp"; c.use_earnings = False
    c.entry_mode = "qswing_breakout"
    c.start_date = start_date; c.end_date = ""
    # boyutlandırma: motor varsayılanı (max 5 poz · %20/poz · compounding)
    if exit_key == "atr":
        c.exit_mode = "atr_full"; c.atr_trail_mult = 2.5; c.partial_tp = False
    elif exit_key == "hybrid":
        c.exit_mode = "tp_grid"; c.tp_mode = "HYBRID_TREND"; c.ma_confirm_close = True; c.partial_tp = False
    else:  # split: ½ hibrit + ½ ATR
        c.exit_mode = "split"; c.split_a = "hybrid"; c.split_b = "atr_trail"
        c.split_b_param = 2.5; c.split_ratio = 0.5; c.partial_tp = False
    return c


def write_csv(bt, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "sector", "score", "entry_date", "exit_date",
                    "entry", "exit", "shares", "pnl", "pnl_pct", "outcome"])
        for t in bt.trades:
            w.writerow([t.symbol, t.sector, int(t.score),
                        t.entry_date.strftime("%Y-%m-%d"), t.exit_date.strftime("%Y-%m-%d"),
                        round(t.entry, 2), round(t.exit, 2), round(t.shares, 4),
                        round(t.pnl, 2), round(t.pnl_pct, 2), t.outcome])


EXLBL = {"atr": "ATR-trail", "hybrid": "8/21-EMA hibrit", "split": "½hibrit+½ATR"}
summary = []
print(f"{'çıkış':16s} {'dönem':5s} {'tarih':24s} {'ROI':>8s} {'SPY':>7s} {'DD':>7s} {'Win':>5s} {'PF':>5s} {'işlem':>6s}")
for plabel, pdays in PERIODS:
    sd = (NOW - pd.Timedelta(days=pdays)).strftime("%Y-%m-%d")
    for ek in EXITS:
        cfg = make_cfg(ek, sd)
        bt = s.Swing2Backtester(cfg, market=market)
        bt.run(); m = bt.metrics()
        eq = m["equity"]
        fn = f"sp500_qswing_{ek}_{plabel}.csv"
        write_csv(bt, os.path.join(OUT, fn))
        roi, spy, dd = m["roi"], m["spy_roi"], m["max_dd"]
        wr, pf, ntr = m["win_rate"], m["profit_factor"], m["trades"]
        st, en = eq.index[0].strftime("%Y-%m-%d"), eq.index[-1].strftime("%Y-%m-%d")
        print(f"{EXLBL[ek]:16s} {plabel:5s} {st}→{en} {roi:7.1f}% {spy:6.1f}% {dd:6.1f}% {str(wr)[:4]:>5s} {pf:5.2f} {ntr:6d}")
        summary.append([ek, EXLBL[ek], plabel, st, en, roi, spy, round(roi-spy, 2),
                        dd, wr, pf, ntr, round(float(bt.cash), 2)])

# özet CSV
with open(os.path.join(OUT, "sp500_qswing_3exit_5period_SUMMARY.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["exit_key", "exit_label", "period", "start", "end", "roi_pct", "spy_roi_pct",
                "alpha_pct", "max_dd_pct", "win_rate_pct", "profit_factor", "trades", "final_capital"])
    w.writerows(summary)
print(f"\n{len(summary)} backtest · CSV'ler → {OUT}")

#!/usr/bin/env python3
"""BİRLEŞİK uzun/kısa kripto portföyü: 5 pencere × {uzun-tek, kısa-tek, birleşik}.

Uzun defter = Swing2Backtester'ın KENDİSİ (şampiyon: qswing kırılım + BTC kilidi 2.5 +
HYBRID_TREND çıkış) · Kısa defter = ayna kırılım, kilitsiz, hibrit kapatma + 3bps/gün
funding · TEK nakit havuzu (kaldıraçsız; rejim geçişlerinde defterler çakışabilir, havuz
sınırlar). Eşdeğerlik kanıtı: kısa-kapalı birleşik koşu, saf motor ledger'ıyla birebir.

Kullanım: python3 backtests/run_crypto_combined_backtests.py
Çıktı:  backtests/crypto_combined_SUMMARY.csv
"""
import csv, os, sys
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import swing2_backtest as s
from short_backtest import ShortBacktester, ShortParams
from combined_backtest import CombinedBacktester, champion_long_cfg
from crypto_data import load_pinned_universe

OUT = os.path.join(ROOT, "backtests")
NOW = pd.Timestamp.now().normalize()

cfg0 = champion_long_cfg()
cfg0.universe = load_pinned_universe()
cfg0.period = "6y"; cfg0.disk_cache = True
market = s.download_and_align_data(cfg0)
print(f"İndirme tamam: {len(market['data'])} coin\n")

PERIODS = [("5y", 5*365), ("3y", 3*365), ("2y", 2*365), ("1y", 365), ("6mo", 182)]

rows = []
print(f"{'pencere':7s} {'taraf':14s} {'ROI':>8s} {'BTC':>7s} {'Alpha':>7s} {'DD':>7s} "
      f"{'Win':>5s} {'PF':>6s} {'işlem':>12s}")
for plabel, pdays in PERIODS:
    sd = (NOW - pd.Timedelta(days=pdays)).strftime("%Y-%m-%d")
    runs = []
    bt = s.Swing2Backtester(champion_long_cfg(start_date=sd), market=market); bt.run()
    runs.append(("long", "🟢 uzun-tek (kilit 2.5)", bt.metrics(), None))
    sb = ShortBacktester(market, ShortParams(start_date=sd)).run()
    sm = sb.metrics(); sm["spy_roi"] = sm.pop("bench_roi")
    runs.append(("short", "🔻 kısa-tek (kilitsiz)", sm, None))
    cb = CombinedBacktester(market, ShortParams(start_date=sd)).run()
    cm = cb.metrics(); cm["spy_roi"] = cm.pop("bench_roi")
    runs.append(("combined", "⚖️ birleşik (tek havuz)", cm,
                 f"U:{cm['long_trades']}/{cm['long_pnl']:+,.0f}$ · K:{cm['short_trades']}/{cm['short_pnl']:+,.0f}$"))
    # duyarlılık: kısa defter YARIM boy (%10/poz) — sinyal aynı, yalnız boyut (overfit değil)
    ch = CombinedBacktester(market, ShortParams(start_date=sd, max_position_pct=0.10)).run()
    hm = ch.metrics(); hm["spy_roi"] = hm.pop("bench_roi")
    runs.append(("combined_half", "⚖️ birleşik (kısa ½)", hm,
                 f"U:{hm['long_trades']}/{hm['long_pnl']:+,.0f}$ · K:{hm['short_trades']}/{hm['short_pnl']:+,.0f}$"))
    if plabel == "5y":
        # 5y özsermaye eğrileri → aylık ızgara + drawdown görselleri için (gen_crypto_report)
        eqs = {key: m["equity"] for key, _, m, _ in runs}
        btc = market["spy"]["Close"].reindex(eqs["long"].index)
        btc = btc / btc.iloc[0] * 100_000.0
        pd.DataFrame({**eqs, "btc_bh": btc}).to_csv(
            os.path.join(OUT, "crypto_combined_equity_5y.csv"),
            index_label="date", float_format="%.2f")
    for key, lbl, m, detail in runs:
        pf = m["profit_factor"]
        ntx = f"{m['trades']:4d}" + (f"  ({detail})" if detail else "")
        print(f"{plabel:7s} {lbl:14s} {m['roi']:7.1f}% {m['spy_roi']:6.1f}% "
              f"{m['roi']-m['spy_roi']:6.1f} {m['max_dd']:6.1f}% {m['win_rate']:4.0f}% "
              f"{(999.0 if pf == float('inf') else pf):6.2f} {ntx}")
        eq = m["equity"]
        rows.append([key, plabel, eq.index[0].strftime("%Y-%m-%d"), eq.index[-1].strftime("%Y-%m-%d"),
                     round(m["roi"], 2), round(m["spy_roi"], 2), round(m["roi"] - m["spy_roi"], 2),
                     round(m["max_dd"], 2), round(m["win_rate"], 1),
                     (None if pf == float("inf") else round(pf, 3)), m["trades"],
                     m.get("long_trades"), m.get("short_trades"),
                     (round(m["long_pnl"], 2) if "long_pnl" in m else None),
                     (round(m["short_pnl"], 2) if "short_pnl" in m else None)])
    print()

with open(os.path.join(OUT, "crypto_combined_SUMMARY.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["side", "period", "start", "end", "roi_pct", "bench_roi_pct", "alpha_pct",
                "max_dd_pct", "win_rate_pct", "profit_factor", "trades",
                "long_trades", "short_trades", "long_pnl", "short_pnl"])
    w.writerows(rows)
print(f"{len(rows)} koşu · crypto_combined_SUMMARY.csv → {OUT}")

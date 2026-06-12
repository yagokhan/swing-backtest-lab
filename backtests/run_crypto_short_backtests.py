#!/usr/bin/env python3
"""KRİPTO KISA (short) taraf: ayna-qswick kırılım girişi × 2 kapatma × 5 pencere × kilit {yok, 2.5}.

Giriş yalnız AYI rejiminde (BTC<SMA200): 40g DİP kırılımı + 52H dibe yakın + BTC'den zayyf
momentum. Kapatmalar: 'atr_cover' (dip+2.5×ATR üstü kapanış) · 'hybrid' (%50 KAPANIŞ>EMA8 ·
%50 KAPANIŞ>EMA21). Maliyet: 10bps/bacak komisyon + slippage + 3bps/GÜN funding (perp
varsayımı, MUHAFAZAKÂR — ayıda kısalar funding öder).

⚠️ Uzun taraftaki sağ-kalan yanlılığı burada TERS çalışır: delist olmuş (sıfıra giden)
coinler evrende YOK → kısa tarafın gerçek getirisi burada görünenden İYİ olabilirdi.
Yine de mutlak sayılar değil, davranış (ayıda alpha, DD profili) okunmalı.

Kullanım: python3 backtests/run_crypto_short_backtests.py [--ledgers] [--funding BPS]
Çıktı:  backtests/crypto_short_SUMMARY.csv (+ --ledgers ile işlem CSV'leri)
"""
import csv, os, sys
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import swing2_backtest as s
from short_backtest import ShortBacktester, ShortParams
from crypto_data import load_pinned_universe

OUT = os.path.join(ROOT, "backtests")
NOW = pd.Timestamp.now().normalize()
FUNDING = float(sys.argv[sys.argv.index("--funding") + 1]) if "--funding" in sys.argv else 3.0
LEDGERS = "--ledgers" in sys.argv

cfg = s.Config()
cfg.universe = load_pinned_universe()
cfg.benchmark = "BTCUSDT"; cfg.price_source = "binance"
cfg.use_earnings = False; cfg.disk_cache = True; cfg.period = "6y"
cfg.high52_bars = 365; cfg.warmup_bars = 380
market = s.download_and_align_data(cfg)
print(f"İndirme tamam: {len(market['data'])} coin · funding {FUNDING}bps/gün\n")

PERIODS = [("5y", 5*365), ("3y", 3*365), ("2y", 2*365), ("1y", 365), ("6mo", 182)]
EXITS = [("atr_cover", "ATR-cover (dip+2.5×ATR)"), ("hybrid", "8/21-EMA hibrit kapatma")]
LOCKS = [(False, "kilitsiz"), (True, "kilit 2.5")]

rows = []
print(f"{'kapatma':22s} {'kilit':9s} {'dönem':5s} {'ROI':>8s} {'BTC':>7s} {'Alpha':>7s} {'DD':>7s} {'Win':>5s} {'PF':>5s} {'işlem':>6s}")
for plabel, pdays in PERIODS:
    sd = (NOW - pd.Timedelta(days=pdays)).strftime("%Y-%m-%d")
    for ek, elbl in EXITS:
        for lock, llbl in LOCKS:
            p = ShortParams(exit_mode=ek, funding_bps_daily=FUNDING, start_date=sd,
                            regime_atr_filter=lock)
            bt = ShortBacktester(market, p).run()
            m = bt.metrics()
            pf = m["profit_factor"]
            print(f"{elbl:22s} {llbl:9s} {plabel:5s} {m['roi']:7.1f}% {m['bench_roi']:6.1f}% "
                  f"{m['alpha']:6.1f} {m['max_dd']:6.1f}% {m['win_rate']:4.0f}% "
                  f"{(99.99 if pf == float('inf') else pf):5.2f} {m['trades']:6d}")
            eq = m["equity"]
            rows.append([ek, elbl, llbl, plabel,
                         eq.index[0].strftime("%Y-%m-%d"), eq.index[-1].strftime("%Y-%m-%d"),
                         round(m["roi"], 2), round(m["bench_roi"], 2), round(m["alpha"], 2),
                         round(m["max_dd"], 2), round(m["win_rate"], 1),
                         (None if pf == float("inf") else round(pf, 3)), m["trades"], FUNDING])
            if LEDGERS and m["trades"]:
                fn = f"crypto_short_{ek}{'_lock25' if lock else ''}_{plabel}.csv"
                with open(os.path.join(OUT, fn), "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["symbol", "entry_date", "exit_date", "entry", "exit",
                                "shares", "pnl", "pnl_pct", "outcome"])
                    for t in bt.trades:
                        w.writerow([t.symbol, pd.Timestamp(t.entry_date).strftime("%Y-%m-%d"),
                                    pd.Timestamp(t.exit_date).strftime("%Y-%m-%d"),
                                    round(t.entry, 8), round(t.exit, 8), round(t.shares, 6),
                                    round(t.pnl, 2), round(t.pnl_pct, 2), t.outcome])

with open(os.path.join(OUT, "crypto_short_SUMMARY.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["exit_key", "exit_label", "lock", "period", "start", "end", "roi_pct",
                "bench_roi_pct", "alpha_pct", "max_dd_pct", "win_rate_pct",
                "profit_factor", "trades", "funding_bps_daily"])
    w.writerows(rows)
print(f"\n{len(rows)} koşu · crypto_short_SUMMARY.csv → {OUT}")

#!/usr/bin/env python3
"""KRİPTO: qswing girişi × 3 çıkış × 5 dönem = 15 backtest (Binance top-75 USDT).
Çıkışlar: ATR-trail (tam) · 8/21-EMA hibrit (tam) · ½hibrit+½ATR (bölünmüş).
Dönemler: 5y · 3y · 2y · 1y · 6mo. Satırlar sp500_qswing_3exit_5period_SUMMARY.csv
ile birebir karşılaştırılabilir (aynı motor, aynı 15 hücre); benchmark = BTCUSDT
al-tut (kolon: bench_roi_pct).

Kripto farkları: günlük bar UTC 00:00 kapanışlı, takvim 7 gün/hafta · komisyon
%0.10/bacak (commission_bps=10, Binance spot taker) · 52H penceresi 365 bar ·
warmup 380 bar (HIGH52'nin işlem başında dolu olması için) · earnings/sektör yok.

⚠️ SAĞ-KALAN YANLILIĞI: evren bugünün top-75 listesidir (crypto_universe_pinned.json,
≥400 bar geçmiş şartı); delist olmuş coinler (LUNA-vari ölümler) YOK. Mutlak ROI
iyimser tavandır — birincil metrik BTCUSDT al-tuta karşı ALPHA okunmalı. En uzun
pencere (5y) en çok yanlılık taşır.

Kullanım:  python3 backtests/run_crypto_backtests.py [--regime-grid]
  --regime-grid: 2y × 3 çıkış × regime_atr_threshold {kapalı,2.0,2.5,3.0,3.5,4.5}
                 → crypto_regime_grid.csv (BTC ATR20% tipik %2-4; hisse vars. 1.5
                 kripto için nerdeyse daima kilitli kalır — tahmin değil ölçüm).
"""
import csv, os, sys
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import swing2_backtest as s
from crypto_data import load_pinned_universe

OUT = os.path.join(ROOT, "backtests")
os.makedirs(OUT, exist_ok=True)
NOW = pd.Timestamp.now().normalize()


def base_config():
    c = s.Config()
    c.universe = load_pinned_universe()
    c.benchmark = "BTCUSDT"; c.price_source = "binance"
    c.use_earnings = False; c.disk_cache = True; c.period = "6y"
    c.commission_bps = 10.0          # Binance spot taker ~%0.10/bacak
    c.high52_bars = 365              # kripto yılı (7g/hafta)
    c.warmup_bars = 380              # HIGH52(365) işlem başında NaN kalmasın
    c.entry_fill_mode = "close"      # 00:00 UTC kapanışı saniyeler sonra işlenebilir
    return c


# ---- tek geniş indirme (6y → 5y backtest + ısınma), 15 koşuda paylaşılır ----
market = s.download_and_align_data(base_config())
print(f"İndirme tamam: {len(market['data'])} coin\n")

PERIODS = [("5y", 5*365), ("3y", 3*365), ("2y", 2*365), ("1y", 365), ("6mo", 182)]
EXITS = ["atr", "hybrid", "split"]


def make_cfg(exit_key, start_date):
    c = base_config()
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
                        round(t.entry, 6), round(t.exit, 6), round(t.shares, 6),
                        round(t.pnl, 2), round(t.pnl_pct, 2), t.outcome])


def run_one(cfg):
    bt = s.Swing2Backtester(cfg, market=market)
    bt.run()
    return bt, bt.metrics()


EXLBL = {"atr": "ATR-trail", "hybrid": "8/21-EMA hibrit", "split": "½hibrit+½ATR"}

if "--regime-grid" in sys.argv:
    # ---- ATR-REJİM eşik ızgarası: 2y × 3 çıkış × 6 eşik ----
    THRESH = [None, 2.0, 2.5, 3.0, 3.5, 4.5]      # None = filtre kapalı
    sd = (NOW - pd.Timedelta(days=2*365)).strftime("%Y-%m-%d")
    rows = []
    print(f"{'çıkış':16s} {'eşik':>6s} {'ROI':>8s} {'BTC':>7s} {'DD':>7s} {'Win':>5s} {'PF':>5s} {'işlem':>6s}")
    for ek in EXITS:
        for th in THRESH:
            cfg = make_cfg(ek, sd)
            if th is not None:
                cfg.regime_atr_filter = True; cfg.regime_atr_threshold = th
            bt, m = run_one(cfg)
            lbl = "kapalı" if th is None else f"{th:.1f}"
            print(f"{EXLBL[ek]:16s} {lbl:>6s} {m['roi']:7.1f}% {m['spy_roi']:6.1f}% "
                  f"{m['max_dd']:6.1f}% {str(m['win_rate'])[:4]:>5s} {m['profit_factor']:5.2f} {m['trades']:6d}")
            rows.append([ek, lbl, m["roi"], m["spy_roi"], round(m["roi"] - m["spy_roi"], 2),
                         m["max_dd"], m["win_rate"], m["profit_factor"], m["trades"]])
    with open(os.path.join(OUT, "crypto_regime_grid.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["exit_key", "regime_atr_threshold", "roi_pct", "bench_roi_pct",
                    "alpha_pct", "max_dd_pct", "win_rate_pct", "profit_factor", "trades"])
        w.writerows(rows)
    print(f"\n{len(rows)} koşu · crypto_regime_grid.csv → {OUT}")
    sys.exit(0)

summary = []
print(f"{'çıkış':16s} {'dönem':5s} {'tarih':24s} {'ROI':>8s} {'BTC':>7s} {'DD':>7s} {'Win':>5s} {'PF':>5s} {'işlem':>6s}")
for plabel, pdays in PERIODS:
    sd = (NOW - pd.Timedelta(days=pdays)).strftime("%Y-%m-%d")
    for ek in EXITS:
        bt, m = run_one(make_cfg(ek, sd))
        eq = m["equity"]
        write_csv(bt, os.path.join(OUT, f"crypto_qswing_{ek}_{plabel}.csv"))
        st, en = eq.index[0].strftime("%Y-%m-%d"), eq.index[-1].strftime("%Y-%m-%d")
        print(f"{EXLBL[ek]:16s} {plabel:5s} {st}→{en} {m['roi']:7.1f}% {m['spy_roi']:6.1f}% "
              f"{m['max_dd']:6.1f}% {str(m['win_rate'])[:4]:>5s} {m['profit_factor']:5.2f} {m['trades']:6d}")
        summary.append([ek, EXLBL[ek], plabel, st, en, m["roi"], m["spy_roi"],
                        round(m["roi"] - m["spy_roi"], 2), m["max_dd"], m["win_rate"],
                        m["profit_factor"], m["trades"], round(float(bt.cash), 2)])

with open(os.path.join(OUT, "crypto_qswing_3exit_5period_SUMMARY.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["exit_key", "exit_label", "period", "start", "end", "roi_pct", "bench_roi_pct",
                "alpha_pct", "max_dd_pct", "win_rate_pct", "profit_factor", "trades", "final_capital"])
    w.writerows(summary)
print(f"\n{len(summary)} backtest · CSV'ler → {OUT}")

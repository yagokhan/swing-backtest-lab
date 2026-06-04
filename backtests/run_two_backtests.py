#!/usr/bin/env python3
"""Telegram stratejisi (qswing giriş + 8/21-EMA hibrit çıkış) ile iki backtest.
Ocak 2026 → son veri. Aynı evren (sp500), aynı tarihler. Trade'leri CSV'ye yazar.
  #1: her poz %10 (compounding), max 10 poz
  #2: her poz $1000 sabit (compounding YOK), max 20 poz
"""
import csv, os
import swing2_backtest as s

OUT = "/home/gokhan/swing-backtest-lab/backtests"
os.makedirs(OUT, exist_ok=True)
START = "2026-01-01"


def base_cfg():
    c = s.Config()
    c.universe = s.UNIVERSE_PRESETS["sp500"]   # Telegram botuyla aynı evren (~352)
    c.price_source = "fmp"
    c.start_date = START
    c.end_date = ""                            # son veriye kadar
    c.use_earnings = False
    c.per_ticker_download = False
    c.disk_cache = True
    # Giriş: qswing kırılım (Telegram ile birebir)
    c.entry_mode = "qswing_breakout"
    # Çıkış: 8/21-EMA HİBRİT (Telegram ile birebir) — %50 8-EMA, runner 21-EMA
    c.exit_mode = "tp_grid"; c.tp_mode = "HYBRID_TREND"
    c.ma_confirm_close = True; c.partial_tp = False
    c.sizing_mode = "fixed"
    return c


def run(cfg, market, label):
    bt = s.Swing2Backtester(cfg, market=market)
    bt.run()
    mt = bt.metrics()
    eq = mt["equity"]
    print(f"\n===== {label} =====")
    print(f"  Tarih      : {eq.index[0].date()} → {eq.index[-1].date()}")
    print(f"  Sermaye    : ${cfg.initial_capital:,.0f} → ${bt.cash:,.2f}  (compounding={cfg.compounding})")
    smode = (f"%{cfg.max_position_pct*100:.0f}/poz" if cfg.compounding
             else f"${cfg.initial_capital*cfg.max_position_pct:,.0f}/poz sabit")
    print(f"  Boyut/Poz  : {smode} · max {cfg.max_positions} poz")
    print(f"  ROI={mt['roi']:.2f}%  SPY={mt['spy_roi']:.2f}%  Alpha={mt['roi']-mt['spy_roi']:.2f}%")
    print(f"  MaxDD={mt['max_dd']:.2f}%  Win={mt['win_rate']}%  PF={mt['profit_factor']}  İşlem(bacak)={len(bt.trades)}")
    from collections import Counter
    print(f"  Çıkış dağılımı: {dict(Counter(t.outcome for t in bt.trades))}")
    return bt, mt


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
    print(f"  CSV → {path} ({len(bt.trades)} satır)")


# Market'i bir kez indir (iki backtest aynı evren+tarih → paylaş)
c0 = base_cfg()
market = s.download_and_align_data(c0)

# #1 — %10/poz (compounding), max 10
c1 = base_cfg()
c1.compounding = True
c1.max_position_pct = 0.10
c1.max_positions = 10
bt1, _ = run(c1, market, "#1 · %10/poz (compounding) · max 10 poz")
write_csv(bt1, os.path.join(OUT, "qswing_hibrit_2026_pct10_max10.csv"))

# #2 — $1000/poz sabit (compounding YOK), max 20
c2 = base_cfg()
c2.compounding = False
c2.initial_capital = 100_000.0
c2.max_position_pct = 0.01          # 100k × %1 = $1000 sabit (clamp'siz, doğrudan Config)
c2.max_positions = 20
bt2, _ = run(c2, market, "#2 · $1000/poz sabit · max 20 poz")
write_csv(bt2, os.path.join(OUT, "qswing_hibrit_2026_usd1000_max20.csv"))

print("\nBitti.")

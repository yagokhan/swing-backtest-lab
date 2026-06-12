#!/usr/bin/env python3
"""KRİPTO 1 SAATLİK barlar: aynı yöntem, hızlı zaman ölçeği — bar-sayısı semantiği.

Günlükteki TÜM parametreler bar cinsinden aynen taşınır (felsefe: strateji BAR'larla
tanımlı, zaman ölçeği bir düğme): SMA200=200 saat (~8 gün) · 40-bar kırılımı=40 saat ·
HIGH52/LOW52=365 saat (~15 gün tepe/dip) · RET60=60 saat · EMA8/21 saatlik.
Sonuç: günler süren hızlı swing işlemleri (günlükte haftalar).

Oynaklık kilidi 1h için YENİDEN ölçülür (günlük 2.5 saatlikte anlamsız —
BTC 1h ATR20% medyanı ~0.56): ızgara {kapalı, 0.45, 0.60, 0.80}.
Kısa funding bar-başına ölçeklenir (bars_per_day=24 → yine 3bps/GÜN).
Komisyon AYNI (10bps/bacak) — hızlı sistemde maliyet oranı büyür; sonuçlar bunu içerir.

Kullanım: python3 backtests/run_crypto_1h_backtests.py
Çıktı:  backtests/crypto_1h_SUMMARY.csv
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
NOW = pd.Timestamp.now()
WARMUP_BARS = 800            # HIGH52(365h) + SMA200 + pay (≈33 gün 1h barı)


def long_cfg_1h(start_date="", lock=None):
    cfg = champion_long_cfg(start_date=start_date)
    cfg.interval = "1h"
    cfg.period = "1y"
    cfg.warmup_calendar_buffer = 60          # 60 gün ≈ 1440 bar > warmup (günlükteki 420 aşırı olur)
    cfg.warmup_bars = WARMUP_BARS
    cfg.disk_cache = False                   # 1h market pickle'ı ~200MB — CSV önbelleği yeterli
    if lock is None:
        cfg.regime_atr_filter = False        # 1h için kilit ızgarayla ölçülür; varsayılan KAPALI
    else:
        cfg.regime_atr_filter = True; cfg.regime_atr_threshold = lock
    return cfg


def short_p_1h(start_date):
    return ShortParams(start_date=start_date, bars_per_day=24, warmup_bars=WARMUP_BARS)


cfg0 = long_cfg_1h()
cfg0.universe = load_pinned_universe()
market = s.download_and_align_data(cfg0)
print(f"İndirme tamam: {len(market['data'])} coin · {len(market['calendar'])} saatlik bar\n")

WINDOWS = [("1y", 365), ("6mo", 182), ("3mo", 91)]
rows = []
hdr = f"{'pencere':7s} {'taraf':22s} {'ROI':>8s} {'BTC':>7s} {'Alpha':>7s} {'DD':>7s} {'Win':>5s} {'PF':>6s} {'işlem':>6s}"
print(hdr)


EMO2KEY = {"🟢": "long", "🔻": "short", "⚖️": "combined"}


def emit(window, side, locklbl, m, extra=""):
    pf = m["profit_factor"]
    print(f"{window:7s} {side:22s} {m['roi']:7.1f}% {m['spy_roi']:6.1f}% "
          f"{m['roi']-m['spy_roi']:6.1f} {m['max_dd']:6.1f}% {m['win_rate']:4.0f}% "
          f"{(999.0 if pf == float('inf') else pf):6.2f} {m['trades']:6d}{extra}")
    eq = m["equity"]
    rows.append([EMO2KEY.get(side.split(" ")[0], side.split(" ")[0]), locklbl, window,
                 eq.index[0].strftime("%Y-%m-%d %H:%M"), eq.index[-1].strftime("%Y-%m-%d %H:%M"),
                 round(m["roi"], 2), round(m["spy_roi"], 2), round(m["roi"] - m["spy_roi"], 2),
                 round(m["max_dd"], 2), round(m["win_rate"], 1),
                 (None if pf == float("inf") else round(pf, 3)), m["trades"],
                 m.get("long_trades"), m.get("short_trades")])


for wl, days in WINDOWS:
    sd = (NOW - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    bt = s.Swing2Backtester(long_cfg_1h(sd), market=market); bt.run()
    emit(wl, "🟢 uzun (kilitsiz)", "kapalı", bt.metrics())
    sb = ShortBacktester(market, short_p_1h(sd)).run()
    m = sb.metrics(); m["spy_roi"] = m.pop("bench_roi")
    emit(wl, "🔻 kısa (kilitsiz)", "kapalı", m)
    cb = CombinedBacktester(market, short_p_1h(sd), long_cfg_1h(sd)).run()
    m = cb.metrics(); m["spy_roi"] = m.pop("bench_roi")
    emit(wl, "⚖️ birleşik", "kapalı", m,
         f"  (U:{m['long_trades']}/{m['long_pnl']:+,.0f}$ · K:{m['short_trades']}/{m['short_pnl']:+,.0f}$)")
    print()

# kilit ızgarası (uzun, 1y) — BTC 1h ATR20% medyanı ~0.56 etrafında ölçülmüş eşikler
sd = (NOW - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
for thr in (0.45, 0.60, 0.80):
    bt = s.Swing2Backtester(long_cfg_1h(sd, lock=thr), market=market); bt.run()
    emit("1y", f"🟢 uzun (kilit {thr})", f"{thr}", bt.metrics())

with open(os.path.join(OUT, "crypto_1h_SUMMARY.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["side", "lock", "period", "start", "end", "roi_pct", "bench_roi_pct",
                "alpha_pct", "max_dd_pct", "win_rate_pct", "profit_factor", "trades",
                "long_trades", "short_trades"])
    w.writerows(rows)
print(f"\n{len(rows)} koşu · crypto_1h_SUMMARY.csv → {OUT}")

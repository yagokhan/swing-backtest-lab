"""Regime breakdown for the debiased (systematic RS top-50) strategy.
Loads the market ONCE over the full span, then runs the same champion config
over several sub-windows (yearly + full) to expose regime-dependence.
The watchlist is point-in-time per date, so reusing one market dict across
windows introduces no leakage."""
import wf_validate as wf
import swing2_backtest as sb

WINDOWS = [
    ("2021 H2 (chop)",   "2021-06-18", "2021-12-31"),
    ("2022 (bear)",      "2022-01-01", "2022-12-31"),
    ("2023 (recovery)",  "2023-01-01", "2023-12-31"),
    ("2024 (bull)",      "2024-01-01", "2024-12-31"),
    ("2025 (bull)",      "2025-01-01", "2025-12-31"),
    ("2026 YTD",         "2026-01-01", ""),
    ("FULL 5y",          "2021-06-18", ""),
]

# load market once (downloads ~373 names), RS universe on
base = wf.champion_cfg(sb.UNIVERSE_PRESETS["sp500_ndx"], use_rs=True)
base.start_date = "2021-06-18"; base.end_date = ""
market = sb.load_market(base)

print()
print("=== REJIM KIRILIMI · sistematik RS top-50 · 20-slot/%5 · $20k ===")
print("%-18s %8s %8s %8s %8s %6s %7s" % ("PENCERE","Getiri%","SPY%","Alpha","MaxDD%","PF","Islem"))
print("-" * 72)
rows = []
for label, start, end in WINDOWS:
    cfg = wf.champion_cfg(sb.UNIVERSE_PRESETS["sp500_ndx"], use_rs=True)
    m = wf.run_window(market, cfg, start, end)
    pf = "%.2f" % m["profit_factor"] if m["profit_factor"] != float("inf") else "inf"
    print("%-18s %+8.1f %+8.1f %+8.1f %+8.1f %6s %7d"
          % (label, m["roi"], m["spy_roi"], m["alpha"], m["max_dd"], pf, m["trades"]))
    rows.append((label, m))

# tally: how many windows beat SPY?
yearly = [r for r in rows if r[0] != "FULL 5y"]
beat = sum(1 for _, m in yearly if m["roi"] > m["spy_roi"])
pos = sum(1 for _, m in yearly if m["roi"] > 0)
print("-" * 72)
print("Yillik pencereler: %d/%d SPY'i gecti · %d/%d pozitif getiri"
      % (beat, len(yearly), pos, len(yearly)))

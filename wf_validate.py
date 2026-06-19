# wf_validate.py
"""Walk-forward validation for the RS-universe debias.
In-sample (tune): 2021-06-18 → 2023-12-31. Out-of-sample (report): 2024-01-01 → end.
Dual benchmark: must beat SPY AND the random-95 baseline (+9.7%)."""
import pandas as pd
import swing2_backtest as sb

IN_SAMPLE = ("2021-06-18", "2023-12-31")
OUT_SAMPLE = ("2024-01-01", None)
RANDOM_95_BASELINE = 9.7        # measured 2026-06-19 selection-bias test (5y); informational bar

def assert_no_leakage(in_sample_end, oos_start):
    if pd.Timestamp(oos_start) <= pd.Timestamp(in_sample_end):
        raise ValueError(f"OOS start {oos_start} must be after in-sample end {in_sample_end}")

def champion_cfg(universe, use_rs=True):
    c = sb.Config()
    c.entry_mode = "qswing_breakout"; c.qswing_breakout_lb = 63
    c.exit_mode = "atr_full"; c.atr_trail_mult = 3.25
    c.initial_capital = 20000; c.compounding = True
    c.max_positions = 20; c.max_position_pct = 0.05
    c.use_earnings = False
    c.use_rs_universe = use_rs
    c.rs_pool = sb.UNIVERSE_PRESETS["sp500_ndx"]
    c.rs_n = 50
    c.universe = universe
    return c

def run_window(market, cfg, start, end):
    cfg.start_date = start; cfg.end_date = end or ""
    bt = sb.Swing2Backtester(cfg, market=market)
    bt.run()
    return bt.metrics()

def main():
    assert_no_leakage(IN_SAMPLE[1], OUT_SAMPLE[0])
    # Pool data loaded ONCE over the full span; windows slice the same frames.
    cfg = champion_cfg(sb.UNIVERSE_PRESETS["sp500_ndx"], use_rs=True)
    cfg.start_date = IN_SAMPLE[0]; cfg.end_date = ""          # download full span
    market = sb.load_market(cfg)

    print("=== IN-SAMPLE (tune only) 2021-06-18 → 2023-12-31 ===")
    is_m = run_window(market, champion_cfg(cfg.universe), *IN_SAMPLE)
    print("  roi %+.1f%% | alpha %+.1f | DD %+.1f | PF %.2f"
          % (is_m["roi"], is_m["alpha"], is_m["max_dd"], is_m["profit_factor"]))

    print("=== OUT-OF-SAMPLE (REPORT) 2024-01-01 → end ===")
    oos = run_window(market, champion_cfg(cfg.universe), *OUT_SAMPLE)
    print("  roi %+.1f%% | SPY %+.1f%% | alpha %+.1f | DD %+.1f | PF %.2f"
          % (oos["roi"], oos["spy_roi"], oos["alpha"], oos["max_dd"], oos["profit_factor"]))

    beats_spy = oos["roi"] > oos["spy_roi"]
    beats_rand = oos["roi"] > RANDOM_95_BASELINE
    print("--- DUAL-BENCHMARK GATE ---")
    print("  beats SPY: %s | beats random-95 (+%.1f%%): %s" % (beats_spy, RANDOM_95_BASELINE, beats_rand))
    print("  VERDICT: %s" % ("DEBIASED EDGE CONFIRMED" if (beats_spy and beats_rand)
                             else "NO GENERALIZABLE EDGE — stop or pivot"))

if __name__ == "__main__":
    main()

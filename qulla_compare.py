"""3 çıkış felsefesi · aynı RS-evren · aynı pencereler · aynı qswing-63 giriş.
Tek değişen değişken = exit_mode. Qulla'yı (MA-runner trail + partial) regime
tablosuna ekler; saf-ATR braketi ve şamdan-trail ile yan yana koyar.
Market BİR kez yüklenir; her config aynı point-in-time watchlist'i kullanır (sızıntı yok)."""
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

POOL = sb.UNIVERSE_PRESETS["sp500_ndx"]

def cfg_bracket():           # senin tarif ettiğin: saf ATR sabit kâr-al/zarar-kes, trailing YOK
    c = wf.champion_cfg(POOL, use_rs=True)
    c.exit_mode = "atr_regime"; c.atr_target_mult = 3.0
    return c

def cfg_chandelier():        # debias şampiyonu: tam-pozisyon şamdan trail (peak - 3.25xATR)
    c = wf.champion_cfg(POOL, use_rs=True)
    c.exit_mode = "atr_full"; c.atr_trail_mult = 3.25
    return c

def cfg_qulla8():            # Qulla(sıkı): %50 kısmi @+2R, kalan runner 8-EMA(kapanış) trail, LOW10 felaket stopu
    c = wf.champion_cfg(POOL, use_rs=True)
    c.exit_mode = "ma_trail"; c.ma_trail_type = "ema"
    c.ma_confirm_close = True; c.ma_keep_initial_stop = True
    c.partial_tp = True; c.partial_pct = 0.5; c.partial_rr = 2.0
    return c

def cfg_qulla21():           # Qulla(sadık): yarı +2R'de banka (limit), kalan yarı 21-EMA(kapanış) runner
    c = wf.champion_cfg(POOL, use_rs=True)
    c.exit_mode = "split"
    c.split_a = "target"; c.split_a_param = 2.0     # ilk yarı: +2R sabit hedef
    c.split_b = "ema21";  c.split_b_param = 0.0     # kalan yarı: 21-EMA runner
    c.split_ratio = 0.5
    return c

# market BİR kez (tam span), RS evreni açık
base = cfg_chandelier(); base.start_date = "2021-06-18"; base.end_date = ""
market = sb.load_market(base)

print()
print("=== CIKIS FELSEFESI KARSILASTIRMASI · RS top-50 · qswing-63 · 20-slot/%5/$20k ===")
print("%-18s %8s %8s %8s %8s %8s" % ("PENCERE", "Braket%", "Samdan%", "Qul-8%", "Qul-21%", "SPY%"))
print("-" * 74)
rows = []
for label, start, end in WINDOWS:
    mb  = wf.run_window(market, cfg_bracket(),    start, end)
    mc  = wf.run_window(market, cfg_chandelier(), start, end)
    q8  = wf.run_window(market, cfg_qulla8(),     start, end)
    q21 = wf.run_window(market, cfg_qulla21(),    start, end)
    spy = mb["spy_roi"]
    print("%-18s %+8.1f %+8.1f %+8.1f %+8.1f %+8.1f"
          % (label, mb["roi"], mc["roi"], q8["roi"], q21["roi"], spy))
    rows.append((label, mb, mc, q8, q21, spy))

print("-" * 74)
yearly = [r for r in rows if r[0] != "FULL 5y"]
def beat(idx): return sum(1 for r in yearly if r[idx]["roi"] > r[5])
def pos(idx):  return sum(1 for r in yearly if r[idx]["roi"] > 0)
print("SPY'i gecen yil:  Braket %d/6 · Samdan %d/6 · Qul-8 %d/6 · Qul-21 %d/6" % (beat(1), beat(2), beat(3), beat(4)))
print("Pozitif yil:      Braket %d/6 · Samdan %d/6 · Qul-8 %d/6 · Qul-21 %d/6" % (pos(1), pos(2), pos(3), pos(4)))
print()
print("--- Profit Factor / MaxDD / Islem (FULL 5y) ---")
_, fb, fc, f8, f21, _ = rows[-1]
for name, m in [("Braket  (saf ATR)", fb), ("Samdan  (atr_full 3.25x)", fc),
                ("Qulla-8  (8-EMA runner)", f8), ("Qulla-21 (21-EMA runner)", f21)]:
    pf = "%.2f" % m["profit_factor"] if m["profit_factor"] != float("inf") else "inf"
    print("  %-26s PF %5s · MaxDD %+6.1f · Islem %4d" % (name, pf, m["max_dd"], m["trades"]))

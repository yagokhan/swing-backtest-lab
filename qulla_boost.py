"""Qulla-21'i güçlendirme denemesi: felaket-stop + oynaklık şalteri.
Baz = split(target+2R / 21-EMA runner). Her varyantı aynı evren/pencerelerde koşturur.
Karar: risk-ayarlı (PF↑, MaxDD↓) iyileşme getiriyi öldürmeden geliyorsa KORU, yoksa AT."""
import wf_validate as wf
import swing2_backtest as sb

WINDOWS = [
    ("2021 H2", "2021-06-18", "2021-12-31"),
    ("2022 bear", "2022-01-01", "2022-12-31"),
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("2026 YTD", "2026-01-01", ""),
    ("FULL 5y", "2021-06-18", ""),
]
POOL = sb.UNIVERSE_PRESETS["sp500_ndx"]

def base():
    c = wf.champion_cfg(POOL, use_rs=True)
    c.exit_mode = "split"
    c.split_a = "target"; c.split_a_param = 2.0
    c.split_b = "ema21";  c.split_b_param = 0.0
    c.split_ratio = 0.5
    return c

def v_stop():
    c = base(); c.split_catastrophe_stop = True; return c

def v_regime(th):
    c = base(); c.regime_atr_filter = True; c.regime_atr_threshold = th; return c

def v_both(th):
    c = base(); c.split_catastrophe_stop = True
    c.regime_atr_filter = True; c.regime_atr_threshold = th; return c

VARIANTS = [
    ("BAZ (target+21EMA)", base()),
    ("+felaket-stop",       v_stop()),
    ("+salter@1.5",         v_regime(1.5)),
    ("+salter@1.8",         v_regime(1.8)),
    ("+stop+salter@1.5",    v_both(1.5)),
    ("+stop+salter@1.8",    v_both(1.8)),
]

b = base(); b.start_date = "2021-06-18"; b.end_date = ""
market = sb.load_market(b)

# her varyant için tüm pencereler
full = {}
print()
print("=== QULLA-21 GUCLENDIRME · RS top-50 · qswing-63 ===")
hdr = "%-20s" % "VARYANT" + "".join("%9s" % w[0] for w in WINDOWS)
print(hdr); print("-" * len(hdr))
for name, _cfg in VARIANTS:
    cells = []
    for label, start, end in WINDOWS:
        c = {  # taze config (run_window start/end mutasyonu var)
            "BAZ (target+21EMA)": base, "+felaket-stop": v_stop,
            "+salter@1.5": lambda: v_regime(1.5), "+salter@1.8": lambda: v_regime(1.8),
            "+stop+salter@1.5": lambda: v_both(1.5), "+stop+salter@1.8": lambda: v_both(1.8),
        }[name]()
        m = wf.run_window(market, c, start, end)
        cells.append(m)
    full[name] = cells[-1]
    print("%-20s" % name + "".join("%+9.1f" % m["roi"] for m in cells))

print("-" * len(hdr))
print("\n--- FULL 5y risk metrikleri ---")
print("%-20s %8s %8s %8s %8s" % ("VARYANT", "Getiri%", "PF", "MaxDD%", "Islem"))
for name, _ in VARIANTS:
    m = full[name]
    pf = "%.2f" % m["profit_factor"] if m["profit_factor"] != float("inf") else "inf"
    calmar = m["roi"] / abs(m["max_dd"]) if m["max_dd"] else 0
    print("%-20s %+8.1f %8s %+8.1f %8d   (getiri/DD=%.2f)"
          % (name, m["roi"], pf, m["max_dd"], m["trades"], calmar))

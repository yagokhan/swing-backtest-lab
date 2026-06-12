# -*- coding: utf-8 -*-
"""Swing2 deney koşucusu — şampiyon etrafında TEST EDİLMEMİŞ boyutlar + ayrık-pencere doğrulama.
Mevcut sisteme DOKUNMAZ: swing2_backtest yalnız import edilir, Config varsayılanları değişmez.
Kullanım: python3 exp_swing2.py phaseA   (sonuç: swing2_out/exp_a_results.csv)
"""
import copy, json, sys, time
import pandas as pd
import swing2_backtest as s

OUT_DIR = "/home/gokhan/swing2_out"

# Tek 5y FMP indirmesi → tüm pencereler takvim diliminden (run() start/end_date destekler)
def build_market():
    cfg = s.Config()
    cfg.period = "5y"
    cfg.price_source = "fmp"
    cfg.disk_cache = True
    cfg.use_earnings = False        # calibrate_fmp ile aynı (baz kıyas tutarlı)
    cfg.per_ticker_download = False
    print("===== 5y FMP verisi yükleniyor =====", flush=True)
    market = s.download_and_align_data(cfg)
    return cfg, market

# Pencereler: FULL+L2Y kalibrasyonla kıyas için; W1/W2/W3 AYRIK doğrulama dilimleri
WINDOWS = {
    "FULL": ("", ""),                       # ≈ calib 5y
    "L2Y":  ("2024-06-12", ""),             # ≈ calib 2y (son 2 yıl)
    "W1":   ("2021-01-01", "2022-12-31"),   # 2022 ayısı dahil
    "W2":   ("2023-01-01", "2024-12-31"),
    "W3":   ("2025-01-01", ""),
}
ALL_WINS = list(WINDOWS.keys())

CHAMPION = {}   # Config varsayılanı ZATEN şampiyon (min_score=16, rr=2.0, stop=1.5, trail=2.5, strict_entry)


def run_one(base_cfg, market, name, overrides, windows=ALL_WINS):
    rows = []
    for w in windows:
        cfg = copy.deepcopy(base_cfg)
        for k, v in overrides.items():
            setattr(cfg, k, v)
        cfg.start_date, cfg.end_date = WINDOWS[w]
        t0 = time.time()
        bt = s.Swing2Backtester(cfg, market=market)
        bt.run()
        mt = bt.metrics()
        eq = mt.pop("equity")
        yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
        cagr = ((1 + mt["roi"] / 100) ** (1 / yrs) - 1) * 100
        rows.append({"exp": name, "win": w, "params": json.dumps(overrides, ensure_ascii=False),
                     "roi": round(mt["roi"], 2), "cagr": round(cagr, 2),
                     "dd": round(mt["max_dd"], 2), "pf": round(mt["profit_factor"], 2),
                     "winrate": round(mt["win_rate"], 1), "n": mt["trades"]})
        print(f"  [{name:<28}] {w:<5} ROI {mt['roi']:+7.2f}%  CAGR {cagr:+6.2f}%  DD {mt['max_dd']:6.2f}%  "
              f"PF {mt['profit_factor']:.2f}  n={mt['trades']}  ({time.time()-t0:.1f}s)", flush=True)
    return rows


# ---- FAZ A: tek-faktör deneyleri (şampiyon etrafında, FMP'de hiç taranmamış boyutlar) ----
PHASE_A = [
    ("baseline_champion", CHAMPION),
    # 1) Pozisyon genişliği (max_positions × pct) — canlı paper "tüm sinyaller eşit-ağırlık" sorusu
    ("breadth_3x33", {"max_positions": 3, "max_position_pct": 0.33}),
    ("breadth_4x25", {"max_positions": 4, "max_position_pct": 0.25}),
    ("breadth_7x14", {"max_positions": 7, "max_position_pct": 0.14}),
    ("breadth_8x125", {"max_positions": 8, "max_position_pct": 0.125}),
    ("breadth_10x10", {"max_positions": 10, "max_position_pct": 0.10}),
    ("breadth_15x066", {"max_positions": 15, "max_position_pct": 0.0667}),
    # 2) min_score (FMP'de yalnız 16 tarandı)
    ("score_14", {"min_score": 14}),
    ("score_15", {"min_score": 15}),
    ("score_17", {"min_score": 17}),
    ("score_18", {"min_score": 18}),
    # 3) Risk-bazlı boyutlama
    ("sizing_risk_1.0", {"sizing_mode": "risk", "risk_per_trade_pct": 1.0}),
    ("sizing_risk_1.5", {"sizing_mode": "risk", "risk_per_trade_pct": 1.5}),
    ("sizing_risk_2.0", {"sizing_mode": "risk", "risk_per_trade_pct": 2.0}),
    # 4) SPY oynaklık kilidi (v7 rejim filtresi — hiç kalibre edilmedi)
    ("regime_atr_1.5", {"regime_atr_filter": True, "regime_atr_threshold": 1.5}),
    ("regime_atr_1.8", {"regime_atr_filter": True, "regime_atr_threshold": 1.8}),
    ("regime_atr_2.2", {"regime_atr_filter": True, "regime_atr_threshold": 2.2}),
    # 5) Chase kapısı (SMA20'den aşırı uzaklık)
    ("chase_10", {"max_dist_sma20": 0.10}),
    ("chase_15", {"max_dist_sma20": 0.15}),
    ("chase_25", {"max_dist_sma20": 0.25}),
    # 6) Trailing devreye girme eşiği
    ("trail_after_0.5", {"trail_after_r": 0.5}),
    ("trail_after_1.5", {"trail_after_r": 1.5}),
    ("trail_after_2.0", {"trail_after_r": 2.0}),
    # 7) Partial / hedef varyantları (calib'de pct=0.5 trig=2.0 sabitti)
    ("partial_33", {"partial_pct": 0.33}),
    ("partial_67", {"partial_pct": 0.67}),
    ("p15_rr30", {"partial_rr": 1.5, "rr_target": 3.0}),
    ("p20_rr30", {"partial_rr": 2.0, "rr_target": 3.0}),
    ("p20_rr40", {"partial_rr": 2.0, "rr_target": 4.0}),
    ("runner_no_target", {"rr_target": 99.0, "partial_rr": 2.0}),   # hedef yok: partial@2R + trail
    # 8) Saf ATR-trail (tam pozisyon, partial yok)
    ("atr_full_2.5", {"exit_mode": "atr_full", "atr_trail_mult": 2.5}),
    ("atr_full_3.0", {"exit_mode": "atr_full", "atr_trail_mult": 3.0}),
    ("atr_full_3.5", {"exit_mode": "atr_full", "atr_trail_mult": 3.5}),
]


def phase(name, exps, out_csv):
    base_cfg, market = build_market()
    all_rows = []
    t0 = time.time()
    for i, (nm, ov) in enumerate(exps, 1):
        print(f"\n[{i}/{len(exps)}] {nm}  {ov}", flush=True)
        all_rows += run_one(base_cfg, market, nm, ov)
        pd.DataFrame(all_rows).to_csv(out_csv, index=False)   # ara kayıt
    print(f"\n{name} bitti ({(time.time()-t0)/60:.1f} dk) → {out_csv}", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "phaseA"
    if mode == "phaseA":
        phase("FAZ A", PHASE_A, f"{OUT_DIR}/exp_a_results.csv")
    elif mode == "phaseB":
        import exp_swing2_b as b   # Faz B ayrı dosyada tanımlanacak
        phase("FAZ B", b.PHASE_B, f"{OUT_DIR}/exp_b_results.csv")
    elif mode == "phaseC":
        import exp_swing2_c as c
        phase("FAZ C", c.PHASE_C, f"{OUT_DIR}/exp_c_results.csv")
    elif mode == "phaseD":
        import exp_swing2_d as d
        phase("FAZ D", d.PHASE_D, f"{OUT_DIR}/exp_d_results.csv")

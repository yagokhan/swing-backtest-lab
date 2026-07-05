"""/adaylar sayfası için özsermaye eğrileri: 4 sistem × 5 pencere + SPY (100'e endeksli).
Çıktı: /home/gokhan/dashboard_static/adaylar_curves.js  (const CURVES = {...})
Kontrol: her koşunun ROI'si combo_battery3 çıktısıyla birebir tutmalı."""
import copy
import json
import os
import pickle
import sys

sys.path.insert(0, "/home/gokhan")
os.chdir("/home/gokhan")
import pandas as pd
import swing2_backtest as s

SCRATCH = "/tmp/claude-1000/-home-gokhan/a99038e3-500e-4af2-89a4-63a0d6e59f9c/scratchpad"

cfg = s.Config()
cfg.period = "5y"; cfg.price_source = "fmp"; cfg.disk_cache = True
cfg.use_earnings = False; cfg.per_ticker_download = False
cfg.entry_mode = "qswing_breakout"; cfg.qswing_breakout_lb = 63
cfg.exit_mode = "split"; cfg.split_a = "target"; cfg.split_a_param = 2.0
cfg.split_b = "ema21"; cfg.split_b_param = 0.0
cfg.split_ratio = 0.6
cfg.use_rs_universe = True; cfg.rs_n = 50
cfg.rs_pool = s.UNIVERSE_PRESETS["sp500_ndx"]; cfg.universe = cfg.rs_pool
cfg.max_positions = 20; cfg.compounding = True; cfg.liquidate_at_end = True
cfg.max_position_pct = 0.075; cfg.free_runner_slots = True

with open("swing2_cache/market_5y_152dab0ec647.pkl", "rb") as fh:
    market = pickle.load(fh)
market = s.attach_watchlist(market, cfg)
print(f"cache sabit: 152dab0ec647 · {len(market['data'])} hisse", flush=True)

BR = pickle.load(open("/home/gokhan/swing2_cache/breadth.pkl", "rb"))

class KX(s.Swing2Backtester):
    WIRE = ""; BRDEF = None
    RANK = ""

    def _common(self, date):
        c = super()._common(date)
        if self.WIRE and self.BRDEF:
            name, thr = self.BRDEF
            v = BR[name].get(date)
            if v is not None and not pd.isna(v):
                b = bool(v > thr) if name.startswith("MM") else bool(v >= thr)
                spy = c["spy_above_sma200"]
                c["spy_above_sma200"] = (spy and b) if self.WIRE == "and" else (spy or b)
        return c

    def _rank_key(self, qscore, row, dist):
        if not self.RANK:
            return qscore
        a = row.get("ATR_PCT"); a = float(a) if a is not None and not pd.isna(a) else 0.0
        if self.RANK == "atr":
            return a
        if self.RANK.startswith("atrcap"):
            return min(a, float(self.RANK[6:]))
        if self.RANK.startswith("blend"):
            div = float(self.RANK[5:])
            return qscore / 100.0 + a / div
        return qscore

    def _step(self, date):
        if not self.RANK:
            return super()._step(date)
        cfg = self.cfg
        self._manage(date)
        common = self._common(date)
        if (common["spy_above_sma200"] and not self._vol_regime_locked(common)
                and self._slot_count() < cfg.max_positions and self.cash >= self._size(date)):
            cands = []
            spy_ret60 = self.spy.loc[date, "RET60"]
            for sym, df in self.data.items():
                if sym in self.positions: continue
                if not self._in_watchlist(sym, date): continue
                row = df.loc[date]
                if (pd.isna(row["Close"]) or pd.isna(row["SMA200"]) or row["Close"] <= row["SMA200"]
                        or row["Close"] <= row["SMA50"] or row["Close"] <= row["SMA20"]
                        or pd.isna(row["SLOPE200"]) or row["SLOPE200"] <= 0): continue
                plan = s.compute_trade_plan(row, cfg)
                dist = (row["Close"] - row["SMA20"]) / row["SMA20"]
                rs = self._qswing_entry_ok(row, spy_ret60)
                if rs is None: continue
                _risk = plan["entry"] - plan["stop"]
                _rec = {"rs": rs,
                        "dist_52h_pct": (row["Close"] / row["HIGH52"] - 1) * 100,
                        "dist_sma20_pct": dist * 100,
                        "risk_pct": (_risk / plan["entry"] * 100) if plan["entry"] else None}
                qscore, _ = s._qswing_priority_score(_rec)
                if cfg.qswing_min_score > 0 and qscore < cfg.qswing_min_score: continue
                cands.append((self._rank_key(qscore, row, dist), -dist, sym, row, plan))
            cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
            for total, _nd, sym, row, plan in cands:
                if self._slot_count() >= cfg.max_positions or self.cash < self._size(date): break
                self._open(sym, date, row, plan, total)
        self.equity_curve.append((date, self._equity(date)))

VARS = [
    ("baz",   {}),
    ("atr",   {"RANK": "atr"}),
    ("tavan", {"RANK": "atrcap4.0", "WIRE": "and", "BRDEF": ("A200", 50.0)}),
    ("blend", {"RANK": "blend10",   "WIRE": "and", "BRDEF": ("A200", 50.0)}),
]
WINS = [("5y tam", "2021-05-01", ""), ("ayı 21-23", "2021-05-01", "2023-07-01"),
        ("topar 23-25", "2023-07-01", "2025-07-01"),
        ("son 2y", "2024-07-01", ""), ("son 1y", "2025-07-01", "")]

CURVES = {}
for wi, (wn, sd, ed) in enumerate(WINS):
    entry = {}
    dates = None
    spy_vals = None
    for key, ov in VARS:
        c = copy.deepcopy(cfg); c.start_date = sd; c.end_date = ed
        KX.WIRE = ov.get("WIRE", ""); KX.BRDEF = ov.get("BRDEF"); KX.RANK = ov.get("RANK", "")
        bt = KX(c, market=market); bt.run()
        m = bt.metrics()
        ds = [d for d, _ in bt.equity_curve]
        eq = [e for _, e in bt.equity_curve]
        base = eq[0]
        entry[key] = [round(e / base * 100.0, 2) for e in eq]
        if dates is None:
            dates = ds
            spy_close = bt.spy["Close"].reindex(ds).ffill()
            sb = float(spy_close.iloc[0])
            spy_vals = [round(float(v) / sb * 100.0, 2) for v in spy_close]
        print(f"  {wn:>12} · {key:>5}: roi {m['roi']:+7.1f} · {len(ds)} gün · eğri son {entry[key][-1]}", flush=True)
    entry["d"] = [str(d)[:10] for d in dates]
    entry["spy"] = spy_vals
    CURVES[f"w{wi}"] = entry

out = "/home/gokhan/dashboard_static/adaylar_curves.js"
with open(out, "w") as fh:
    fh.write("const CURVES = " + json.dumps(CURVES, separators=(",", ":")) + ";\n")
print(f"yazıldı → {out} ({os.path.getsize(out)//1024} KB)", flush=True)
print("BITTI", flush=True)

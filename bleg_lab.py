"""B-bacağı (runner) anatomisi: split çıkışta %40'lık dilim (kapanış<21-EMA).
Dört yöntem (baz/atr/tavan/blend) × 5 pencere. Her B bacağının kaderi:
  · EMA21  → gerçek runner çıkışı (kapanış 21-EMA altına indi) — kârda/zararda?
  · EOD    → pencere sonunda hâlâ trend, kural tetiklemeden tasfiye (kalıntı).
Motor DEĞİŞMEZ — yalnız _close_leg/_close override'ı YAN kayıt tutar (self.legrec);
nakit/işlem/ROI motorun kendisinden gelir → sadakat metrics().roi ile kanıtlanır.

  python3 bleg_lab.py --run       # analiz + sadakat + JSON
  python3 bleg_lab.py --report    # adaylar.html bölümünü üret/güncelle
"""
import argparse
import copy
import json
import os
import pickle
import sys

sys.path.insert(0, "/home/gokhan")
os.chdir("/home/gokhan")
import pandas as pd
import swing2_backtest as s

CACHE = "swing2_cache/market_5y_152dab0ec647.pkl"
BREADTH_PKL = "swing2_cache/breadth.pkl"
ADAYLAR = "/home/gokhan/dashboard_static/adaylar.html"
OUT_JSON = "/home/gokhan/swing2_out/bleg_results.json"

WINS = [("5y tam", "2021-05-01", ""), ("ayı 21-23", "2021-05-01", "2023-07-01"),
        ("topar 23-25", "2023-07-01", "2025-07-01"),
        ("son 2y", "2024-07-01", ""), ("son 1y", "2025-07-01", "")]

VARS = [
    ("baz",   {}),
    ("atr",   {"RANK": "atr"}),
    ("tavan", {"RANK": "atrcap4.0", "WIRE": "and", "BRDEF": ("A200", 50.0)}),
    ("blend", {"RANK": "blend10",   "WIRE": "and", "BRDEF": ("A200", 50.0)}),
]

# Sadakat kapıları: /adaylar "Dönem dönem getiri" tablosu (sabit cache, gen_adaylar_curves)
EXP_ROI = {
    "baz":   [74.7,   5.9, 29.5, 70.9, 46.6],
    "atr":   [181.5, 10.6, 43.8, 80.2, 50.9],
    "tavan": [208.1, 16.4, 46.6, 92.2, 47.7],
    "blend": [166.3, 21.3, 43.3, 81.3, 57.4],
}
EXP_N_BLEND = [482, 187, 273, 302, 215]   # blend işlem (bacak) sayısı — batarya

BR = None
MARKET = None


def base_cfg():
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
    return cfg


def load_data():
    global BR, MARKET
    if MARKET is not None:
        return
    BR = pickle.load(open(BREADTH_PKL, "rb"))
    with open(CACHE, "rb") as fh:
        MARKET = pickle.load(fh)
    MARKET = s.attach_watchlist(MARKET, base_cfg())
    print("cache sabit: 152dab0ec647 · %d hisse" % len(MARKET["data"]), flush=True)


class BKX(s.Swing2Backtester):
    """gen_adaylar_curves.KX'in BİREBİR kopyası (4 varyant) + B-bacağı yan kaydı."""
    WIRE = ""; BRDEF = None; RANK = ""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.legrec = []      # {tag,fate,sym,entry_date,exit_date,pnl,pnl_pct,bars}

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
            # baz: motorun kendi _step'i (gen_adaylar_curves baz yolu)
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

    # ---- B-bacağı YAN kaydı (motor davranışı değişmez; super çağrılır) ----
    def _bars(self, sym, entry_date, exit_date):
        idx = self.data[sym].index
        try:
            return int(idx.get_loc(exit_date) - idx.get_loc(entry_date))
        except Exception:
            return None

    def _close_leg(self, sym, pos, leg, date, price, label, slip=None):
        tag = leg["tag"]; edate = pos.entry_date
        super()._close_leg(sym, pos, leg, date, price, label, slip=slip)
        t = self.trades[-1]
        self.legrec.append({"tag": tag, "fate": label, "sym": sym,
                            "entry_date": str(edate)[:10], "exit_date": str(date)[:10],
                            "pnl": round(t.pnl, 2), "pnl_pct": round(t.pnl_pct, 3),
                            "bars": self._bars(sym, edate, date)})

    def _close(self, sym, date, price, outcome, slip=None):
        pos = self.positions.get(sym)
        snap = ([(l["tag"], l["shares"], l["cost"]) for l in getattr(pos, "legs", [])
                 if l["shares"] > 0] if pos is not None else [])
        entry = pos.entry if pos is not None else None
        edate = pos.entry_date if pos is not None else None
        fillp = price * (1 - (self._slip if slip is None else slip))
        super()._close(sym, date, price, outcome, slip=slip)
        for tag, sh, cost in snap:
            self.legrec.append({"tag": tag, "fate": "EOD", "sym": sym,
                                "entry_date": str(edate)[:10], "exit_date": str(date)[:10],
                                "pnl": round(sh * fillp - cost, 2),
                                "pnl_pct": round((fillp / entry - 1) * 100, 3) if entry else 0.0,
                                "bars": self._bars(sym, edate, date)})


def _med(xs):
    return round(float(pd.Series(xs).median()), 2) if xs else None


def analyze():
    load_data()
    out = {"variants": {}, "wins": [w[0] for w in WINS]}
    fid_ok = True
    for key, ov in VARS:
        rows = []
        for wi, (wn, sd, ed) in enumerate(WINS):
            c = copy.deepcopy(base_cfg()); c.start_date = sd; c.end_date = ed
            BKX.WIRE = ov.get("WIRE", ""); BKX.BRDEF = ov.get("BRDEF"); BKX.RANK = ov.get("RANK", "")
            bt = BKX(c, market=MARKET); bt.run()
            m = bt.metrics()
            # --- sadakat: ROI batarya değeriyle birebir; blend'de N de kontrol ---
            eroi = EXP_ROI[key][wi]
            roi_ok = abs(round(m["roi"], 1) - eroi) < 0.05
            n_ok = (m["trades"] == EXP_N_BLEND[wi]) if key == "blend" else True
            fid_ok = fid_ok and roi_ok and n_ok
            # --- B bacağı ---
            B = [r for r in bt.legrec if r["tag"] == "B"]
            ema = [r for r in B if r["fate"] == "EMA21"]
            eod = [r for r in B if r["fate"] == "EOD"]
            win = [r for r in ema if r["pnl"] > 0]
            los = [r for r in ema if r["pnl"] <= 0]
            row = {
                "win": wn, "roi": round(m["roi"], 1), "roi_ok": roi_ok, "n_ok": n_ok,
                "n_ema": len(ema), "n_win": len(win), "n_loss": len(los),
                "win_rate": round(len(win) / max(1, len(ema)) * 100, 1),
                "usd_win": round(sum(r["pnl"] for r in win), 0),
                "usd_loss": round(sum(r["pnl"] for r in los), 0),
                "usd_net": round(sum(r["pnl"] for r in ema), 0),
                "med_win_pct": _med([r["pnl_pct"] for r in win]),
                "med_loss_pct": _med([r["pnl_pct"] for r in los]),
                "big_win_pct": (round(float(pd.Series([r["pnl_pct"] for r in win]).quantile(0.9)), 1)
                                if win else None),
                "best_pct": round(max((r["pnl_pct"] for r in ema), default=0.0), 1),
                "med_hold": _med([r["bars"] for r in ema if r["bars"] is not None]),
                "med_hold_win": _med([r["bars"] for r in win if r["bars"] is not None]),
                "med_hold_loss": _med([r["bars"] for r in los if r["bars"] is not None]),
                # EOD kalıntı (kural tetiklemeden pencere-sonu tasfiyesi)
                "n_eod": len(eod),
                "usd_eod": round(sum(r["pnl"] for r in eod), 0),
                "eod_win_rate": round(sum(1 for r in eod if r["pnl"] > 0) / max(1, len(eod)) * 100, 1),
                "med_eod_pct": _med([r["pnl_pct"] for r in eod]),
            }
            rows.append(row)
            print("  %-6s %-12s roi %+7.1f %s · EMA21 n=%d win%%=%s (K$%s / Z$%s net$%s) "
                  "medW=%s%% medZ=%s%% · EOD n=%d ($%s)" %
                  (key, wn, row["roi"], "OK" if roi_ok and n_ok else "FARK!",
                   row["n_ema"], row["win_rate"], row["usd_win"], row["usd_loss"],
                   row["usd_net"], row["med_win_pct"], row["med_loss_pct"],
                   row["n_eod"], row["usd_eod"]), flush=True)
        out["variants"][key] = {"rows": rows}
    out["fidelity_ok"] = bool(fid_ok)
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    tmp = OUT_JSON + ".tmp"
    _nat = lambda o: o.item() if hasattr(o, "item") else str(o)
    json.dump(out, open(tmp, "w"), ensure_ascii=False, default=_nat)
    os.replace(tmp, OUT_JSON)
    print("\nSADAKAT:", "TÜM ROI/N BATARYA-BİREBİR ✓" if fid_ok else "FARK VAR ✗")
    print("yazıldı:", OUT_JSON)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.run:
        analyze()
    elif a.report:
        import bleg_report
        bleg_report.report()
    else:
        ap.print_help()

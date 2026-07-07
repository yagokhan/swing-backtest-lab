"""splitstop_lab.py — A bacağı (+2R hedef, %60) stop/timeout iterasyonu.

Canlı Aday 3 (blend10 + A200>=%50 VE-freni) kopyası üzerinde A bacağına
stop/timeout/ema21 koruması ekleyip 5-pencere bataryasında kıyaslar.
Motor/canlı DEĞİŞMEZ. Spec: docs/superpowers/specs/2026-07-07-splitA-stop-iterasyon-design.md

SADAKAT ZORUNLU: STOP=None, TIMEOUT=0, AEMA=False iken batarya blend ile
5 pencerede ROI+N birebir olmalı (bkz. EXPECTED). Tutmazsa koşu durur.

Kullanım:
  python3 splitstop_lab.py --selftest   # market verisiz öncelik testleri
  python3 splitstop_lab.py --fidelity   # none == batarya 5/5 kanıtı
  python3 splitstop_lab.py --wave1      # 10 varyant x 5 pencere -> JSON
  python3 splitstop_lab.py --wave2      # kombolar (wave1 JSON'undan seçer)
  python3 splitstop_lab.py --report     # adaylar.html bölümünü üret/güncelle
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
OUT_JSON = "/home/gokhan/swing2_out/splitstop_results.json"
ADAYLAR = "/home/gokhan/dashboard_static/adaylar.html"

WINS = [("5y tam", "2021-05-01", ""), ("ayı 21-23", "2021-05-01", "2023-07-01"),
        ("topar 23-25", "2023-07-01", "2025-07-01"),
        ("son 2y", "2024-07-01", ""), ("son 1y", "2025-07-01", "")]

# Aday 3 batarya referansı (blend, sabit cache): (roi, işlem sayısı)
EXPECTED = [(166.3, 482), (21.3, 187), (43.3, 273), (81.3, 302), (57.4, 215)]

BR = None      # breadth pkl (A200: pd.Series) — load_data doldurur
MARKET = None  # sabit market cache — load_data doldurur


def base_cfg():
    """Aday 3 canlı konfiği (gen_adaylar_curves.py cfg'sinin birebir kopyası)."""
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


class StopKX(s.Swing2Backtester):
    """Aday 3 kopyası (gen_adaylar_curves.KX blend yolu) + A bacağı koruma uzantısı.

    STOP    : None | ("ref", 0.0) -> girişteki plan stopu (pos.stop)
                   | ("atr", k)   -> giriş - k*ATR0 (ATR0 NaN ise pos.stop'a düşer)
    TIMEOUT : N işlem barı (0=kapalı) — +2R gelmezse N. yönetilen barın KAPANIŞINDA çık
    AEMA    : True -> A bacağı da kapanış<EMA21'de çıkar (hangisi önce)
    Öncelik (aynı bar): STOP (gün-içi, kötümser) > +2R hedef (gün-içi limit)
                        > EMA21 (kapanış) > TIMEOUT (kapanış).
    """
    STOP = None
    TIMEOUT = 0
    AEMA = False

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.a_log = []       # (tarih, sym, fill, stop_px|None, ref_stop, entry, etiket)
        self.util_curve = []  # (tarih, yatırım oranı 0..1)

    # ---- Aday 3 davranışı: gen_adaylar_curves.KX'in blend yolunun kopyası ----
    def _common(self, date):
        c = super()._common(date)
        v = BR["A200"].get(date)
        if v is not None and not pd.isna(v):
            c["spy_above_sma200"] = c["spy_above_sma200"] and bool(v >= 50.0)
        return c

    def _rank_key(self, qscore, row):
        a = row.get("ATR_PCT")
        a = float(a) if a is not None and not pd.isna(a) else 0.0
        return qscore / 100.0 + a / 10.0          # blend10 "denge karışımı"

    def _step(self, date):
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
                cands.append((self._rank_key(qscore, row), -dist, sym, row, plan))
            cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
            for total, _nd, sym, row, plan in cands:
                if self._slot_count() >= cfg.max_positions or self.cash < self._size(date): break
                self._open(sym, date, row, plan, total)
        eq = self._equity(date)
        self.equity_curve.append((date, eq))
        self.util_curve.append((date, (1.0 - self.cash / eq) if eq else 0.0))

    # ---- A bacağı uzantıları ----
    def _open(self, sym, date, row, plan, score):
        ok = super()._open(sym, date, row, plan, score)
        if ok:
            pos = self.positions[sym]
            atr0 = row["ATR"]
            for leg in pos.legs:
                if leg["rule"] == "target":
                    leg["bars"] = 0
                    if self.STOP:
                        kind, k = self.STOP
                        if kind == "ref":
                            leg["stop_px"] = pos.stop
                        elif atr0 is not None and not pd.isna(atr0) and atr0 > 0:
                            leg["stop_px"] = pos.entry - k * float(atr0)
                        else:
                            leg["stop_px"] = pos.stop   # ATR yoksa plan stopuna düş
        return ok

    def _split_leg_exit(self, leg, pos, row):
        if leg["rule"] != "target":
            return super()._split_leg_exit(leg, pos, row)
        cfg = self.cfg
        low, op, close = row["Low"], row["Open"], row["Close"]
        sp = leg.get("stop_px")
        res = None
        if sp is not None and not pd.isna(low) and low <= sp:      # 1) STOP — kötümser
            fill = op if (cfg.gap_fills and not pd.isna(op) and op < sp) else sp
            res = (fill, "STOP", True)
        if res is None:
            res = super()._split_leg_exit(leg, pos, row)           # 2) +2R (gün-içi limit)
        if res is None and self.AEMA:                              # 3) EMA21 (kapanış)
            ma = row.get("EMA21")
            if ma is not None and not pd.isna(ma) and not pd.isna(close) and close < ma:
                res = (close, "EMA21", True)
        if res is None and self.TIMEOUT:                           # 4) timeout (kapanış)
            leg["bars"] = leg.get("bars", 0) + 1
            if leg["bars"] >= self.TIMEOUT and not pd.isna(close):
                res = (close, "T%d" % self.TIMEOUT, True)
        if res is not None:
            self.a_log.append((str(row.name)[:10], pos.symbol, float(res[0]),
                               (float(sp) if sp is not None else None),
                               float(pos.stop), float(pos.entry), res[1]))
        return res


def selftest():
    """Market verisiz öncelik/semantik testleri. Hata = AssertionError."""
    bt = object.__new__(StopKX)
    bt.cfg = s.Config(); bt.cfg.gap_fills = True
    bt.a_log = []
    bt.STOP = None; bt.TIMEOUT = 0; bt.AEMA = False
    pos = s.Position("X", pd.Timestamp("2026-01-02"), 100.0, 95.0, 110.0,
                     10.0, 1000.0, 5, risk0=5.0)

    def mkrow(**kw):
        b = {"Open": 100.0, "High": 105.0, "Low": 98.0, "Close": 102.0,
             "ATR": 2.0, "EMA21": 90.0}
        b.update(kw)
        r = pd.Series(b); r.name = pd.Timestamp("2026-01-05")
        return r

    def mkleg(**kw):
        l = {"tag": "A", "rule": "target", "param": 2.0,
             "shares": 6.0, "cost": 600.0, "peak": 100.0}
        l.update(kw)
        return l

    # 1) aynı barda stop + hedef -> STOP kazanır (kötümser), fill = stop_px
    r = bt._split_leg_exit(mkleg(stop_px=95.0), pos, mkrow(Low=94.0, High=111.0))
    assert r is not None and r[1] == "STOP" and abs(r[0] - 95.0) < 1e-9, r
    # 2) gap-down: Open < stop -> Open'dan dolum
    r = bt._split_leg_exit(mkleg(stop_px=95.0), pos, mkrow(Open=93.0, Low=92.0, High=94.0))
    assert r is not None and r[1] == "STOP" and abs(r[0] - 93.0) < 1e-9, r
    # 3) yalnız hedef -> +2R, fill = 110
    r = bt._split_leg_exit(mkleg(), pos, mkrow(High=111.0))
    assert r is not None and r[1] == "+2R" and abs(r[0] - 110.0) < 1e-9, r
    # 4) AEMA: hedef yok, kapanış < EMA21 -> EMA21 kapanıştan
    bt.AEMA = True
    r = bt._split_leg_exit(mkleg(), pos, mkrow(Close=89.0))
    assert r is not None and r[1] == "EMA21" and abs(r[0] - 89.0) < 1e-9, r
    # 5) AEMA: aynı barda hedef + EMA21 -> hedef kazanır (gün-içi limit önce)
    r = bt._split_leg_exit(mkleg(), pos, mkrow(High=111.0, Close=89.0))
    assert r is not None and r[1] == "+2R", r
    bt.AEMA = False
    # 6) TIMEOUT=3: ilk 2 yönetilen bar None, 3.'de kapanıştan T3
    bt.TIMEOUT = 3
    leg = mkleg()
    assert bt._split_leg_exit(leg, pos, mkrow()) is None
    assert bt._split_leg_exit(leg, pos, mkrow()) is None
    r = bt._split_leg_exit(leg, pos, mkrow())
    assert r is not None and r[1] == "T3" and abs(r[0] - 102.0) < 1e-9, r
    # 7) TIMEOUT barında hedef de dokunduysa hedef kazanır
    leg = mkleg(); leg["bars"] = 2
    r = bt._split_leg_exit(leg, pos, mkrow(High=111.0))
    assert r is not None and r[1] == "+2R", r
    bt.TIMEOUT = 0
    # 8) her şey kapalı + sakin bar -> None (baz davranış)
    assert bt._split_leg_exit(mkleg(), pos, mkrow()) is None
    # 9) target-dışı bacak super'e düşer (ema21 kuralı, kapanış < EMA21)
    r = bt._split_leg_exit({"tag": "B", "rule": "ema21", "param": 0, "shares": 4.0,
                            "cost": 400.0, "peak": 100.0}, pos, mkrow(Close=89.0))
    assert r is not None and r[1] == "EMA21", r
    print("selftest: 9/9 GEÇTİ")


def load_data():
    global BR, MARKET
    if MARKET is not None:
        return
    BR = pickle.load(open(BREADTH_PKL, "rb"))
    with open(CACHE, "rb") as fh:
        MARKET = pickle.load(fh)
    MARKET = s.attach_watchlist(MARKET, base_cfg())
    print("cache sabit: 152dab0ec647 · %d hisse" % len(MARKET["data"]), flush=True)


def _tail_stats(bt):
    """A bacağı kuyruk metrikleri: en kötü çıkış %, ref-stop-altı pay, etiket sayaçları.
    NOT: pencere-sonu 'EOD' tasfiyeleri _close ile kapanır (a_log'a düşmez) —
    en kötü % hesabına trades'ten EOD da katılır (bazda sıkışan A bacağı orada görünür)."""
    worst = 0.0; below = 0; counts = {}
    for (_d, _sym, fill, _sp, ref, entry, lab) in bt.a_log:
        pct = (fill / entry - 1) * 100
        worst = min(worst, pct)
        counts[lab] = counts.get(lab, 0) + 1
        if fill < ref - 1e-9:
            below += 1
    for t in bt.trades:
        if t.outcome == "EOD":
            worst = min(worst, t.pnl_pct)
            counts["EOD"] = counts.get("EOD", 0) + 1
    n = max(1, len(bt.a_log))
    return {"a_worst_pct": round(worst, 1), "a_below_ref": round(below / n * 100, 1),
            "a_counts": counts}


def run_windows(stop=None, timeout=0, aema=False, label=""):
    load_data()
    rows = []
    for wi, (wn, sd, ed) in enumerate(WINS):
        c = copy.deepcopy(base_cfg()); c.start_date = sd; c.end_date = ed
        StopKX.STOP = stop; StopKX.TIMEOUT = timeout; StopKX.AEMA = aema
        bt = StopKX(c, market=MARKET); bt.run()
        m = bt.metrics()
        row = {"win": wn, "roi": round(m["roi"], 1), "max_dd": round(m["max_dd"], 1),
               "pf": round(m["profit_factor"], 2), "win_rate": round(m["win_rate"], 0),
               "trades": m["trades"],
               "util_med": round(pd.Series([u for _, u in bt.util_curve]).median() * 100, 1)}
        row.update(_tail_stats(bt))
        # tutarlılık: stop varken hiçbir STOP dolumu stop_px üstünde olamaz
        for (_d, _sym, fill, sp, _r, _e, lab) in bt.a_log:
            if lab == "STOP":
                assert sp is not None and fill <= sp + 1e-9, (label, wn, _sym, fill, sp)
        if wi in (0, 4):   # eğri yalnız 5y tam + son 1y (rapora gömülür)
            ds = [str(d)[:10] for d, _ in bt.equity_curve]
            eq = [e for _, e in bt.equity_curve]
            spy = bt.spy["Close"].reindex([d for d, _ in bt.equity_curve]).ffill()
            row["curve"] = {"d": ds,
                            "eq": [round(e / eq[0] * 100, 2) for e in eq],
                            "spy": [round(float(v) / float(spy.iloc[0]) * 100, 2) for v in spy]}
        rows.append(row)
        print("  %-10s %-12s roi %+7.1f · dd %6.1f · pf %5.2f · n %d" %
              (label, wn, row["roi"], row["max_dd"], row["pf"], row["trades"]), flush=True)
    return rows


def fidelity(rows):
    ok = True
    for row, (eroi, en) in zip(rows, EXPECTED):
        hit = (abs(row["roi"] - eroi) < 0.05) and (row["trades"] == en)
        print("  %-12s roi %+7.1f (beklenen %+7.1f) · n %d (beklenen %d) -> %s" %
              (row["win"], row["roi"], eroi, row["trades"], en, "OK" if hit else "FARK!"))
        ok = ok and hit
    return ok


WAVE1 = [
    ("none",   {}),
    ("ref",    {"stop": ("ref", 0.0)}),
    ("atr1.0", {"stop": ("atr", 1.0)}),
    ("atr2.0", {"stop": ("atr", 2.0)}),
    ("atr3.0", {"stop": ("atr", 3.0)}),
    ("t10",    {"timeout": 10}),
    ("t21",    {"timeout": 21}),
    ("t42",    {"timeout": 42}),
    ("t63",    {"timeout": 63}),
    ("ema21",  {"aema": True}),
]


def save_json(obj):
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    tmp = OUT_JSON + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, OUT_JSON)
    print("yazıldı:", OUT_JSON)


def load_json():
    with open(OUT_JSON) as fh:
        return json.load(fh)


def wave1():
    out = {"meta": {"cache": "152dab0ec647", "windows": [w[0] for w in WINS],
                    "spec": "2026-07-07-splitA-stop-iterasyon-design.md"},
           "variants": {}}
    for key, kw in WAVE1:
        print("varyant:", key, flush=True)
        rows = run_windows(stop=kw.get("stop"), timeout=kw.get("timeout", 0),
                           aema=kw.get("aema", False), label=key)
        out["variants"][key] = {"kind": kw, "rows": rows}
    if not fidelity(out["variants"]["none"]["rows"]):
        raise SystemExit("SADAKAT KANITI BAŞARISIZ — JSON yazılmadı.")
    out["fidelity_ok"] = True
    # tutarlılık: koruma varyantlarında tetik sayaçları boş olmamalı
    for key in ("ref", "atr1.0", "t10", "ema21"):
        cnt = 0
        for r in out["variants"][key]["rows"]:
            for lab, v in r["a_counts"].items():
                if lab not in ("+2R", "EOD"):   # STOP / EMA21 / T{N} tetikleri
                    cnt += v
        assert cnt > 0, "hiç tetiklenmedi: " + key
    save_json(out)


def score_variant(rows, base_rows):
    """Risk-ayarlı skor (spec): 5 pencere ortalaması ( Δroi + DD-iyileşmesi ).
    max_dd negatif; (baz_dd - varyant_dd) > 0 = daha sığ çukur."""
    return sum((rv["roi"] - rb["roi"]) + (rb["max_dd"] - rv["max_dd"])
               for rv, rb in zip(rows, base_rows)) / len(rows)


def wave2():
    d = load_json()
    base = d["variants"]["none"]["rows"]
    stops = sorted(["ref", "atr1.0", "atr2.0", "atr3.0"],
                   key=lambda k: score_variant(d["variants"][k]["rows"], base), reverse=True)
    touts = sorted(["t10", "t21", "t42", "t63"],
                   key=lambda k: score_variant(d["variants"][k]["rows"], base), reverse=True)
    picked = [(stops[0], touts[0]), (stops[0], touts[1]), (stops[1], touts[0])]
    d["meta"]["combo_rule"] = ("skor = 5 pencere ort.(Δroi + ΔDD-iyileşmesi); "
                               "kombolar: en iyi stop x en iyi 2 timeout + 2. stop x en iyi timeout")
    d["meta"]["combo_picked"] = ["%s+%s" % p for p in picked]
    for sk, tk in picked:
        key = "kombo:%s+%s" % (sk, tk)
        skw = d["variants"][sk]["kind"]["stop"]
        n = int(tk[1:])
        print("varyant:", key, flush=True)
        rows = run_windows(stop=tuple(skw), timeout=n, label=key)
        d["variants"][key] = {"kind": {"stop": skw, "timeout": n}, "rows": rows}
    save_json(d)
    rank = sorted(d["variants"], key=lambda k: score_variant(d["variants"][k]["rows"], base),
                  reverse=True)
    print("skor sıralaması:", " > ".join(rank))


def anatomy():
    """Baz (korumasız) koşuda A bacağının yaşam döngüsü: hedefe ulaşma süresi,
    suda kalma (kapanış<giriş), MAE (Low bazlı), ilk kâra geçiş, 'stoplansaydı
    kesilirdi ama kazandı' sayacı. Trades + ham fiyat yolundan POST-HOC; motor değişmez.
    Not: 'EOD' = pencere sonunda hedefe ulaşamadan tasfiye edilen kalıntı
    (runner kalıntısı içerebilir); giriş barı yönetilmediği için süreler giriş
    sonrası işlem günü sayısıdır."""
    load_data()
    d = load_json()
    per_win = []; w0_recs = None
    for wi, (wn, sd, ed) in enumerate(WINS):
        c = copy.deepcopy(base_cfg()); c.start_date = sd; c.end_date = ed
        StopKX.STOP = None; StopKX.TIMEOUT = 0; StopKX.AEMA = False
        bt = StopKX(c, market=MARKET); bt.run()
        recs = []
        for t in bt.trades:
            if t.outcome not in ("A:+2R", "EOD"):
                continue
            df = bt.data[t.symbol]
            if t.entry_date not in df.index:
                continue
            ref = s.compute_trade_plan(df.loc[t.entry_date], c)["stop"]
            mng = df.loc[t.entry_date:t.exit_date].iloc[1:]   # giriş barı yönetilmez
            closes = mng["Close"].dropna(); lows = mng["Low"].dropna()
            if len(closes) == 0:
                continue
            prof = closes[closes > t.entry]
            recs.append({
                "sym": t.symbol, "out": "hedef" if t.outcome == "A:+2R" else "eod",
                "bars": int(len(closes)),
                "uw_bars": int((closes < t.entry).sum()),
                "mae": round(float((lows.min() / t.entry - 1) * 100), 1) if len(lows) else 0.0,
                "first_prof": (int(closes.index.get_loc(prof.index[0]) + 1) if len(prof) else None),
                "pnl": round(t.pnl, 2), "pnl_pct": round(t.pnl_pct, 1),
                "would_stop": bool(len(lows) and float(lows.min()) <= ref),
            })
        tg = [r for r in recs if r["out"] == "hedef"]
        eo = [r for r in recs if r["out"] == "eod"]
        med = lambda xs: (round(float(pd.Series(xs).median()), 1) if xs else None)
        ws = [r for r in tg if r["would_stop"]]
        summ = {
            "win": wn, "n_target": len(tg), "n_eod": len(eo),
            "eod_loss_n": sum(1 for r in eo if r["pnl_pct"] < 0),
            "win_rate": round(len(tg) / max(1, len(recs)) * 100, 1),
            "pnl_target": round(sum(r["pnl"] for r in tg), 0),
            "pnl_eod": round(sum(r["pnl"] for r in eo), 0),
            "med_pct_target": med([r["pnl_pct"] for r in tg]),
            "med_pct_eod": med([r["pnl_pct"] for r in eo]),
            "med_bars_target": med([r["bars"] for r in tg]),
            "p90_bars_target": (round(float(pd.Series([r["bars"] for r in tg]).quantile(0.9)), 0)
                                if tg else None),
            "uw_any_pct": round(sum(1 for r in recs if r["uw_bars"] > 0) / max(1, len(recs)) * 100, 1),
            "med_uw_bars": med([r["uw_bars"] for r in recs if r["uw_bars"] > 0]),
            "med_mae": med([r["mae"] for r in recs]),
            "worst_mae": min((r["mae"] for r in recs), default=0.0),
            "deep10": sum(1 for r in recs if r["mae"] <= -10),
            "deep10_won": sum(1 for r in tg if r["mae"] <= -10),
            "med_first_prof": med([r["first_prof"] for r in tg if r["first_prof"]]),
            "would_stop_n": len(ws),
            "would_stop_pnl": round(sum(r["pnl"] for r in ws), 0),
            "eod_med_bars": med([r["bars"] for r in eo]),
            "eod_max_bars": max((r["bars"] for r in eo), default=0),
        }
        per_win.append(summ)
        print("  anatomi %-12s hedef %d · eod %d · isabet %%%s · medyan süre %s g · "
              "suda %%%s · MAE med %s · stoplansaydı %d ($%s)" %
              (wn, summ["n_target"], summ["n_eod"], summ["win_rate"],
               summ["med_bars_target"], summ["uw_any_pct"], summ["med_mae"],
               summ["would_stop_n"], summ["would_stop_pnl"]), flush=True)
        if wi == 0:
            w0_recs = recs

    def hist_bars(xs):
        h = {"≤5": 0, "6-10": 0, "11-21": 0, "22-42": 0, "43-63": 0, "64+": 0}
        for x in xs:
            k = ("≤5" if x <= 5 else "6-10" if x <= 10 else "11-21" if x <= 21
                 else "22-42" if x <= 42 else "43-63" if x <= 63 else "64+")
            h[k] += 1
        return h

    def hist_mae(xs):
        h = {"−%3'e kadar": 0, "−%3…−%6": 0, "−%6…−%10": 0, "−%10…−%20": 0, "−%20'den derin": 0}
        for x in xs:
            k = ("−%3'e kadar" if x > -3 else "−%3…−%6" if x > -6 else "−%6…−%10" if x > -10
                 else "−%10…−%20" if x > -20 else "−%20'den derin")
            h[k] += 1
        return h

    tg0 = [r for r in w0_recs if r["out"] == "hedef"]
    d["anatomy"] = {"per_win": per_win,
                    "w0_bars_hist": hist_bars([r["bars"] for r in tg0]),
                    "w0_mae_hist": hist_mae([r["mae"] for r in w0_recs]),
                    "w0_recs": w0_recs}
    save_json(d)


TR = lambda v: ("%.1f" % v).replace(".", ",")
TRG = lambda v: (TR(v)[:-2] if TR(v).endswith(",0") else TR(v))  # 24,0 -> 24

VLABEL = {
    "none":   "Baz — bugünkü canlı (A bacağı korumasız)",
    "ref":    "Plan stopu işlesin (girişte zaten hesaplanan seviye)",
    "atr1.0": "Dar stop: giriş − 1,0×ATR",
    "atr2.0": "Orta stop: giriş − 2,0×ATR",
    "atr3.0": "Geniş stop: giriş − 3,0×ATR",
    "t10":    "Süre sınırı: 10 işlem günü",
    "t21":    "Süre sınırı: 21 işlem günü",
    "t42":    "Süre sınırı: 42 işlem günü",
    "t63":    "Süre sınırı: 63 işlem günü",
    "ema21":  "A bacağı da 21-EMA'yı izlesin",
}


def _vlabel(key):
    if key.startswith("kombo:"):
        sk, tk = key[6:].split("+")
        return "Kombo: %s + %s gün sınırı (hangisi önce)" % (VLABEL[sk], tk[1:])
    return VLABEL[key]


def _anatomy_html(d, wins_tr):
    """'🔬 Stopsuz bacakla yaşamak' alt bölümü — anatomy() çıktısından. Veri yoksa boş."""
    a = d.get("anatomy")
    if not a:
        return ""
    usd = lambda v: ("−$" if v < 0 else "$") + format(abs(int(round(v))), ",").replace(",", ".")
    rows = []
    for wi, m in enumerate(a["per_win"]):
        rows.append(
            "<tr><td>%s</td><td>%d</td><td>%d (%d'i zararda)</td><td>%%%s</td>"
            "<td>%s g</td><td>%%%s</td><td>−%%%s</td><td>%d · %s</td></tr>" % (
                wins_tr[wi], m["n_target"], m["n_eod"], m["eod_loss_n"], TR(m["win_rate"]),
                TRG(m["med_bars_target"]), TR(m["uw_any_pct"]), TR(abs(m["med_mae"])),
                m["would_stop_n"], usd(m["would_stop_pnl"])))
    tbl = ('<div style="overflow-x:auto"><table><tr><th>Dönem</th><th>Hedefe ulaşan (+2R)</th>'
           '<th>Takılan (dönem sonu)</th><th>İsabet</th><th>Hedefe varış (medyan)</th>'
           '<th>Suya batan payı</th><th>Tipik en derin sarkma</th>'
           '<th>Stoplansaydı kesilecek KAZANAN (adet · kâr)</th></tr>'
           + "".join(rows) + "</table></div>")
    w0 = a["per_win"][0]
    bh = a["w0_bars_hist"]; mh = a["w0_mae_hist"]
    n0 = w0["n_target"] + w0["n_eod"]
    bh_tbl = ("<table><tr><th>Hedefe varış süresi (işlem günü)</th>"
              + "".join("<th>%s</th>" % k for k in bh) + "</tr><tr><td>işlem sayısı</td>"
              + "".join("<td>%d</td>" % v for v in bh.values()) + "</tr></table>")
    mh_tbl = ("<table><tr><th>Yoldaki en derin sarkma (MAE)</th>"
              + "".join("<th>%s</th>" % k for k in mh) + "</tr><tr><td>işlem sayısı</td>"
              + "".join("<td>%d</td>" % v for v in mh.values()) + "</tr></table>")
    para = ("""
<h2 id="stopanat">🔬 Stopsuz bacakla yaşamak — kâr/zarar anatomisi</h2>
<p>Karar stopsuz devam olduğuna göre, neyle yaşadığımızı sayılara dökelim. Aşağıdaki tablo
korumasız (baz) koşuda +2R bekleyen bacağın kaderini dönem dönem gösterir:</p>
%TBL%
<p><b>5 yıllık pencerenin detayı (%N0% bacak):</b> hedefe ulaşan %NT% işlem toplam <b>%PT%</b>
kâr getirdi (tipik işlem +%%MPT%); dönem sonuna takılan %NE% kalıntının %NEL%'i zararda kaldı,
net faturası yalnız <b>%PE%</b> (tipik −%%MPE%). Yani stopsuzluğun 5 yıllık net bilançosu:
büyük kazanç, küçük fatura — ama tek tek işlemlerde yol ÇOK sarsıntılı:</p>
<ul>
<li><b>Kara ne zaman geçiyor?</b> Tipik işlem daha girişten sonraki <b>1. günde</b> kârda
(medyan). Ama bu ilk kâr kalıcı değil: bacakların <b>%%UW%'ü</b> yolda en az bir gün girişin
altına sarkıyor; sarkanlar tipik <b>%UWB% işlem günü</b> su altında kalıyor.</li>
<li><b>Ne kadar derine batıyor?</b> Tipik en derin sarkma −%%MMAE%; işlemlerin %D10%'ü
−%10'dan derine battı ve bunların <b>%D10W%'ü yine de hedefe döndü</b>. En derin sarkma
−%%WMAE% idi. Stop koymamanın kazandırdığı işte bu geri dönüşler: hedefe ulaşan işlemlerin
%WSN%'i (%WSP% kâr) yolda referans stopa değmişti — stoplu dünyada bunlar zarar yazacaktı.</li>
<li><b>Hedefe varış ne kadar sürüyor?</b> Medyan %MBT% işlem günü, ama kuyruk uzun: onda biri
%P90% günden uzun sürdü. Takılan kalıntıların tipik taşınma süresi %EMB% gün; en inatçısı
<b>%EMX% işlem günü</b> (≈4,5 yıl) taşındı — "slot işgali"nin gerçek yüzü bu.</li>
</ul>
%BHT%
%MHT%
<p class="note">Dürüstlük: tutarlar bileşik büyüyen sermaye üstünden dolar; "stoplansaydı
kesilecek" sütunu işlem-bazlı bir varsayımsaldır (stoplu dünyada portföy başka evrilirdi —
o dünyanın gerçek toplamı yukarıdaki ana tabloda). "Takılan" kalıntı runner artığı içerebilir;
sarkma (MAE) gün-içi Low ile, süreler giriş sonrası işlem günüyle ölçüldü.</p>
"""
            .replace("%TBL%", tbl).replace("%N0%", str(n0)).replace("%NT%", str(w0["n_target"]))
            .replace("%PT%", usd(w0["pnl_target"])).replace("%MPT%", TR(w0["med_pct_target"]))
            .replace("%NE%", str(w0["n_eod"])).replace("%NEL%", str(w0["eod_loss_n"]))
            .replace("%PE%", usd(w0["pnl_eod"])).replace("%MPE%", TR(abs(w0["med_pct_eod"])))
            .replace("%UWB%", TRG(w0["med_uw_bars"])).replace("%UW%", TR(w0["uw_any_pct"]))
            .replace("%MMAE%", TR(abs(w0["med_mae"]))).replace("%WMAE%", TR(abs(w0["worst_mae"])))
            .replace("%D10W%", str(w0["deep10_won"])).replace("%D10%", str(w0["deep10"]))
            .replace("%WSN%", str(w0["would_stop_n"])).replace("%WSP%", usd(w0["would_stop_pnl"]))
            .replace("%MBT%", TRG(w0["med_bars_target"])).replace("%P90%", "%d" % w0["p90_bars_target"])
            .replace("%EMB%", TRG(w0["eod_med_bars"])).replace("%EMX%", str(w0["eod_max_bars"]))
            .replace("%BHT%", bh_tbl).replace("%MHT%", mh_tbl))
    return para


def report():
    d = load_json()
    assert d.get("fidelity_ok"), "sadakat kanıtı olmadan rapor yazılmaz"
    base = d["variants"]["none"]["rows"]
    keys = list(d["variants"])
    rank = sorted(keys, key=lambda k: score_variant(d["variants"][k]["rows"], base),
                  reverse=True)
    finalists = [k for k in rank if k != "none"][:2]
    wins_tr = ["5 yıl (tümü, 2021→2026)", "Düşüş dönemi 2021-23 (zor dönem)",
               "Toparlanma 2023-25", "Son 2 yıl", "Son 1 yıl"]

    # --- tablo: pencere · varyant satırları; en iyi ROI/DD/PF hücresi <b> ---
    rowsh = []
    for wi, wn in enumerate(wins_tr):
        best_roi = max(d["variants"][k]["rows"][wi]["roi"] for k in keys)
        best_dd = max(d["variants"][k]["rows"][wi]["max_dd"] for k in keys)
        best_pf = max(d["variants"][k]["rows"][wi]["pf"] for k in keys)
        for k in keys:
            r = d["variants"][k]["rows"][wi]
            hl = ' style="background:rgba(201,133,0,.08)"' if k == "none" else ""
            def cell(v, best, fmt):
                sx = fmt(v)
                return "<b>%s</b>" % sx if abs(v - best) < 1e-9 else sx
            rowsh.append(
                "<tr%s><td>%s · %s</td><td>%s</td><td>%s</td><td>%s</td>"
                "<td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    hl, wn, _vlabel(k),
                    cell(r["roi"], best_roi, lambda v: ("+%" if v >= 0 else "−%") + TR(abs(v))),
                    cell(r["max_dd"], best_dd, lambda v: "−%" + TR(abs(v))),
                    cell(r["pf"], best_pf, lambda v: ("%.2f" % v).replace(".", ",")),
                    r["trades"], "%" + TR(r["util_med"]), "%" + TR(r["a_below_ref"]),
                    ("+%" if r["a_worst_pct"] >= 0 else "−%") + TR(abs(r["a_worst_pct"]))))
    table = ('<div style="overflow-x:auto"><table><tr><th>Dönem · Koruma</th><th>Getiri</th>'
             '<th>En derin çukur</th><th>Denge (1\'e karşı)</th><th>İşlem</th>'
             '<th>Parada kalma</th><th>Ref-stop-altı A çıkışı</th><th>En kötü tek çıkış</th></tr>'
             + "".join(rowsh) + "</table></div>")

    top = [k for k in rank if k != "none"][0]
    droi5 = d["variants"][top]["rows"][0]["roi"] - base[0]["roi"]

    section = """<!-- STOPAB:BEGIN -->
<h2 id="stopab">🛡️ +2R bacağına stop koysak mı? — stopsuz bacak deneyi (2026-07-07)</h2>
<blockquote><p><b>Sorun:</b> Canlıda her alımın %60'ı "+2R kâr hedefi"ni bekliyor ama bu parçanın
<b>hiçbir koruması yok</b> — hisse alımdan sonra çökerse süresiz elde kalıyor (TER'de iki günde
−%24'ü böyle yedik; grafikteki "Ref. stop" çizgisi yalnız gösterim, motor uygulamıyor).
<b>Denenen:</b> bu parçaya stop (plan stopu / 1-2-3×ATR), süre sınırı (10-63 işlem günü),
21-EMA takibi ve ikili kombinasyonlar takıldı; 13 varyantın hepsi aynı 5 dönemde, aynı sabit
veriyle bazla kıyaslandı. Ek beklenti: yer sınırı analizine göre sistem günlerin ~%75'inde
20/20 dolu — stoplanan parça yeri erken boşaltırsa para yeni sinyale döner, getiri artabilir.</p></blockquote>
<p><b>Kısa cevap: HAYIR — denenen 12 korumanın hiçbiri bazı geçemedi; tablo baz için ezici.</b>
En iyi koruma bile (%TOPLABEL%) 5 yıllık getiride bazın çok gerisinde (fark %DROI5% puan).
Beklenmedik ders şu çıktı: sistemin yüksek getirisinin önemli bir kaynağı tam da bu
"stopsuzluk" — +2R bekleyen parça, kırılım sonrası sık görülen geri çekilmeleri sineye çekip
toparlanınca hedefte satıyor. Stop koyunca bu parçaların çoğu −%2…−%4'lük sıradan
sallantılarda kesildi (son 1 yılda A parçalarının %59'u stopla bitti), kazananlar filizken
koparıldı ve işlem kalitesi çöktü (denge 3,67'den ~1,2-1,5'e). Sermaye-geri-dönüşüm beklentisi
gerçekleşti ama ters tepti: parada kalma %77'den %93'e çıktı, işlem sayısı ~3 katına fırladı —
geri dönen para daha düşük kaliteli işlemlere gitti.</p>
%TABLE%
<p class="note">Nasıl okunur: "Parada kalma" = paranın hissede bağlı olduğu gün payı (ortanca).
"Ref-stop-altı A çıkışı" = korumasız bacağın, girişte hesaplanan referans stopun da altında bir
fiyattan çıktığı işlemlerin payı. "En kötü tek çıkış" = o dönemdeki en kötü tek işlem —
korumaların gerçek kazanımı bu sütunda: bazda −%72,9'a varan tek-işlem felaketi, korumalarla
−%14…−%42 bandına iniyor. Dürüstlük: aynı barda hem stop hem hedef dokunursa <b>stop sayıldı</b>
(kötümser); gap'te açılıştan dolum + kayma maliyeti uygulandı; 2021-26 örneklemi V-tipi
toparlanmalarla dolu — "dipte satmamak kazandırır" dersi bu örnekleme bağlı olabilir, toparlanamayan
hisse riski (delist vb.) backtestte az temsil edilir; geçmiş sonuç gelecek garantisi değildir.</p>
<div class="leg" id="stopLeg"></div>
<div id="stopLcharts"></div>
%ANATOMY%
<blockquote><p><b>✅ Karar (2026-07-07): stopsuz devam.</b> Skor sıralamasında (getiri +
çukur-iyileşmesi, 5 dönem ortalaması) birinci zaten bugünkü canlı davranıştı; sıralama: %RANKING%.
Korumalar portföy çukurunu da kayda değer düzeltmedi (baz −%19,6 → en iyi ~−%18; çukuru tek
hisse kuyrukları değil, 20 pozisyonun birlikte düştüğü piyasa geneli belirliyor). Tek-işlem
felaket sigortası isteyene en ehveni süre sınırıydı (%TOPLABEL%) — ama fiyatı 5 yılda getirinin
yarısından fazlası. <b>Canlıda değişiklik GEREKMİYOR</b> (sistem zaten stopsuz çalışıyor);
yukarıdaki anatomi, bu tercihle neyle yaşadığımızın belgesidir.</p></blockquote>
<!-- STOPAB:END -->
""".replace("%TABLE%", table).replace("%TOPLABEL%", _vlabel(top)) \
   .replace("%DROI5%", ("−%d" if droi5 < 0 else "+%d") % abs(round(droi5))) \
   .replace("%RANKING%", " &gt; ".join(("<b>baz</b>" if k == "none" else k) for k in rank)) \
   .replace("%ANATOMY%", _anatomy_html(d, wins_tr))

    # --- inline eğri verisi + çizim (lwc.js sayfada zaten yüklü; en sona eklenir) ---
    curves = {}
    for wjs, wi in (("w0", 0), ("w4", 4)):
        c0 = d["variants"]["none"]["rows"][wi]["curve"]
        curves[wjs] = {"d": c0["d"], "spy": c0["spy"], "none": c0["eq"]}
        for k in finalists:
            curves[wjs][k] = d["variants"][k]["rows"][wi]["curve"]["eq"]
    fin_js = json.dumps([{"k": k, "n": _vlabel(k)} for k in finalists], ensure_ascii=False)
    script = """<!-- STOPABJS:BEGIN -->
<script>
(function(){
 const SC=%CURVES%;
 const FIN=%FIN%;
 const box=document.getElementById('stopLcharts');
 if(!box) return;
 if(typeof LightweightCharts==='undefined'){box.innerHTML='<p class="note">Grafik kütüphanesi yüklenemedi.</p>';return;}
 const SER=[{k:'spy',n:'SPY — endeks fonu',c:'#9085e9',st:2},
            {k:'none',n:'Baz — bugünkü canlı (korumasız)',c:'#c98500',st:0}]
   .concat(FIN.map((f,i)=>({k:f.k,n:f.n,c:['#3987e5','#199e70'][i]||'#8b949e',st:0})));
 document.getElementById('stopLeg').innerHTML=SER.map(s=>
  `<span><span style="display:inline-block;width:18px;border-top:2.5px ${s.st?'dashed':'solid'} ${s.c};vertical-align:3px"></span>${s.n}</span>`).join('');
 const TITLES={w0:'5 yıl (tümü, 2021→2026)',w4:'Son 1 yıl'};
 for(const w of ['w0','w4']){
  const cur=SC[w]; if(!cur) continue;
  const card=document.createElement('div'); card.className='card';
  card.innerHTML=`<div class="gt">${TITLES[w]} <span class="mut" style="font-weight:400">· başlangıç = 100</span></div><div class="lc" style="height:290px"></div>`;
  box.appendChild(card);
  const el=card.querySelector('.lc');
  const ch=LightweightCharts.createChart(el,{
   layout:{background:{color:'#161b22'},textColor:'#8b949e'},
   grid:{vertLines:{color:'#21262d'},horzLines:{color:'#21262d'}},
   rightPriceScale:{borderColor:'#30363d',mode:1},
   timeScale:{borderColor:'#30363d'}, height:290, width:el.clientWidth});
  new ResizeObserver(()=>ch.applyOptions({width:el.clientWidth})).observe(el);
  for(const s of SER){
   if(!cur[s.k]) continue;
   ch.addLineSeries({color:s.c,lineWidth:2,lineStyle:s.st,lastValueVisible:false,priceLineVisible:false})
     .setData(cur.d.map((dd,j)=>({time:dd,value:cur[s.k][j]})));
  }
  ch.timeScale().fitContent();
 }
})();
</script>
<!-- STOPABJS:END -->
""".replace("%CURVES%", json.dumps(curves)).replace("%FIN%", fin_js)

    import datetime
    html = open(ADAYLAR).read()
    bak = ADAYLAR + ".bak." + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    open(bak, "w").write(html)
    print("yedek:", bak)

    def upsert(h, begin, end, block, anchor):
        if begin in h:
            pre, rest = h.split(begin, 1)
            _, post = rest.split(end, 1)
            return pre + block.rstrip("\n") + post
        assert anchor in h, "çapa bulunamadı: " + anchor
        return h.replace(anchor, block + anchor, 1)

    html = upsert(html, "<!-- STOPAB:BEGIN -->", "<!-- STOPAB:END -->", section,
                  "<h2>Karar öncesi tartılan noktalar</h2>")
    html = upsert(html, "<!-- STOPABJS:BEGIN -->", "<!-- STOPABJS:END -->", script,
                  "</body></html>")
    open(ADAYLAR, "w").write(html)
    print("adaylar.html güncellendi · finalistler:", finalists, "· sıralama:", " > ".join(rank))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fidelity", action="store_true")
    ap.add_argument("--wave1", action="store_true")
    ap.add_argument("--wave2", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--anatomy", action="store_true")
    args = ap.parse_args()
    if args.anatomy:
        anatomy(); return
    if args.selftest:
        selftest(); return
    if args.fidelity:
        rows = run_windows(label="none")
        if not fidelity(rows):
            raise SystemExit("SADAKAT KANITI BAŞARISIZ — deney durduruldu, harness hatası ara.")
        print("SADAKAT: 5/5 birebir."); return
    if args.wave1:
        wave1(); return
    if args.wave2:
        wave2(); return
    if args.report:
        report(); return
    ap.error("bir mod seç: --selftest / --fidelity / --wave1 / --wave2 / --report")


if __name__ == "__main__":
    main()

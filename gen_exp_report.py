# -*- coding: utf-8 -*-
"""Strateji karşılaştırma raporu üreticisi → dashboard_static/exp_report.html

İKİ EKSEN:
 A) Giriş/Çıkış yöntemi: 🏆 ATR-trail · 📐 8/21-EMA · 💡 63G-Şamdan · 👑 Qulla-21
    — hepsi AYNI zeminde (RS top-50 · sp500_ndx · sabit %7.5/slot · 20 slot · 5y).
    Kurallara dokunulmaz; yalnız her yöntemin kendi giriş-lb'si + çıkış mantığı farklı.
 B) Sermaye konuşlandırma (cash-drag): 👑 Qulla-21 %5 (baz) → COMBO (%7.5 + free_runner_slots).

Salt-okur: canlı sisteme/trade mantığına dokunmaz. Kullanım: python3 gen_exp_report.py"""
import copy, json, os
import pandas as pd
import swing2_backtest as s

OUT = "/home/gokhan/dashboard_static/exp_report.html"
FULL_SD, FULL_ED = "2021-05-01", "2026-06-30"

# ---- veri (canlı Qulla-21 zemini: RS top-50 · sp500_ndx · split) ----
cfg = s.Config()
cfg.period = "5y"; cfg.price_source = "fmp"; cfg.disk_cache = True
cfg.use_earnings = False; cfg.per_ticker_download = False
cfg.entry_mode = "qswing_breakout"; cfg.qswing_breakout_lb = 63
cfg.exit_mode = "split"; cfg.split_a = "target"; cfg.split_a_param = 2.0
cfg.split_b = "ema21"; cfg.split_b_param = 0.0; cfg.split_ratio = 0.5
cfg.use_rs_universe = True; cfg.rs_n = 50
cfg.rs_pool = s.UNIVERSE_PRESETS["sp500_ndx"]; cfg.universe = cfg.rs_pool
cfg.max_positions = 20; cfg.compounding = True; cfg.liquidate_at_end = True

print("Veri + RS evreni yükleniyor (sp500_ndx ~373, 5y)...", flush=True)
market = s.load_market(cfg)
CAL = market["calendar"]
NPOOL = len(market["data"])


def _deploy_pct(bt, eq):
    lc = pd.Series(0.0, index=CAL)
    for t in bt.trades:
        lc.loc[t.entry_date:t.exit_date] += t.shares * t.entry
    e = eq.reindex(CAL).ffill()
    return float((lc / e).reindex(eq.index).dropna().mean() * 100)


def run(ov, sd=FULL_SD, ed=FULL_ED):
    c = copy.deepcopy(cfg)
    for k, v in ov.items():
        setattr(c, k, v)
    c.start_date = sd or ""; c.end_date = ed or ""
    bt = s.Swing2Backtester(c, market=market); bt.run()
    mt = bt.metrics()
    tr = pd.DataFrame([t.__dict__ for t in bt.trades])
    tr["hold"] = (pd.to_datetime(tr["exit_date"]) - pd.to_datetime(tr["entry_date"])).dt.days
    w, l = tr[tr.pnl > 0], tr[tr.pnl <= 0]
    st = {
        "roi": mt["roi"], "dd": mt["max_dd"], "pf": mt["profit_factor"], "win": mt["win_rate"],
        "n": mt["trades"], "alpha": mt["alpha"], "spy": mt["spy_roi"], "depl": _deploy_pct(bt, mt["equity"]),
        "hold_med": float(tr["hold"].median()), "hold_avg": float(tr["hold"].mean()), "hold_max": int(tr["hold"].max()),
        "avgw_pct": float(w.pnl_pct.mean()) if len(w) else 0.0, "avgl_pct": float(l.pnl_pct.mean()) if len(l) else 0.0,
        "maxw_pct": float(w.pnl_pct.max()) if len(w) else 0.0, "maxl_pct": float(l.pnl_pct.min()) if len(l) else 0.0,
    }
    return mt["equity"], st


def series(eq, base=100.0):
    n = eq / eq.iloc[0] * base
    return [{"time": d.strftime("%Y-%m-%d"), "value": round(float(v), 2)} for d, v in n.items()]


def dd_series(eq):
    dd = (eq / eq.cummax() - 1) * 100
    return [{"time": d.strftime("%Y-%m-%d"), "value": round(float(v), 2)} for d, v in dd.items()]


def monthly_html(eq):
    p = s.monthly_returns_table(eq)
    head = "".join(f"<th>{c}</th>" for c in p.columns)
    rows = []
    for y, r in p.iterrows():
        tds = "".join(
            f"<td class='{'pos' if v > 0 else 'neg' if v < 0 else ''}'>{v:+.1f}</td>" if pd.notna(v) else "<td>·</td>"
            for v in r.values)
        rows.append(f"<tr><th>{y}</th>{tds}</tr>")
    return f"<table class='mon'><tr><th>Yıl</th>{head}</tr>{''.join(rows)}</table>"


def pf_s(x):
    return f"{x:.2f}" if x != float("inf") else "∞"


# ===== EKSEN A: 4 giriş/çıkış yöntemi, hepsi sabit %7.5 =====
C75 = {"max_position_pct": 0.075, "free_runner_slots": False}
METHODS = [
    ("champ", "🏆 ATR-trail (Şampiyon)", "#f0883e", {
        "qswing_breakout_lb": 40, "exit_mode": "optimized",
        "partial_tp": True, "partial_pct": 0.5, "partial_rr": 2.0,
        "trailing_stop": True, "atr_trail_mult": 2.5, "breakeven_mode": "strict_entry", **C75}),
    ("ema", "📐 8/21-EMA", "#a371f7", {
        "qswing_breakout_lb": 40, "exit_mode": "split",
        "split_a": "ema8", "split_a_param": 0.0, "split_b": "ema21", "split_b_param": 0.0,
        "split_ratio": 0.5, "partial_tp": False, "trailing_stop": False, **C75}),
    ("chand", "💡 63G-Şamdan", "#d29922", {
        "qswing_breakout_lb": 63, "exit_mode": "atr_full", "atr_trail_mult": 3.25,
        "partial_tp": False, "trailing_stop": False, **C75}),
    ("qulla", "👑 Qulla-21 (mevcut)", "#3fb950", {
        "qswing_breakout_lb": 63, "exit_mode": "split",
        "split_a": "target", "split_a_param": 2.0, "split_b": "ema21", "split_b_param": 0.0,
        "split_ratio": 0.5, "partial_tp": False, "trailing_stop": False, **C75}),
]

DESC = {
    "champ": "Kırılımda (40 günün tepesi) alır. Kârın <b>yarısını +2R'de</b> (aldığı riskin 2 katı) satıp "
             "cebe koyar; kalan yarısını fiyat son tepesinden <b>2.5×ATR</b> (oynaklık payı) geri düşene kadar taşır. "
             "Hızlı kâr alan, isabeti yüksek ama büyük trendleri erken bırakan yöntem.",
    "ema": "Kırılımda (40 günün tepesi) alır. Sabit hedef/stop yoktur; tamamen hareketli ortalamalara güvenir: "
           "<b>yarısını 8 günlük</b>, kalan yarısını <b>21 günlük</b> ortalamanın altına kapanınca satar. "
           "Trend-takipçi ama yatay/testere piyasada 8-EMA sık yanıltıp erken çıkartır.",
    "chand": "Daha <b>seçici</b> girer (63 günün / çeyreklik tepe). Kâr alma ve hedef YOK; pozisyonun tamamını "
             "fiyat en yüksek noktasından <b>3.25×ATR</b> geri düşene kadar taşır (şamdan / chandelier stop). "
             "Az sayıda ama çok büyük trend yakalamayı hedefler: isabet düşük, tek tek kayıplar küçük, kazançlar büyük.",
    "qulla": "🏆'nın hızlı kâr-almasını 📐'nin trend runner'ıyla <b>birleştirir</b>: 63 günün tepesinde alır, "
             "<b>yarısını +2R hedefte</b> satar, kalan yarısını <b>21-EMA altına kapanana</b> kadar taşır. "
             "Hızlı kâr güvenliği ile büyük trend yakalamanın dengesi — bugünkü canlı yöntem.",
}

print("EKSEN A — giriş/çıkış yöntemleri (%7.5) FULL...", flush=True)
A_eq, A_st = {}, {}
for key, label, col, ov in METHODS:
    print(f"  {label} ...", flush=True)
    A_eq[key], A_st[key] = run(ov)
spy = market["spy"]["Close"].reindex(A_eq["qulla"].index).ffill()

# walk-forward pencereleri (her yöntem)
WINDOWS = [
    ("W1: 2021–22 (ayı)", "2021-05-01", "2022-12-31"),
    ("W2: 2022–23 (ayı+topar.)", "2022-01-01", "2023-06-30"),
    ("W3: 2023–24 (boğa)", "2023-01-01", "2024-12-31"),
    ("W4: son 2 yıl", "2024-07-01", "2026-06-30"),
    ("FULL: 2021–26", FULL_SD, FULL_ED),
]
A_win = {k: {} for k, *_ in METHODS}
for wname, sd, ed in WINDOWS:
    print(f"  pencere {wname} ...", flush=True)
    for key, label, col, ov in METHODS:
        _, st = run(ov, sd, ed)
        A_win[key][wname] = st

# ---- EKSEN A tabloları ----
def a_full_row(key, label):
    st = A_st[key]
    return (f"<tr><td>{label}</td>"
            f"<td class='{'pos' if st['roi'] >= 0 else 'neg'}'>{st['roi']:+.1f}%</td>"
            f"<td>{st['dd']:.1f}%</td><td>{pf_s(st['pf'])}</td><td>%{st['win']:.0f}</td>"
            f"<td>%{st['depl']:.0f}</td><td>{st['n']}</td>"
            f"<td>{st['hold_med']:.0f}g</td></tr>")

a_full_table = "".join(a_full_row(k, lbl) for k, lbl, *_ in METHODS)
a_full_table += (f"<tr><td>📈 SPY (al-tut, kıyas)</td><td class='mut'>{A_st['qulla']['spy']:+.1f}%</td>"
                 f"<td class='mut'>—</td><td class='mut'>—</td><td class='mut'>—</td>"
                 f"<td class='mut'>%100</td><td class='mut'>—</td><td class='mut'>—</td></tr>")

def a_win_row(wname):
    cells = ""
    for key, label, col, ov in METHODS:
        st = A_win[key][wname]
        cells += f"<td class='{'pos' if st['roi'] >= 0 else 'neg'}'>{st['roi']:+.1f}% <span class='mut'>/ {st['dd']:.0f}%</span></td>"
    return f"<tr><td>{wname}</td>{cells}</tr>"

a_win_table = "".join(a_win_row(w[0]) for w in WINDOWS)
a_win_head = "".join(f"<th>{lbl.split(' ')[0]}</th>" for k, lbl, *_ in METHODS)

# ---- SPY karşısında: trailing dönemler (5y/2y/1y/6ay/1ay, bugüne kadar) ----
TRAIL = [("5 yıl", "2021-05-01"), ("2 yıl", "2024-07-01"), ("1 yıl", "2025-07-01"),
         ("6 ay", "2026-01-01"), ("1 ay", "2026-06-01")]
print("EKSEN A — SPY karşısında trailing dönemler...", flush=True)
A_trail = {k: {} for k, *_ in METHODS}
trail_spy = {}
for tname, sd in TRAIL:
    for key, label, col, ov in METHODS:
        _, st = run(ov, sd, FULL_ED)
        A_trail[key][tname] = st
    trail_spy[tname] = A_trail["qulla"][tname]["spy"]

def trail_row(tname):
    spyv = trail_spy[tname]
    cells = ""
    for key, label, col, ov in METHODS:
        roi = A_trail[key][tname]["roi"]
        beat = roi >= spyv
        cells += (f"<td class='{'pos' if roi >= 0 else 'neg'}'>{'<b>' if beat else ''}{roi:+.1f}%{'</b>' if beat else ''}</td>")
    cells += f"<td class='mut'>{spyv:+.1f}%</td>"
    return f"<tr><td>{tname}</td>{cells}</tr>"

trail_table = "".join(trail_row(t[0]) for t in TRAIL)
trail_head = "".join(f"<th>{lbl.split(' ')[0]}</th>" for k, lbl, *_ in METHODS) + "<th>📈 SPY</th>"

# dinamik yargı
_by_roi = sorted(METHODS, key=lambda m: A_st[m[0]]["roi"], reverse=True)
_by_pf = sorted(METHODS, key=lambda m: A_st[m[0]]["pf"] if A_st[m[0]]["pf"] != float("inf") else 1e9, reverse=True)
_by_dd = sorted(METHODS, key=lambda m: A_st[m[0]]["dd"], reverse=True)  # dd negatif → büyük=sığ
top_roi, top_pf, top_dd = _by_roi[0][1], _by_pf[0][1], _by_dd[0][1]

# ===== EKSEN B: cash-drag (Qulla-21 %5 baz → COMBO %7.5+slot-serbest) =====
BASE  = {"qswing_breakout_lb": 63, "exit_mode": "split", "split_a": "target", "split_a_param": 2.0,
         "split_b": "ema21", "split_b_param": 0.0, "split_ratio": 0.5, "partial_tp": False,
         "trailing_stop": False, "max_position_pct": 0.05, "free_runner_slots": False}
COMBO = dict(BASE); COMBO["max_position_pct"] = 0.075; COMBO["free_runner_slots"] = True

print("EKSEN B — cash-drag (baz %5 → combo)...", flush=True)
eq_b, st_b = run(BASE)
eq_c, st_c = run(COMBO)

# ===== EKSEN C: Qulla-21 combo — giriş boyutu × slot sayısı ısı haritası =====
QBASE = {"qswing_breakout_lb": 63, "exit_mode": "split", "split_a": "target", "split_a_param": 2.0,
         "split_b": "ema21", "split_b_param": 0.0, "split_ratio": 0.5, "partial_tp": False,
         "trailing_stop": False, "free_runner_slots": True}
GRID_SIZES = [0.05, 0.06, 0.075, 0.10]
GRID_SLOTS = [25, 20, 16, 12]          # tabloda yukarıdan aşağı
print("EKSEN C — boyut × slot ızgarası...", flush=True)
grid = {}
for _slot in GRID_SLOTS:
    for _size in GRID_SIZES:
        _ov = dict(QBASE); _ov["max_position_pct"] = _size; _ov["max_positions"] = _slot
        _, grid[(_slot, _size)] = run(_ov)
        print(f"  slot {_slot} × %{_size*100:.1f} → ROI {grid[(_slot,_size)]['roi']:+.0f}% DD {grid[(_slot,_size)]['dd']:.0f}%", flush=True)

_grois = [grid[(s, z)]["roi"] for s in GRID_SLOTS for z in GRID_SIZES]
_rmin, _rmax = min(_grois), max(_grois)
def _cellbg(roi):
    t = (roi - _rmin) / (_rmax - _rmin) if _rmax > _rmin else 0.5
    return f"rgba(63,185,80,{0.06 + 0.44*t:.2f})"
def _gcell(slot, size):
    st = grid[(slot, size)]
    live = (slot == 20 and abs(size - 0.075) < 1e-9)
    style = f"background:{_cellbg(st['roi'])};text-align:center" + (";outline:2px solid #58a6ff;outline-offset:-2px" if live else "")
    return (f"<td style='{style}'><b>{st['roi']:+.0f}%</b>{' ★' if live else ''}<br>"
            f"<span class='mut' style='font-size:11px'>DD {st['dd']:.0f}% · PF {pf_s(st['pf'])} · %{st['depl']:.0f}</span></td>")
heat_head = "".join(f"<th>%{z*100:g}/slot</th>" for z in GRID_SIZES)
heat_rows = "".join("<tr><td><b>" + str(s) + " slot</b></td>" + "".join(_gcell(s, z) for z in GRID_SIZES) + "</tr>" for s in GRID_SLOTS)
_cells = [(s, z, grid[(s, z)]) for s in GRID_SLOTS for z in GRID_SIZES]
_bR = max(_cells, key=lambda c: c[2]["roi"])
_bP = max(_cells, key=lambda c: c[2]["pf"] if c[2]["pf"] != float("inf") else 1e9)
_bD = max(_cells, key=lambda c: c[2]["dd"])
grid_best_roi = f"{_bR[0]} slot × %{_bR[1]*100:g} (ROI {_bR[2]['roi']:+.0f}%, DD {_bR[2]['dd']:.0f}%)"
grid_best_pf = f"{_bP[0]} slot × %{_bP[1]*100:g} (PF {pf_s(_bP[2]['pf'])}, ROI {_bP[2]['roi']:+.0f}%, DD {_bP[2]['dd']:.0f}%)"
grid_shallow = f"{_bD[0]} slot × %{_bD[1]*100:g} (DD {_bD[2]['dd']:.0f}%, ROI {_bD[2]['roi']:+.0f}%)"
gl = grid[(20, 0.075)]

data = {
    "spy": series(spy),
    **{f"a_{k}": series(A_eq[k]) for k, *_ in METHODS},
    "eq_b": series(eq_b), "eq_c": series(eq_c),
    "dd_b": dd_series(eq_b), "dd_c": dd_series(eq_c),
}
A_leg = " &nbsp; ".join(f"<b style='color:{col}'>■</b> {lbl}" for k, lbl, col, ov in METHODS) + " &nbsp; <b style='color:#8b949e'>■</b> SPY"
A_lines_js = "\n".join(f"eqA.addLineSeries({{color:'{col}',lineWidth:2}}).setData(DATA.a_{k});" for k, lbl, col, ov in METHODS)

fmt = lambda x: f"{x:+.1f}"
today = pd.Timestamp.now().strftime("%d.%m.%Y")
html = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📊 Strateji Karşılaştırma Raporu — 4 yöntem + Combo</title>
<style>
 :root{{--bg:#0d1117;--card:#161b22;--bd:#30363d;--fg:#e6edf3;--mut:#8b949e;--grn:#3fb950;--red:#f85149;--blu:#58a6ff;--amb:#d29922}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 system-ui,'Segoe UI',sans-serif}}
 .wrap{{max-width:1060px;margin:0 auto;padding:18px 20px 60px}}
 h1{{font-size:22px;margin:14px 0 4px}} h2{{font-size:18px;margin:34px 0 10px;border-bottom:1px solid var(--bd);padding-bottom:6px}}
 h3{{font-size:15px;margin:20px 0 6px;color:var(--blu)}}
 .mut{{color:var(--mut)}} .pos{{color:var(--grn)}} .neg{{color:var(--red)}} .amb{{color:var(--amb)}}
 .card{{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px 16px;margin:12px 0}}
 table{{border-collapse:collapse;width:100%;font-size:13.5px;margin:8px 0}}
 th,td{{border:1px solid var(--bd);padding:6px 9px;text-align:right}} th{{background:#1c2128}}
 td:first-child,th:first-child{{text-align:left}}
 table.mon td,table.mon th{{padding:4px 6px;font-size:12.5px}}
 .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}}
 .kpi{{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px 12px}}
 .kpi .v{{font-size:20px;font-weight:700}} .kpi .l{{font-size:12px;color:var(--mut)}}
 .chart{{height:330px;border:1px solid var(--bd);border-radius:10px;margin:10px 0}}
 .leg{{font-size:12.5px;color:var(--mut);margin:2px 0 14px}} .leg b{{padding:0 4px}}
 blockquote{{border-left:3px solid var(--amb);margin:10px 0;padding:4px 14px;color:#d8c690;background:#1a1f17;border-radius:0 8px 8px 0}}
 a{{color:var(--blu)}} .back{{font-size:13px}} ul{{margin:6px 0 6px 20px;padding:0}} li{{margin:5px 0}}
 .mcard{{border-left:4px solid var(--bd);padding:2px 0 2px 12px;margin:12px 0}}
</style></head><body><div class="wrap">
<p class="back"><a href="/">← Dashboard'a dön</a> &nbsp;·&nbsp; <a href="/lab">🧪 Deney Laboratuvarı →</a></p>
<h1>📊 Strateji Karşılaştırma Raporu</h1>
<p class="mut">👑 Qulla-21 · {today} · Veri: FMP günlük · Havuz: sp500_ndx (~{NPOOL}) → günlük RS top-50 · 5 yıl ·
Motor: <code>swing2_backtest.py</code> · Pencere bazlı doğrulama (5 dilim)</p>

<div class="card">
<b>Bu rapor iki ayrı soruyu yanıtlar:</b>
<ul>
<li><b>Bölüm A — Hangi giriş/çıkış yöntemi?</b> Bugüne dek denenip bırakılan 3 yöntem (🏆 · 📐 · 💡) ile
bugünkü 👑 Qulla-21, <b>tamamen aynı zeminde</b> (aynı evren, aynı boyut) yarıştırılır. Böylece fark yalnız
"ne zaman al / ne zaman sat" kuralından gelir.</li>
<li><b>Bölüm B — Sermaye ne kadar çalışsın (cash-drag)?</b> Kazanan yöntemin (Qulla-21) üstünde, sermayeyi
daha verimli konuşlandıran <b>COMBO</b> katmanı incelenir.</li>
</ul>
<p class="mut">Adil olması için Bölüm A'da tüm yöntemler sabit %7.5/slot · 20 slot ile koşuldu; giriş/çıkış
kurallarına (kırılım süresi, +2R, ATR çarpanları) dokunulmadı — her yöntem tarihsel haliyle.</p>
</div>

<h2>A) Giriş/Çıkış Yöntemleri — Basit Anlatım</h2>
<div class="card">
<div class="mcard" style="border-color:#f0883e"><b>🏆 ATR-trail (eski "şampiyon")</b><br>{DESC['champ']}</div>
<div class="mcard" style="border-color:#a371f7"><b>📐 8/21-EMA</b><br>{DESC['ema']}</div>
<div class="mcard" style="border-color:#d29922"><b>💡 63G-Şamdan (chandelier)</b><br>{DESC['chand']}</div>
<div class="mcard" style="border-color:#3fb950"><b>👑 Qulla-21 (mevcut canlı)</b><br>{DESC['qulla']}</div>
</div>

<h3>Sonuçlar (5 yıl, aynı zemin — sabit %7.5)</h3>
<table>
<tr><th>Yöntem</th><th>Getiri</th><th>Maks. düşüş</th><th>Kâr faktörü</th><th>İsabet</th><th>Kullanım</th><th>İşlem</th><th>Medyan tutuş</th></tr>
{a_full_table}
</table>
<p class="mut">Kâr faktörü = kazançların toplamı / kayıpların toplamı (1'in üstü kârlı; yüksek = verimli).
Maks. düşüş = zirveden en dip noktaya kadarki en kötü geri çekilme. İsabet = kârlı işlem oranı.</p>

<h3>Özsermaye eğrisi (100 = başlangıç, log ölçek)</h3>
<div id="ch_a" class="chart"></div>
<div class="leg">{A_leg}</div>

<h3>Rejim dayanıklılığı (pencere bazlı getiri / düşüş)</h3>
<table>
<tr><th>Dönem</th>{a_win_head}</tr>
{a_win_table}
</table>

<h3>SPY karşısında — kısa & uzun vade (bugüne kadar)</h3>
<p class="mut">Her hücre o dönemin toplam getirisi; <b>kalın</b> = o dönemde SPY'ı geçti. Son sütun SPY (al-tut, aynı dönem). Hepsi bugüne (2026-06-30) kadar geriye trailing.</p>
<table>
<tr><th>Dönem</th>{trail_head}</tr>
{trail_table}
</table>
<div class="card">
<p><b>Basit dille:</b> Uzun vadede (5y/2y) yöntemler SPY'ı ham getiride genelde geriden takip eder — bu tasarım gereği
(RS top-50 + kapanış&lt;SMA200 kapısı ayı dönemlerinde nakde geçer, boğanın tamamına binmez). Kısa/yakın vadede
tablo değişir: 👑 Qulla-21 son <b>1 yıl</b> {A_trail['qulla']['1 yıl']['roi']:+.0f}% (SPY {trail_spy['1 yıl']:+.0f}%),
<b>6 ay</b> {A_trail['qulla']['6 ay']['roi']:+.0f}% (SPY {trail_spy['6 ay']:+.0f}%),
<b>1 ay</b> {A_trail['qulla']['1 ay']['roi']:+.0f}% (SPY {trail_spy['1 ay']:+.0f}%).</p>
<p class="mut">⚠️ Kısa pencereler (6 ay, özellikle 1 ay) <b>çok az işlem</b> içerir → gürültülüdür, tek tek sonuçlar
şansa açıktır; trend/istatistik için 2y+ pencerelere bakın. Kısa vade sadece "şu an nabız" göstergesidir.</p>
</div>

<h3>Basit dille sonuç</h3>
<div class="card">
<p>Aynı hisselerde, aynı boyutta koşulunca yöntemler net ayrışıyor:</p>
<ul>
<li><b>En yüksek ham getiri:</b> {top_roi}. Ama ham getiri tek başına aldatıcıdır — yüksek getiri genelde
daha derin düşüşle gelir.</li>
<li><b>En verimli (kâr faktörü):</b> {top_pf} — birim risk başına en çok kâr.</li>
<li><b>En sığ düşüş (en az sarsıntı):</b> {top_dd}.</li>
</ul>
<p><b>Neden 👑 Qulla-21 seçildi?</b> Çünkü uçlardan birini değil, <b>dengeyi</b> temsil ediyor.
🏆 kârı çok erken alıp büyük trendleri kaçırır (yüksek isabet, küçük kazanç). 💡 şamdan büyük trendleri yakalar
ama isabeti düşüktür ve uzun "düz/kayıp" dönemlere + derin tekil geri çekilmelere katlanmayı gerektirir
(psikolojik olarak zor). 📐 saf ortalamalara güvendiği için testere piyasada sık yanılır. Qulla-21, 🏆'nın
<b>+2R hızlı kâr güvenliğini</b> 💡/📐'nin <b>trend runner'ıyla</b> birleştirir: yarısını erken kilitler
(moral + nakit), yarısını 21-EMA ile trende bırakır. Ham getiride mutlaka birinci olmayabilir ama
<b>getiri–risk–taşınabilirlik üçgeninde</b> en yaşanabilir profil bu.</p>
</div>

<h2>B) Sermaye Konuşlandırma — Cash-Drag ve COMBO</h2>
<div class="card">
<p>Yöntem sabitlendikten (Qulla-21) sonra ikinci soru: <b>sermaye ne kadar çalışıyor?</b> Baz kurulumda
(%5/slot) sorun şu: +2R yarısı birkaç günde çıkıp nakde dönüyor, ama kalan 21-EMA runner haftalarca
<b>slotu işgal ediyor</b>. 20-slot tavanı pozisyon <i>sayısını</i> kısıtladığı için boşalan nakit yeniden
konuşlanamıyor → ortalama kullanım yalnız <b>%{st_b['depl']:.0f}</b> (sermayenin yarısı boşta).</p>
<p><b>COMBO çözümü:</b> poz boyutu %5→%7.5 <b>ve</b> +2R yarısı çıkınca kalan runner slotu boşaltsın
(<code>free_runner_slots</code>) → boşalan sermaye yeniden konuşlanır. Kullanım %{st_b['depl']:.0f}→
<b>%{st_c['depl']:.0f}</b>. Aynı giriş/çıkış, sadece daha çok sermaye çalışıyor.</p>
</div>
<div class="kpis">
 <div class="kpi"><div class="l">Sermaye kullanımı — baz → combo</div><div class="v">%{st_b['depl']:.0f} → <span class="pos">%{st_c['depl']:.0f}</span></div></div>
 <div class="kpi"><div class="l">Getiri (5y)</div><div class="v">{st_b['roi']:+.0f}% → <span class="pos">{st_c['roi']:+.0f}%</span></div></div>
 <div class="kpi"><div class="l">Maks. düşüş (bedel)</div><div class="v">{st_b['dd']:.1f}% → <span class="neg">{st_c['dd']:.1f}%</span></div></div>
 <div class="kpi"><div class="l">Kâr faktörü</div><div class="v">{pf_s(st_b['pf'])} → {pf_s(st_c['pf'])}</div></div>
</div>
<h3>Özsermaye & Drawdown — baz vs COMBO</h3>
<div id="ch_b" class="chart"></div>
<div class="leg"><b style="color:#3fb950">■</b> COMBO (%7.5 + slot-serbest) &nbsp; <b style="color:#f85149">■</b> Qulla-21 baz (%5) &nbsp; <b style="color:#8b949e">■</b> SPY</div>
<div id="ch_dd" class="chart"></div>
<div class="leg"><b style="color:#3fb950">■</b> COMBO &nbsp; <b style="color:#f85149">■</b> baz — <span class="mut">daha yüksek kullanım = daha derin düşüş (kaldıraç bedeli)</span></div>
<p class="mut"><b>Önemli:</b> COMBO bir kaldıraçtır — getiriyi de riski de büyütür (düşüş {st_b['dd']:.1f}%→{st_c['dd']:.1f}%).
Ve slot-serbest yalnız <b>split çıkışta</b> (Qulla-21/📐) çalışır; 🏆 ve 💡 bölünmez olduğu için onlara uygulanamaz —
combo bu yüzden Bölüm A'nın değil, Qulla-21'e özgü bir konuşlandırma katmanıdır.</p>

<h2>C) Giriş Miktarı × Slot Sayısı — Isı Haritası</h2>
<div class="card">
<p>Yöntem (👑 Qulla-21) ve konuşlandırma (combo) sabitlendi. Son ayar: her pozisyona sermayenin
<b>yüzde kaçı</b> girsin (giriş miktarı) ve aynı anda <b>kaç pozisyon</b> tutulsun (slot sayısı)?
İkisi birlikte "ne kadar kaldıraç" demektir. Aşağıdaki ızgara, canlı combo zemininde (RS top-50 · sp500_ndx · 5y)
her kombinasyonun 5 yıllık getirisini gösterir — <b>koyu yeşil = yüksek getiri</b>. Mavi çerçeveli ★ =
<b>şu anki canlı ayar (20 slot × %7.5)</b>.</p>
</div>
<table style="text-align:center">
<tr><th>slot ↓ / boyut →</th>{heat_head}</tr>
{heat_rows}
</table>
<p class="mut">Her hücre: büyük sayı = 5y getiri · altında <b>DD</b> (maks. düşüş) · <b>PF</b> (kâr faktörü) · <b>%</b> (ort. sermaye kullanımı).</p>
<h3>Basit dille sonuç</h3>
<div class="card">
<ul>
<li><b>Boyutu büyütmek (tabloda sağa):</b> getiriyi artırır ama düşüşü de derinleştirir — saf kaldıraç.
Belli bir noktadan sonra sermaye zaten dolduğu için (kullanım ~%100) getiri artışı <b>doygunlaşır</b>;
o noktadan sonrası çoğunlukla sadece daha fazla risktir, daha fazla getiri değil.</li>
<li><b>Slot sayısını artırmak (tabloda yukarı):</b> aynı boyutta daha çok slot = daha çok çeşitlendirme ve
daha çok konuşlanmış sermaye; ama slot başına pay küçüldüğü için tek bir ismin katkısı azalır. Çok az slot =
yoğunlaşma (yüksek getiri, yüksek risk); çok fazla slot = seyrelme.</li>
<li><b>En yüksek ham getiri:</b> {grid_best_roi}.</li>
<li><b>En iyi risk-ayarlı (kâr faktörü):</b> {grid_best_pf}.</li>
<li><b>En sığ düşüş (en sakin):</b> {grid_shallow}.</li>
<li><b>Şu anki canlı (20 slot × %7.5):</b> ROI {gl['roi']:+.0f}% · DD {gl['dd']:.0f}% · PF {pf_s(gl['pf'])} ·
kullanım %{gl['depl']:.0f}.</li>
</ul>
<p><b>Karar okuması:</b> En yüksek getirili hücre genelde en derin düşüşe de sahiptir; "en iyi" tanımın
(getiri mi, sakinlik mi) hücreyi belirler. Canlı ayar (20×%7.5) getiriyi kovalayan uçta değil, kullanımı
neredeyse tam (%{gl['depl']:.0f}) yapan ama düşüşü hâlâ makul tutan dengeli bir noktada. Daha yüksek getiri
isteyen boyutu/sloti artırabilir — ama tablo gösteriyor ki bunun bedeli doğrudan daha derin drawdown; getiri
tarafı ise doygunluğa yaklaştığı için sınırlı.</p>
</div>

<h2>D) Aylık Getiri — baz vs COMBO</h2>
<h3 class="pos">COMBO (%7.5 + slot-serbest)</h3>
{monthly_html(eq_c)}
<h3 class="neg">Qulla-21 baz (%5)</h3>
{monthly_html(eq_b)}

<h2>E) Riskler ve Dürüst Okuma</h2>
<blockquote>Hiçbir backtest gelecek vaadi değildir. Aşağıdaki maddeler bu karşılaştırmanın hangi koşullarda
yanıltabileceğini tanımlar.</blockquote>
<ul>
<li><b>Ham getiri ≠ en iyi:</b> Bölüm A'da en yüksek getirili yöntem genelde en derin düşüşe de sahiptir.
"Kazanan" tanımın (getiri mi, sakinlik mi, taşınabilirlik mi) sonucu belirler; Qulla-21 denge için seçildi.</li>
<li><b>COMBO = kaldıraç:</b> Getiri {st_b['roi']:+.0f}%→{st_c['roi']:+.0f}% çıkarken düşüş {st_b['dd']:.1f}%→{st_c['dd']:.1f}%
derinleşir; sert ayıda combo bazdan daha çok kaybeder. Risk-iştahı kararıdır.</li>
<li><b>Havuz derinliği:</b> COMBO'nun kazancı boşalan sermayeyi kaliteli RS top-50 adaylarıyla doldurmaya dayanır;
sp500_ndx (~{NPOOL}) derinliği bu yüzden şart (dar havuzda etki zayıflar).</li>
<li><b>Küçük örneklem + seçim yanlılığı:</b> Sınırlı işlem sayısı; parametreler az sayıda varyant denenerek seçildi.
İhtiyatlı beklenti rapor edilen rakamların altındadır.</li>
<li><b>Veri:</b> FMP fiyatları split-ayarlı, temettü-ayarsız. Evren bugünün endeks bileşenlerinden türetildiği için
sınırlı <i>survivorship</i> yanlılığı içerir — tüm yöntemlere <b>eşit</b> uygulandığından göreli sıralamayı bozmaz.</li>
</ul>

<h2>F) Durum</h2>
<div class="card">
<p>Giriş/çıkış olarak <b>👑 Qulla-21</b> canlıda; sermaye konuşlandırması <b>2026-07-01'de COMBO'ya</b> alındı
(defter aynı çapadan, 2026-05-27, baştan combo ile kuruldu). Bırakılan 3 yöntem (🏆/📐/💡) bu raporda
referans/karşılaştırma amacıyla korunur; canlıda kullanılmıyor. Geri dönüş kolay:
<code>qulla_paper._cfg</code>'deki iki satır (poz%7.5 + free_runner_slots) eski değerlere çevrilir.</p>
</div>
<p class="mut">Üretim: <code>gen_exp_report.py</code> · Bu sayfa salt-okur bir rapordur; canlı trade mantığına etkisi yoktur.</p>
</div>
<script src="/static/lwc.js"></script>
<script>
const DATA = {json.dumps(data)};
function mkChart(id, logScale){{
  const el = document.getElementById(id);
  const ch = LightweightCharts.createChart(el, {{
    layout:{{background:{{color:'#161b22'}},textColor:'#8b949e'}},
    grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},
    rightPriceScale:{{borderColor:'#30363d',mode:logScale?1:0}},
    timeScale:{{borderColor:'#30363d'}}, height:330, width:el.clientWidth}});
  new ResizeObserver(()=>ch.applyOptions({{width:el.clientWidth}})).observe(el);
  return ch;
}}
const eqA = mkChart('ch_a', true);
{A_lines_js}
eqA.addLineSeries({{color:'#8b949e',lineWidth:1}}).setData(DATA.spy);
eqA.timeScale().fitContent();
const eqB = mkChart('ch_b', true);
eqB.addLineSeries({{color:'#3fb950',lineWidth:2}}).setData(DATA.eq_c);
eqB.addLineSeries({{color:'#f85149',lineWidth:2}}).setData(DATA.eq_b);
eqB.addLineSeries({{color:'#8b949e',lineWidth:1}}).setData(DATA.spy);
eqB.timeScale().fitContent();
const dd = mkChart('ch_dd', false);
dd.addAreaSeries({{lineColor:'#3fb950',topColor:'rgba(63,185,80,.25)',bottomColor:'rgba(63,185,80,0)',lineWidth:2}}).setData(DATA.dd_c);
dd.addAreaSeries({{lineColor:'#f85149',topColor:'rgba(248,81,73,.25)',bottomColor:'rgba(248,81,73,0)',lineWidth:2}}).setData(DATA.dd_b);
dd.timeScale().fitContent();
</script></body></html>"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(f"Rapor yazıldı: {OUT} ({len(html)//1024} KB)")

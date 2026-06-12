#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🪙 Kripto adaptasyonu GENEL BAKIŞ raporu → dashboard_static/crypto_report.html

Commit edilmiş backtest CSV'lerinden okur (yeniden koşu GEREKMEZ):
  backtests/crypto_qswing_3exit_5period_SUMMARY.csv   (15 hücre)
  backtests/crypto_regime_grid.csv                    (BTC ATR-rejim eşik ızgarası, 2y)
  backtests/sp500_qswing_3exit_5period_SUMMARY.csv    (hisse kıyası)

Tamamen bağımsız HTML: inline CSS + inline SVG, CDN/JS bağımlılığı YOK.
Tema: Gece Masası (paper_dashboard ile aynı palet). Dashboard /kripto-rapor'dan servis edilir.

Kullanım: python3 gen_crypto_report.py
"""
import csv
import html as _h
import os
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "dashboard_static", "crypto_report.html")

# Gece Masası paleti (paper_dashboard ile aynı)
C = {"gece": "#101216", "defter": "#15181d", "defter2": "#1b1f26", "cizgi": "rgba(174,188,214,.10)",
     "cizgi2": "rgba(174,188,214,.20)", "ink": "#e8ecf3", "gumus": "#a9b2c1", "sis": "#69727f",
     "kar": "#3ecf8e", "zarar": "#f07b7b", "kehribar": "#e8b04b",
     "altin": "#d4a843", "buz": "#7eb3e3", "fosfor": "#5ee0a0", "btc": "#f7931a"}
EXIT_COLOR = {"atr": C["altin"], "hybrid": C["buz"], "split": C["fosfor"]}
EXIT_LABEL = {"atr": "🏆 ATR-trail", "hybrid": "📐 8/21-EMA hibrit", "split": "💡 ½hibrit+½ATR"}
PERIODS = ["5y", "3y", "2y", "1y", "6mo"]
EXITS = ["atr", "hybrid", "split"]


def _read(name):
    with open(os.path.join(ROOT, "backtests", name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(x, d=1):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v == float("inf"):
        return "∞"
    return f"{v:,.{d}f}"


def _sgn(x, d=1, suf=""):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    cls = "pos" if v >= 0 else "neg"
    return f'<span class="{cls}">{"+" if v >= 0 else ""}{v:,.{d}f}{suf}</span>'


# ---------------------------------------------------------------- SVG grafikler
def chart_roi_vs_btc(rows):
    """Pencere başına: 3 çıkışın ROI çubukları + BTC al-tut çubuğu (gruplu bar, SVG)."""
    by = {(r["exit_key"], r["period"]): r for r in rows}
    vals = [float(by[(e, p)]["roi_pct"]) for p in PERIODS for e in EXITS]
    btc = {p: float(by[("atr", p)]["bench_roi_pct"]) for p in PERIODS}
    vals += list(btc.values())
    lo, hi = min(vals + [0]), max(vals)
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    W, H, ML, MB, MT = 920, 320, 46, 34, 14
    PW = (W - ML - 10) / len(PERIODS)              # pencere genişliği
    def y(v): return MT + (hi - v) / (hi - lo) * (H - MT - MB)
    bw = PW / 6.2                                   # 4 çubuk + boşluk
    s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img">']
    # ızgara + eksen
    for gv in (-40, 0, 40, 80, 120):
        if lo <= gv <= hi:
            s.append(f'<line x1="{ML}" y1="{y(gv):.1f}" x2="{W-10}" y2="{y(gv):.1f}" '
                     f'stroke="{C["cizgi2" if gv == 0 else "cizgi"]}" stroke-width="1"/>'
                     f'<text x="{ML-6}" y="{y(gv)+4:.1f}" text-anchor="end" font-size="11" '
                     f'fill="{C["sis"]}">{gv}%</text>')
    for i, p in enumerate(PERIODS):
        x0 = ML + i * PW + PW * 0.14
        bars = [(EXIT_COLOR[e], float(by[(e, p)]["roi_pct"])) for e in EXITS] + [(C["btc"], btc[p])]
        for j, (col, v) in enumerate(bars):
            bx = x0 + j * bw * 1.18
            yt, yb = (y(v), y(0)) if v >= 0 else (y(0), y(v))
            hh = max(abs(yb - yt), 1.5)
            s.append(f'<rect x="{bx:.1f}" y="{yt:.1f}" width="{bw:.1f}" height="{hh:.1f}" '
                     f'rx="2" fill="{col}" fill-opacity="{0.55 if j == 3 else 0.92}"/>')
            s.append(f'<text x="{bx+bw/2:.1f}" y="{(yt-4) if v >= 0 else (yb+11):.1f}" text-anchor="middle" '
                     f'font-size="9.5" fill="{C["gumus"]}">{v:+.0f}</text>')
        s.append(f'<text x="{ML+i*PW+PW/2:.1f}" y="{H-10}" text-anchor="middle" font-size="12" '
                 f'font-weight="600" fill="{C["ink"]}">{p}</text>')
    s.append("</svg>")
    return "".join(s)


def chart_regime(grid):
    """Hibrit çıkış: eşik → ROI (yeşil) ve MaxDD (kırmızı, negatif) çubukları."""
    rows = [r for r in grid if r["exit_key"] == "hybrid"]
    W, H, ML, MB, MT = 920, 300, 46, 50, 14
    vals = [float(r["roi_pct"]) for r in rows] + [float(r["max_dd_pct"]) for r in rows]
    lo, hi = min(vals) - 6, max(vals) + 10
    PW = (W - ML - 10) / len(rows)
    def y(v): return MT + (hi - v) / (hi - lo) * (H - MT - MB)
    bw = PW / 3.4
    s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img">']
    for gv in (-30, 0, 30, 60):
        if lo <= gv <= hi:
            s.append(f'<line x1="{ML}" y1="{y(gv):.1f}" x2="{W-10}" y2="{y(gv):.1f}" '
                     f'stroke="{C["cizgi2" if gv == 0 else "cizgi"]}"/>'
                     f'<text x="{ML-6}" y="{y(gv)+4:.1f}" text-anchor="end" font-size="11" '
                     f'fill="{C["sis"]}">{gv}%</text>')
    for i, r in enumerate(rows):
        x0 = ML + i * PW + PW * 0.18
        champ = r["regime_atr_threshold"] == "2.5"
        for j, (col, v) in enumerate([(C["kar"], float(r["roi_pct"])), (C["zarar"], float(r["max_dd_pct"]))]):
            bx = x0 + j * bw * 1.25
            yt, yb = (y(v), y(0)) if v >= 0 else (y(0), y(v))
            s.append(f'<rect x="{bx:.1f}" y="{yt:.1f}" width="{bw:.1f}" height="{max(abs(yb-yt),1.5):.1f}" '
                     f'rx="2" fill="{col}" fill-opacity="{0.95 if champ else 0.55}"/>')
            s.append(f'<text x="{bx+bw/2:.1f}" y="{(yt-4) if v >= 0 else (yb+11):.1f}" text-anchor="middle" '
                     f'font-size="9.5" fill="{C["gumus"]}">{v:+.0f}</text>')
        lbl = r["regime_atr_threshold"]
        s.append(f'<text x="{ML+i*PW+PW/2:.1f}" y="{H-26}" text-anchor="middle" font-size="12.5" '
                 f'font-weight="{700 if champ else 500}" fill="{C["kehribar"] if champ else C["ink"]}">'
                 f'{lbl}{" ★" if champ else ""}</text>')
        s.append(f'<text x="{ML+i*PW+PW/2:.1f}" y="{H-10}" text-anchor="middle" font-size="10" '
                 f'fill="{C["sis"]}">{r["trades"]} işlem</text>')
    s.append("</svg>")
    return "".join(s)


# ---------------------------------------------------------------- tablolar
def table_15(rows):
    by = {(r["exit_key"], r["period"]): r for r in rows}
    out = ['<table><tr><th>Pencere</th><th>Çıkış</th><th>ROI</th><th>BTC al-tut</th>'
           '<th>Alpha</th><th>MaxDD</th><th>Win</th><th>PF</th><th>İşlem</th></tr>']
    for p in PERIODS:
        for k, e in enumerate(EXITS):
            r = by[(e, p)]
            best = max(EXITS, key=lambda x: float(by[(x, p)]["alpha_pct"]))
            star = " ★" if e == best and float(r["trades"]) > 0 else ""
            pf = _f(r["profit_factor"], 2)
            out.append(
                f'<tr{" class=sep" if k == 0 else ""}>'
                f'<td>{("<b>" + p + "</b><br><span class=muted style=font-size:10.5px>" + r["start"] + " → " + r["end"] + "</span>") if k == 0 else ""}</td>'
                f'<td><span class="dot" style="background:{EXIT_COLOR[e]}"></span>{EXIT_LABEL[e][2:]}{star}</td>'
                f'<td>{_sgn(r["roi_pct"], 1, "%")}</td><td>{_sgn(r["bench_roi_pct"], 1, "%")}</td>'
                f'<td><b>{_sgn(r["alpha_pct"], 1, " pt")}</b></td>'
                f'<td class="neg">{_f(r["max_dd_pct"])}%</td>'
                f'<td>{_f(r["win_rate_pct"], 0)}%</td><td>{pf}</td><td>{r["trades"]}</td></tr>')
    out.append("</table>")
    return "".join(out)


def table_regime(grid):
    out = ['<table><tr><th>Çıkış</th><th>Eşik (BTC ATR20%)</th><th>ROI</th><th>Alpha</th>'
           '<th>MaxDD</th><th>Win</th><th>PF</th><th>İşlem</th></tr>']
    for e in EXITS:
        rows = [r for r in grid if r["exit_key"] == e]
        for k, r in enumerate(rows):
            champ = e == "hybrid" and r["regime_atr_threshold"] == "2.5"
            thr = r["regime_atr_threshold"]
            out.append(
                f'<tr{" class=champ" if champ else (" class=sep" if k == 0 else "")}>'
                f'<td>{("<span class=dot style=background:" + EXIT_COLOR[e] + "></span>" + EXIT_LABEL[e][2:]) if k == 0 or champ else ""}</td>'
                f'<td>{"filtre kapalı" if thr == "kapalı" else thr + "%"}{" ★ CANLI" if champ else ""}</td>'
                f'<td>{_sgn(r["roi_pct"], 1, "%")}</td><td>{_sgn(r["alpha_pct"], 1, " pt")}</td>'
                f'<td class="neg">{_f(r["max_dd_pct"])}%</td><td>{_f(r["win_rate_pct"], 0)}%</td>'
                f'<td>{_f(r["profit_factor"], 2)}</td><td>{r["trades"]}</td></tr>')
    out.append("</table>")
    return "".join(out)


def table_short(srows):
    out = ['<table><tr><th>Pencere</th><th>Kapatma</th><th>Kilit</th><th>ROI</th>'
           '<th>BTC al-tut</th><th>Alpha</th><th>MaxDD</th><th>Win</th><th>PF</th><th>İşlem</th></tr>']
    for p in PERIODS:
        rows = [r for r in srows if r["period"] == p]
        for k, r in enumerate(rows):
            n = int(r["trades"])
            tiny = ' <span class="muted" title="örneklem çok küçük — istatistiksel anlamı yok">(n!)</span>' if 0 < n < 5 else ""
            champ = p in ("1y", "6mo") and r["exit_key"] == "hybrid" and r["lock"] == "kilitsiz"
            out.append(
                f'<tr{" class=champ" if champ else (" class=sep" if k == 0 else "")}>'
                f'<td>{("<b>" + p + "</b>") if k == 0 else ""}</td>'
                f'<td>{"8/21-EMA hibrit" if r["exit_key"] == "hybrid" else "ATR-cover 2.5×"}</td>'
                f'<td>{r["lock"]}</td>'
                f'<td>{_sgn(r["roi_pct"], 1, "%")}</td><td>{_sgn(r["bench_roi_pct"], 1, "%")}</td>'
                f'<td><b>{_sgn(r["alpha_pct"], 1, " pt")}</b></td>'
                f'<td class="neg">{_f(r["max_dd_pct"])}%</td><td>{_f(r["win_rate_pct"], 0)}%</td>'
                f'<td>{_f(r["profit_factor"], 2)}</td><td>{n}{tiny}</td></tr>')
    out.append("</table>")
    return "".join(out)


MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def _read_equity(name="crypto_combined_equity_5y.csv"):
    """[(tarih, {kolon: değer})] — yoksa boş liste."""
    try:
        rows = _read(name)
    except FileNotFoundError:
        return []
    return [(r["date"], {k: float(v) for k, v in r.items() if k != "date"}) for r in rows]


def _monthly(eqrows, col):
    """Ay-sonu değerlerinden aylık % getiriler + yıllık bileşik %. (motorun
    monthly_returns_table'ı ile aynı tanım: resample ay-sonu → pct_change)."""
    me, last_ym, last_v = [], None, None
    for d, vals in eqrows:
        ym = (int(d[:4]), int(d[5:7]))
        if last_ym is not None and ym != last_ym:
            me.append((*last_ym, last_v))
        last_ym, last_v = ym, vals[col]
    me.append((*last_ym, last_v))
    rets = {}
    for i in range(1, len(me)):
        y, m, v = me[i]
        pv = me[i - 1][2]
        if pv > 0:
            rets[(y, m)] = (v / pv - 1) * 100
    yearly = {}
    for (y, _m), r in rets.items():
        yearly[y] = yearly.get(y, 1.0) * (1 + r / 100)
    return rets, {y: (v - 1) * 100 for y, v in yearly.items()}


def heatmap_monthly(title, rets, yearly):
    """Yıl × ay ısı ızgarası (HTML tablo; hücre arkaplanı getiri şiddetiyle)."""
    years = sorted({y for y, _ in rets})
    out = [f'<h3 style="font-size:11px;font-weight:650;letter-spacing:.07em;text-transform:uppercase;'
           f'color:{C["gumus"]};margin:18px 0 8px">{title}</h3>',
           '<table class="hm"><tr><th>Yıl</th>' + "".join(f"<th>{m}</th>" for m in MONTHS)
           + '<th>Yıl%</th></tr>']
    def cell(r, strong=False):
        if r is None:
            return f'<td class="muted" style="text-align:right">·</td>'
        a = min(0.50, abs(r) / 40.0)
        bg = f"rgba(62,207,142,{a:.2f})" if r >= 0 else f"rgba(240,123,123,{a:.2f})"
        return (f'<td style="text-align:right;background:{bg}">'
                f'{"<b>" if strong else ""}{r:+.1f}{"</b>" if strong else ""}</td>')
    for y in years:
        out.append(f"<tr><td><b>{y}</b></td>"
                   + "".join(cell(rets.get((y, m))) for m in range(1, 13))
                   + cell(yearly.get(y), strong=True) + "</tr>")
    out.append("</table>")
    return "".join(out)


def _year_ticks(s, eqrows, x, MT, H, MB):
    seen = set()
    for i, (d, _v) in enumerate(eqrows):
        yy = d[:4]
        if yy not in seen:
            seen.add(yy)
            if i > 0:
                s.append(f'<line x1="{x(i):.1f}" y1="{MT}" x2="{x(i):.1f}" y2="{H-MB}" '
                         f'stroke="{C["cizgi"]}"/>'
                         f'<text x="{x(i)+3:.1f}" y="{H-8}" font-size="11" fill="{C["sis"]}">{yy}</text>')


def chart_equity(eqrows):
    """Özsermaye eğrileri: ⚖️ birleşik (kısa ½) vs ₿ BTC al-tut (100k$ başlangıç, lineer)."""
    sv = [v["combined_half"] for _d, v in eqrows]
    bv = [v["btc_bh"] for _d, v in eqrows]
    lo = min(min(sv), min(bv)) * 0.96
    hi = max(max(sv), max(bv)) * 1.04
    n = len(eqrows)
    W, H, ML, MB, MT = 920, 300, 56, 26, 8
    def y(v): return MT + (hi - v) / (hi - lo) * (H - MT - MB)
    def x(i): return ML + i / max(n - 1, 1) * (W - ML - 12)
    step = max(1, n // 460)
    s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img">']
    for gv in (50_000, 100_000, 150_000, 200_000, 250_000, 300_000, 350_000):
        if lo <= gv <= hi:
            s.append(f'<line x1="{ML}" y1="{y(gv):.1f}" x2="{W-12}" y2="{y(gv):.1f}" '
                     f'stroke="{C["cizgi2" if gv == 100_000 else "cizgi"]}"/>'
                     f'<text x="{ML-6}" y="{y(gv)+4:.1f}" text-anchor="end" font-size="11" '
                     f'fill="{C["sis"]}">{gv//1000}k</text>')
    _year_ticks(s, eqrows, x, MT, H, MB)
    idx = list(range(0, n, step)) + ([n - 1] if (n - 1) % step else [])
    bpts = " ".join(f"{x(i):.1f},{y(bv[i]):.1f}" for i in idx)
    s.append(f'<polyline points="{bpts}" fill="none" stroke="{C["btc"]}" '
             f'stroke-width="1.1" stroke-opacity="0.75"/>')
    spts = " ".join(f"{x(i):.1f},{y(sv[i]):.1f}" for i in idx)
    s.append(f'<polygon points="{x(idx[0]):.1f},{y(lo):.1f} {spts} {x(idx[-1]):.1f},{y(lo):.1f}" '
             f'fill="{C["buz"]}" fill-opacity="0.10" stroke="none"/>')
    s.append(f'<polyline points="{spts}" fill="none" stroke="{C["buz"]}" stroke-width="1.5"/>')
    s.append("</svg>")
    return "".join(s), sv[-1], bv[-1]


def chart_drawdown(eqrows, cols=(("combined_half", None, "⚖️ birleşik (kısa ½)"),
                                 ("btc_bh", None, "₿ BTC al-tut"))):
    """Sualtı (underwater) grafiği: zirveden düşüş %, iki seri (SVG)."""
    series = {}
    for col, _c, _l in cols:
        vals, peak, dd = [], 0.0, []
        for _d, v in eqrows:
            x = v[col]
            peak = max(peak, x)
            dd.append((x / peak - 1) * 100)
        series[col] = dd
    n = len(eqrows)
    lo = min(min(s) for s in series.values())
    lo = lo * 1.06 - 1
    W, H, ML, MB, MT = 920, 260, 46, 26, 8
    def y(v): return MT + (0 - v) / (0 - lo) * (H - MT - MB)
    def x(i): return ML + i / max(n - 1, 1) * (W - ML - 12)
    step = max(1, n // 460)
    s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img">']
    for gv in (0, -20, -40, -60):
        if gv >= lo:
            s.append(f'<line x1="{ML}" y1="{y(gv):.1f}" x2="{W-12}" y2="{y(gv):.1f}" '
                     f'stroke="{C["cizgi2" if gv == 0 else "cizgi"]}"/>'
                     f'<text x="{ML-6}" y="{y(gv)+4:.1f}" text-anchor="end" font-size="11" '
                     f'fill="{C["sis"]}">{gv}%</text>')
    _year_ticks(s, eqrows, x, MT, H, MB)
    # BTC: çizgi · strateji: dolgulu alan
    idx = list(range(0, n, step)) + ([n - 1] if (n - 1) % step else [])
    btc_pts = " ".join(f"{x(i):.1f},{y(series['btc_bh'][i]):.1f}" for i in idx)
    s.append(f'<polyline points="{btc_pts}" fill="none" stroke="{C["btc"]}" '
             f'stroke-width="1.1" stroke-opacity="0.75"/>')
    st_pts = " ".join(f"{x(i):.1f},{y(series['combined_half'][i]):.1f}" for i in idx)
    s.append(f'<polygon points="{x(idx[0]):.1f},{y(0):.1f} {st_pts} {x(idx[-1]):.1f},{y(0):.1f}" '
             f'fill="{C["buz"]}" fill-opacity="0.22" stroke="none"/>')
    s.append(f'<polyline points="{st_pts}" fill="none" stroke="{C["buz"]}" stroke-width="1.4"/>')
    s.append("</svg>")
    return "".join(s), min(series["combined_half"]), min(series["btc_bh"])


CMB_LABEL = {"long": "🟢 uzun-tek (kilit 2.5)", "short": "🔻 kısa-tek (kilitsiz)",
             "combined": "⚖️ birleşik", "combined_half": "⚖️ birleşik (kısa ½ boy)"}
CMB_COLOR = {"long": C["altin"], "combined": C["buz"], "combined_half": C["fosfor"]}


def chart_combined(rows):
    """Pencere başına: uzun-tek / birleşik / birleşik-½ / BTC al-tut ROI çubukları."""
    by = {(r["side"], r["period"]): r for r in rows}
    sides = ["long", "combined", "combined_half"]
    vals = [float(by[(sd, p)]["roi_pct"]) for p in PERIODS for sd in sides]
    btc = {p: float(by[("long", p)]["bench_roi_pct"]) for p in PERIODS}
    vals += list(btc.values())
    lo, hi = min(vals + [0]), max(vals)
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    W, H, ML, MB, MT = 920, 320, 46, 34, 14
    PW = (W - ML - 10) / len(PERIODS)
    def y(v): return MT + (hi - v) / (hi - lo) * (H - MT - MB)
    bw = PW / 6.2
    s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img">']
    for gv in (-40, 0, 40, 80, 120):
        if lo <= gv <= hi:
            s.append(f'<line x1="{ML}" y1="{y(gv):.1f}" x2="{W-10}" y2="{y(gv):.1f}" '
                     f'stroke="{C["cizgi2" if gv == 0 else "cizgi"]}" stroke-width="1"/>'
                     f'<text x="{ML-6}" y="{y(gv)+4:.1f}" text-anchor="end" font-size="11" '
                     f'fill="{C["sis"]}">{gv}%</text>')
    for i, p in enumerate(PERIODS):
        x0 = ML + i * PW + PW * 0.14
        bars = [(CMB_COLOR[sd], float(by[(sd, p)]["roi_pct"])) for sd in sides] + [(C["btc"], btc[p])]
        for j, (col, v) in enumerate(bars):
            bx = x0 + j * bw * 1.18
            yt, yb = (y(v), y(0)) if v >= 0 else (y(0), y(v))
            s.append(f'<rect x="{bx:.1f}" y="{yt:.1f}" width="{bw:.1f}" height="{max(abs(yb-yt),1.5):.1f}" '
                     f'rx="2" fill="{col}" fill-opacity="{0.55 if j == 3 else 0.92}"/>')
            s.append(f'<text x="{bx+bw/2:.1f}" y="{(yt-4) if v >= 0 else (yb+11):.1f}" text-anchor="middle" '
                     f'font-size="9.5" fill="{C["gumus"]}">{v:+.0f}</text>')
        s.append(f'<text x="{ML+i*PW+PW/2:.1f}" y="{H-10}" text-anchor="middle" font-size="12" '
                 f'font-weight="600" fill="{C["ink"]}">{p}</text>')
    s.append("</svg>")
    return "".join(s)


def table_combined(rows):
    by = {(r["side"], r["period"]): r for r in rows}
    out = ['<table><tr><th>Pencere</th><th>Taraf</th><th>ROI</th><th>BTC al-tut</th>'
           '<th>Alpha</th><th>MaxDD</th><th>PF</th><th>İşlem (U·K)</th></tr>']
    for p in PERIODS:
        for k, sd in enumerate(["long", "short", "combined", "combined_half"]):
            r = by.get((sd, p))
            if r is None:
                continue
            nL, nS = r.get("long_trades") or "", r.get("short_trades") or ""
            ntx = f'{r["trades"]}' + (f' <span class="muted">({nL}·{nS})</span>' if nL != "" else "")
            champ = sd == "combined_half"
            out.append(
                f'<tr{" class=champ" if champ else (" class=sep" if k == 0 else "")}>'
                f'<td>{("<b>" + p + "</b>") if k == 0 else ""}</td>'
                f'<td>{CMB_LABEL[sd]}{" ★" if champ else ""}</td>'
                f'<td>{_sgn(r["roi_pct"], 1, "%")}</td><td>{_sgn(r["bench_roi_pct"], 1, "%")}</td>'
                f'<td><b>{_sgn(r["alpha_pct"], 1, " pt")}</b></td>'
                f'<td class="neg">{_f(r["max_dd_pct"])}%</td>'
                f'<td>{_f(r["profit_factor"], 2)}</td><td>{ntx}</td></tr>')
    out.append("</table>")
    return "".join(out)


def table_vs_equity(crypto, sp500):
    cb = {(r["exit_key"], r["period"]): r for r in crypto}
    sb = {(r["exit_key"], r["period"]): r for r in sp500}
    out = ['<table><tr><th>Pencere</th><th>Çıkış</th>'
           '<th>🪙 Kripto alpha<br><span class="muted">(vs BTC al-tut)</span></th>'
           '<th>📈 Hisse alpha<br><span class="muted">(vs SPY al-tut)</span></th>'
           '<th>🪙 işlem</th><th>📈 işlem</th></tr>']
    for p in PERIODS:
        for k, e in enumerate(EXITS):
            c, s = cb[(e, p)], sb[(e, p)]
            out.append(f'<tr{" class=sep" if k == 0 else ""}>'
                       f'<td>{("<b>" + p + "</b>") if k == 0 else ""}</td>'
                       f'<td><span class="dot" style="background:{EXIT_COLOR[e]}"></span>{EXIT_LABEL[e][2:]}</td>'
                       f'<td><b>{_sgn(c["alpha_pct"], 1, " pt")}</b></td>'
                       f'<td>{_sgn(s["alpha_pct"], 1, " pt")}</td>'
                       f'<td>{c["trades"]}</td><td>{s["trades"]}</td></tr>')
    out.append("</table>")
    return "".join(out)


# ---------------------------------------------------------------- sayfa
def build():
    crypto = _read("crypto_qswing_3exit_5period_SUMMARY.csv")
    grid = _read("crypto_regime_grid.csv")
    sp500 = _read("sp500_qswing_3exit_5period_SUMMARY.csv")
    try:
        short = _read("crypto_short_SUMMARY.csv")
    except FileNotFoundError:
        short = []
    try:
        combined = _read("crypto_combined_SUMMARY.csv")
    except FileNotFoundError:
        combined = []
    eqrows = _read_equity()
    try:
        h1 = _read("crypto_1h_SUMMARY.csv")
    except FileNotFoundError:
        h1 = []

    h1_html = ""
    if h1:
        H1LBL = {"long": "🟢 uzun", "short": "🔻 kısa", "combined": "⚖️ birleşik"}
        out = ['<table><tr><th>Pencere</th><th>Taraf</th><th>Kilit (1h ATR%)</th><th>ROI</th>'
               '<th>BTC al-tut</th><th>Alpha</th><th>MaxDD</th><th>Win</th><th>PF</th><th>İşlem</th></tr>']
        order = {"1y": 0, "6mo": 1, "3mo": 2}
        prev_p = None
        for r in sorted(h1, key=lambda x: (order.get(x["period"], 9), x["lock"] != "kapalı", x["side"])):
            champ = r["side"] == "long" and r["lock"] == "0.6"
            cls = " class=champ" if champ else (" class=sep" if r["period"] != prev_p else "")
            prev_p = r["period"]
            out.append(
                f'<tr{cls}><td><b>{r["period"]}</b></td>'
                f'<td>{H1LBL[r["side"]]}{" ★" if champ else ""}</td>'
                f'<td>{"—" if r["lock"] == "kapalı" else r["lock"]}</td>'
                f'<td>{_sgn(r["roi_pct"], 1, "%")}</td><td>{_sgn(r["bench_roi_pct"], 1, "%")}</td>'
                f'<td><b>{_sgn(r["alpha_pct"], 1, " pt")}</b></td>'
                f'<td class="neg">{_f(r["max_dd_pct"])}%</td><td>{_f(r["win_rate_pct"], 0)}%</td>'
                f'<td>{_f(r["profit_factor"], 2)}</td><td>{r["trades"]}</td></tr>')
        out.append("</table>")
        h1_html = f"""<section><h2>⚡ 1 saatlik barlar — aynı yöntem, hızlı ölçek</h2>
<span class="kural">Bar-sayısı semantiği: SMA200=200 saat (~8 gün) · 40-bar kırılım=40 saat · HIGH52/LOW52=365 saat
(~15 gün) · komisyon+slippage AYNI (10bps/bacak) · kısa funding bara bölünür (yine 3bps/gün) ·
kilit eşiği 1h için yeniden ölçüldü (BTC 1h ATR20% medyanı ~0.56) · ★ = risk-ayarlı kazanan</span>
{"".join(out)}
<p class="muted" style="font-size:12.5px;margin-bottom:0">Üç bulgu: (1) <b>1h'de uzun taraf ayı yılında bile çalışıyor</b>
(1y: +%112 kilitsiz · +%102 kilit 0.6 ile DD −%19, BTC −%42 iken) — 200-saatlik "rejim" ayı rallilerinde sık sık açılıyor,
günlük sistemin nakitte beklediği yılda ~1.000+ hızlı trend işlemi alınıyor. (2) <b>KISA taraf 1h'de HER yerde zararda</b>
(1y: −%45, PF 0.75) — saatlik ayı rallileri EMA kapatmalarını testereye çevirir, maliyet oranı tüm kenarı yer; birleşik
defteri de bu aşağı çeker (1h'de doğru yapı: yalnız-uzun + kilit). (3) <b>Maliyet gerçekçiliği uyarısı</b>: yılda 1.000+
işlemde sonuç slippage varsayımına çok duyarlıdır — sabit 8-15bps, ince defterli altcoinlerde saatlik frekansta iyimser
olabilir; canlıya alınmadan önce kağıt-trade ile doğrulanmalı. Günlük sistemle 1:1 karşılaştırma değildir (farklı işlem
ufku); en uzun pencere 1y (saatlik veri derinliği).</p>
</section>

"""

    monthly_html = ""
    if eqrows:
        sr, sy = _monthly(eqrows, "combined_half")
        br, by = _monthly(eqrows, "btc_bh")
        eqsvg, sfin, bfin = chart_equity(eqrows)
        ddsvg, sdd, bdd = chart_drawdown(eqrows)
        monthly_html = f"""<section><h2>Özsermaye, drawdown & aylık ızgara — ⚖️ birleşik (kısa ½) vs ₿ al-tut</h2>
<span class="kural">5y penceresi ({eqrows[0][0]} → {eqrows[-1][0]}) · 100.000$ başlangıç · iki grafik aynı zaman
eksenini paylaşır (üstte özsermaye, altta zirveden düşüş) · aylık % = ay-sonu özsermayeden</span>
<h3 style="font-size:11px;font-weight:650;letter-spacing:.07em;text-transform:uppercase;color:{C['gumus']};margin:14px 0 8px">
Özsermaye eğrisi — günlük</h3>
<div class="legend"><span><span class="dot" style="background:{C['buz']}"></span>⚖️ birleşik (kısa ½) ·
son <b>${sfin:,.0f}</b> ({(sfin/1000-100):+.1f}%)</span>
<span><span class="dot" style="background:{C['btc']}"></span>₿ BTC al-tut · son <b>${bfin:,.0f}</b> ({(bfin/1000-100):+.1f}%)</span></div>
{eqsvg}
<h3 style="font-size:11px;font-weight:650;letter-spacing:.07em;text-transform:uppercase;color:{C['gumus']};margin:20px 0 8px">
Zirveden düşüş (underwater) — günlük</h3>
<div class="legend"><span><span class="dot" style="background:{C['buz']}"></span>⚖️ birleşik (kısa ½) ·
maxDD <b class="neg">{sdd:.1f}%</b></span>
<span><span class="dot" style="background:{C['btc']}"></span>₿ BTC al-tut · maxDD <b class="neg">{bdd:.1f}%</b></span></div>
{ddsvg}
<p class="muted" style="font-size:12.5px;margin:8px 0 0">Eğri okuma: BTC'nin dağ-vadi silüetine karşı stratejinin
basamaklı çizgisi — düz bölümler nakitte beklenen aylar (rejim kapısı/kilit), basamaklar rejim uygunken alınan
trendler. BTC zirvede stratejiden öndeyken vadide çok gerisinde; strateji yolu aynı yere <b>çok daha sığ çukurlarla</b> gidiyor.</p>
{heatmap_monthly("⚖️ Birleşik (kısa ½ boy) ★ — aylık %", sr, sy)}
{heatmap_monthly("₿ BTC al-tut — aylık %", br, by)}
<p class="muted" style="font-size:12.5px;margin-bottom:0">Okuma: stratejinin ızgarasındaki uzun <b>0.0 şeritleri</b>
hata değil — rejim kapısı + oynaklık kilidi o aylarda portföyü <b>nakitte</b> tuttu (BTC satırındaki derin kırmızı
aylarla karşılaştırın). Sualtı grafiğinde fark daha net: BTC iki kez %60+ çukura inerken strateji çukuru
{sdd:.0f}%'te kaldı — momentum sisteminin asıl işi getiri yapmak kadar <b>çukurda olmamak</b>.</p>
</section>

"""
    cb = {(r["exit_key"], r["period"]): r for r in crypto}
    gb = {(r["exit_key"], r["regime_atr_threshold"]): r for r in grid}
    h1y = cb[("hybrid", "1y")]
    g_off, g_on = gb[("hybrid", "kapalı")], gb[("hybrid", "2.5")]

    kpis = [
        ("1y alpha (hibrit çıkış)", _sgn(h1y["alpha_pct"], 1, " pt"),
         f'ROI {_f(h1y["roi_pct"])}% · BTC {_f(h1y["bench_roi_pct"])}%'),
        ("Oynaklık kilidi etkisi (2y · hibrit)",
         f'<span class="neg">{_f(g_off["max_dd_pct"])}%</span> → <span class="pos">{_f(g_on["max_dd_pct"])}%</span> DD',
         f'ROI {_f(g_off["roi_pct"])}% → {_f(g_on["roi_pct"])}% · eşik 2.5'),
        ("Ayı piyasası savunması (6 ay)", '<span class="pos">+29.5 pt</span>',
         "0 işlem — rejim kapısı nakitte bekletti, BTC −29.5%"),
        ("Evren / veri", "75 USDT çifti", "Binance günlük UTC · 6y · komisyon 10bps/bacak"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div>'
        f'<div class="s muted">{s}</div></div>' for l, v, s in kpis)

    phases = [
        ("1 · Veri katmanı + motor", C["btc"],
         "Binance public klines (anahtarsız, sayfalı, sembol-başına önbellek) aynı motora "
         "<code>price_source='binance'</code> olarak takıldı. SPY'ın yerini <b>BTCUSDT</b> aldı "
         "(rejim kapısı + görece güç); sektör/earnings katmanları kriptoda otomatik devre dışı. "
         "Yüzde komisyon (<code>commission_bps=10</code>), 52H penceresi 365 bar. "
         "Hisse davranışı <b>bit-özdeş</b> (326 işlemlik golden regresyon ✓)."),
        ("2 · Kağıt-trade (şampiyon konfig)", C["buz"],
         "<code>crypto_paper_telegram.py</code>: her gün 00:00 UTC kapanışından sonra tarama + "
         "🪙 kağıt portföy + Telegram. Giriş: qswing 40g kırılım + BTC&gt;SMA200 + <b>BTC ATR20%&gt;2.5 "
         "oynaklık kilidi</b>. Çıkış: HYBRID_TREND (%50 kapanış&lt;EMA8 · %50 kapanış&lt;EMA21). "
         "Komut botunda <code>/kripto</code>."),
        ("3 · Web entegrasyonu", C["fosfor"],
         "Backtest Lab'a <b>🪙 Kripto Top-75</b> evren preseti (otomatik Binance modu) · kağıt-trade "
         "dashboard'a 4. defter (Binance canlı fiyat, 7/24 mum grafikleri 15m–4h, kuruş-altı "
         "fiyatlarda 6 anlamlı hane)."),
    ]
    phase_html = "".join(
        f'<div class="ph" style="border-left-color:{c}"><h3>{t}</h3><p>{b}</p></div>'
        for t, c, b in phases)

    page = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🪙 Kripto Adaptasyonu — Genel Bakış</title>
<style>
 :root{{color-scheme:dark}}
 body{{margin:0;background:{C['gece']};color:{C['ink']};
  font:14px/1.55 system-ui,"Segoe UI",Roboto,sans-serif;font-variant-numeric:tabular-nums}}
 .muted{{color:{C['sis']}}} .pos{{color:{C['kar']}}} .neg{{color:{C['zarar']}}}
 code{{background:{C['defter2']};border:1px solid {C['cizgi']};border-radius:4px;padding:1px 5px;font-size:12.5px}}
 header{{padding:26px 28px 20px;border-bottom:1px solid {C['cizgi']}}}
 h1{{font-size:21px;font-weight:650;letter-spacing:-.01em;margin:0}}
 h1 .alt{{color:{C['sis']};font-weight:500;font-size:13px;margin-left:10px}}
 .wrap{{max-width:1080px;margin:0 auto;padding:26px 28px 70px}}
 section{{background:{C['defter']};border:1px solid {C['cizgi']};border-left:3px solid {C['btc']};
  border-radius:10px;padding:20px 22px;margin:0 0 26px}}
 section h2{{font-size:14px;font-weight:650;margin:0 0 4px}}
 section .kural{{display:block;font-size:12px;color:{C['sis']};margin:0 0 16px}}
 .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:12px;margin:22px 0 26px}}
 .kpi{{background:{C['defter']};border:1px solid {C['cizgi']};border-top:2px solid {C['btc']};
  border-radius:10px;padding:14px 16px}}
 .kpi .v{{font-size:20px;font-weight:650;letter-spacing:-.01em}}
 .kpi .l{{font-size:10.5px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:{C['gumus']};margin-top:4px}}
 .kpi .s{{font-size:11.5px;margin-top:3px}}
 .ph{{border-left:3px solid {C['sis']};padding:2px 0 2px 14px;margin:0 0 14px}}
 .ph h3{{font-size:12.5px;font-weight:650;margin:0 0 4px}}
 .ph p{{margin:0;font-size:13px;color:{C['gumus']}}}
 table{{width:100%;border-collapse:collapse;font-size:13px}}
 th,td{{padding:7px 10px;text-align:right;border-bottom:1px solid {C['cizgi']};white-space:nowrap}}
 th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
 th{{color:{C['sis']};font-weight:600;font-size:10.5px;letter-spacing:.07em;text-transform:uppercase}}
 tr.sep td{{border-top:1px solid {C['cizgi2']}}}
 tr.champ td{{background:rgba(232,176,75,.07);border-top:1px solid rgba(232,176,75,.3);
  border-bottom:1px solid rgba(232,176,75,.3)}}
 table.hm td,table.hm th{{padding:4px 7px;font-size:12px}}
 table.hm td:first-child{{color:{C['gumus']}}}
 .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;vertical-align:baseline}}
 .legend{{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;color:{C['gumus']};margin:4px 0 10px}}
 .legend span{{display:inline-flex;align-items:center}}
 svg{{width:100%;height:auto;display:block}}
 .uyar{{background:rgba(232,176,75,.08);border:1px solid rgba(232,176,75,.25);border-radius:8px;
  padding:12px 16px;font-size:12.5px;color:{C['gumus']}}}
 pre{{background:{C['gece']};border:1px solid {C['cizgi']};border-radius:8px;padding:12px 14px;
  font-size:12px;overflow-x:auto;color:{C['gumus']}}}
 footer{{color:{C['sis']};font-size:11.5px;margin-top:8px}}
</style></head><body>
<header><h1>🪙 Kripto Adaptasyonu<span class="alt">swing-backtest-lab · aynı motor, Binance USDT spot evreni · {date.today().isoformat()} · dal: crypto-port</span></h1></header>
<div class="wrap">

<div class="kpis">{kpi_html}</div>

<section><h2>Ne yapıldı</h2>
<span class="kural">Hisse motoru çatallanmadı — genişletildi. Varsayılan konfigde hisse davranışı bit-özdeş kaldı.</span>
{phase_html}</section>

<section><h2>15 hücre: qswing kırılım girişi × 3 çıkış × 5 pencere</h2>
<span class="kural">Evren: top-75 USDT (BTC kıyas) · günlük UTC bar · komisyon 10bps/bacak + slippage · oynaklık filtresi KAPALI (saf karşılaştırma) · ★ = penceredeki en iyi alpha</span>
<div class="legend"><span><span class="dot" style="background:{EXIT_COLOR['atr']}"></span>ATR-trail (2.5×)</span>
<span><span class="dot" style="background:{EXIT_COLOR['hybrid']}"></span>8/21-EMA hibrit</span>
<span><span class="dot" style="background:{EXIT_COLOR['split']}"></span>½hibrit+½ATR</span>
<span><span class="dot" style="background:{C['btc']}"></span>BTC al-tut (kıyas)</span></div>
{chart_roi_vs_btc(crypto)}
{table_15(crypto)}
<p class="muted" style="font-size:12.5px;margin-bottom:0">Okuma: <b>ayı pencerelerinde</b> (1y: BTC −39.8% · 2y: −6.8%) strateji
büyük alpha üretiyor — rejim kapısı + seçici giriş. <b>Boğa süper-döngüsünde</b> (3y: BTC +145%) al-tut'u geçemiyor (hisselerde
SPY'a karşı bilinen davranışın aynısı). <b>6 ayda 0 işlem</b> hata değil: BTC&lt;SMA200 → sistem nakitte bekledi ve +29.5 pt kazandı.</p>
</section>

<section><h2>BTC oynaklık kilidi — bu çalışmanın ana bulgusu</h2>
<span class="kural">2y penceresi · BTC 20g ATR% eşiği aşılırsa yeni alım yok (v7 ATR-Rejim kilidinin kripto kalibrasyonu) · hisse varsayılanı 1.5 kriptoda hep kilitli kalırdı — ölçtük: tatlı nokta 2.5</span>
<div class="legend"><span><span class="dot" style="background:{C['kar']}"></span>ROI</span>
<span><span class="dot" style="background:{C['zarar']}"></span>MaxDD</span>
<span>★ = canlı kağıt-trade konfigi (hibrit · eşik 2.5)</span></div>
{chart_regime(grid)}
{table_regime(grid)}
<p class="muted" style="font-size:12.5px;margin-bottom:0">Eşik 2.5'te hibrit: DD {_f(g_off['max_dd_pct'])}% → {_f(g_on['max_dd_pct'])}%
(yarıdan az), ROI {_f(g_off['roi_pct'])}% → {_f(g_on['roi_pct'])}%, PF 1.66 → 4.67. Eşik 2.0 daha yüksek ROI gösteriyor ama
12 işlemlik örneklem güvenilir değil (PF 32 = küçük-örneklem yanılsaması) — canlı konfig için <b>2.5</b> seçildi.</p>
</section>

{('''<section><h2>Kısa (short) taraf — ayna strateji, yalnız ayı rejiminde</h2>
<span class="kural">Giriş: 40g DİP kırılımı + 52H dibe yakın + BTC'den zayıf momentum, YALNIZ BTC&lt;SMA200 iken ·
kapatma kapanış-teyitli · maliyet: 10bps/bacak + slippage + 3bps/GÜN funding (perp varsayımı, muhafazakâr) ·
★ = anlamlı örneklemli kazanan konfig</span>
''' + table_short(short) + '''
<p class="muted" style="font-size:12.5px;margin-bottom:0">Üç dürüst bulgu: (1) <b>Kısa taraf yalnız taze ayıda kazanıyor</b>
(1y: +37.3% · 6mo: +32.1%, hibrit kapatma) — 5y/3y gibi karışık rejimlerde HER konfig zararda; kripto kısalamak
süper-döngüde intihar. (2) <b>Oynaklık kilidi kısa tarafı aç bırakıyor</b>: çöküşler = yüksek-ATR günleri; kilit 2.5
2 yılda 1-2 işleme düşürüyor (%100 Win satırları örneklem yanılsaması, "n!"). Uzunları koruyan filtre kısaların fırsat
kümesini siliyor → kısa konfig kilitSİZ. (3) <b>Hibrit kapatma &gt; ATR-cover</b>: sert ayı ralli'leri şamdan seviyesini
deler; EMA üstü kapanış teyidi daha erken çıkarıyor. Uzun ve kısa defterler rejim gereği <b>doğal olarak ayrık</b>
(uzun: BTC&gt;SMA200 · kısa: BTC&lt;SMA200) — birleşik portföy sonuçları bir sonraki bölümde.</p>
</section>

''') if short else ''}{('''<section><h2>⚖️ Birleşik uzun/kısa portföy — tek nakit havuzu, rejim anahtarı</h2>
<span class="kural">Uzun defter = motorun KENDİSİ (şampiyon: kırılım + kilit 2.5 + HYBRID_TREND) · kısa defter = ayna,
kilitsiz, 3bps/gün funding · girişler rejime göre ayrık (uzun: BTC&gt;SMA200 · kısa: BTC&lt;SMA200), pozisyonlar geçişte
taşınır, havuz kaldıraçsız sınırlar · eşdeğerlik kanıtlı: kısa-kapalı birleşik koşu = saf motor ledger'ı birebir ·
★ = önerilen varsayılan (kısa ½ boy)</span>
<div class="legend"><span><span class="dot" style="background:''' + C["altin"] + '''"></span>uzun-tek</span>
<span><span class="dot" style="background:''' + C["buz"] + '''"></span>birleşik</span>
<span><span class="dot" style="background:''' + C["fosfor"] + '''"></span>birleşik (kısa ½)</span>
<span><span class="dot" style="background:''' + C["btc"] + '''"></span>BTC al-tut</span></div>
''' + chart_combined(combined) + table_combined(combined) + '''
<p class="muted" style="font-size:12.5px;margin-bottom:0">Okuma: <b>1y penceresi tezin kanıtı</b> — aynı sermaye boğa
yarısında uzun (+56.5k$), ayı yarısında kısa (+60.8k$) çalışıp <b>+%117.3</b>'e bileşikleniyor (BTC −%39.8; iki tek
defterin toplamından fazla, çünkü kısa defter uzunun büyüttüğü sermayeyle işlem görüyor). <b>Kısa ½ boy her karışık
pencerede tam boyu hem getiride hem DD'de geçiyor</b> (5y: DD −%58→−%40 ve ROI ↑ · 2y: DD −%36→−%23 ve ROI ↑) — tam boy
kısa defter geçişlerde uzun defterin sermayesini de kilitliyordu. Saf taze ayıda (1y/6mo) tam boy daha çok kazanıyor ama
½ boyun PF'i orada bile daha yüksek (3.35 vs 2.98). Önerilen varsayılan: <b>birleşik, kısa ½ boy</b>; agresif varyant tam boy.
Not: kilitli uzun defter 5y/3y/2y pencerelerinde aynı 32 işlemi yapıyor — kilit+rejim koşulları yalnız son ~2 yılda
sakin gün bıraktı.</p>
</section>

''') if combined else ''}{monthly_html}{h1_html}<section><h2>Kripto vs hisse — aynı 15 hücre, alpha karşılaştırması</h2>
<span class="kural">Dikkat: pencereler farklı piyasa karakterinde (kripto 1y/2y = ayı · hisse 1y/2y = boğa) — birebir kıyas değil, davranış kıyası</span>
{table_vs_equity(crypto, sp500)}
<p class="muted" style="font-size:12.5px;margin-bottom:0">Davranış tutarlı: strateji her iki varlık sınıfında da <b>düşen/yatay
piyasada alpha</b> üretiyor, güçlü boğada al-tut'un gerisinde kalıyor. Kriptoda hibrit çıkış öne çıkarken hissede ATR-trail
daha iyi — kripto trendleri daha keskin kırıldığı için kapanış-teyitli EMA çıkışı avantajlı.</p>
</section>

<section><h2>Canlı kağıt-trade konfigi (cron'da)</h2>
<span class="kural">crypto_paper_telegram.py · her gün 00:15 UTC (TR 03:15) · durum ~/.swing_paper_crypto.json · 10.000$ başlangıç</span>
<table>
<tr><th>Bileşen</th><th style="text-align:left">Kural</th></tr>
<tr><td>Giriş</td><td style="text-align:left">qswing 40g tepe kırılımı + 52H yakınlık + BTC'yi geçen 60g momentum</td></tr>
<tr><td>Rejim kapısı</td><td style="text-align:left">BTCUSDT &gt; SMA200 değilse yeni alım yok</td></tr>
<tr><td>Oynaklık kilidi</td><td style="text-align:left">BTC ATR20% &gt; 2.5 ise yeni alım yok (kırılımlar İZLE'ye düşer)</td></tr>
<tr><td>Çıkış</td><td style="text-align:left">HYBRID_TREND: %50 kapanış&lt;EMA8 · %50 kapanış&lt;EMA21 — sabit hedef yok</td></tr>
<tr><td>Boyut</td><td style="text-align:left">eşit-ağırlık (nakit / o günkü yeni sinyal sayısı) · pyramiding yok</td></tr>
<tr><td>Maliyet modeli</td><td style="text-align:left">giriş +3bps · çıkış −10bps slippage (kağıtta) · backtestte +10bps/bacak komisyon</td></tr>
</table></section>

<div class="uyar">⚠️ <b>Dürüstlük notları:</b> (1) Evren bugünün top-75'i — delist olmuş coinler yok (<b>sağ-kalan
yanlılığı</b>); mutlak ROI iyimser tavandır, birincil metrik BTC al-tuta karşı <b>alpha</b>'dır. En uzun pencere (5y) en çok
yanlılık taşır. (2) 2y penceresinde sakin+rejim-açık gün sayısı 106/1515 — kilit kasıtlı olarak çok seçici. (3) Tüm sonuçlar
komisyon+slippage sonrası; eğitim amaçlıdır, yatırım tavsiyesi değildir.</div>

<section style="margin-top:26px"><h2>Yeniden üretmek için</h2>
<pre>python3 crypto_data.py refresh-universe --top 75      # evreni tazele (crypto_universe_pinned.json)
python3 backtests/run_crypto_backtests.py             # 15 hücre → crypto_qswing_*.csv + SUMMARY
python3 backtests/run_crypto_backtests.py --regime-grid   # kilit eşiği ızgarası → crypto_regime_grid.csv
python3 backtests/run_crypto_short_backtests.py       # kısa taraf → crypto_short_SUMMARY.csv
python3 backtests/run_crypto_combined_backtests.py    # birleşik U/K → crypto_combined_SUMMARY.csv
python3 gen_crypto_report.py                          # bu rapor → dashboard_static/crypto_report.html</pre>
<footer>Kaynak CSV'ler: backtests/crypto_qswing_3exit_5period_SUMMARY.csv · crypto_regime_grid.csv ·
crypto_short_SUMMARY.csv · crypto_combined_SUMMARY.csv · sp500_qswing_3exit_5period_SUMMARY.csv —
dashboard'da <b>/kripto-rapor</b> yolundan servis edilir. Sistemin NASIL çalıştığı (huniler, rejim
anahtarı, mimari, işletme): <a href="/kripto-rehber" style="color:{C['buz']}">📖 Kripto Sistem Rehberi</a>.</footer>
</section>
</div></body></html>"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Rapor yazıldı: {OUT} ({len(page)//1024} KB)")


if __name__ == "__main__":
    build()

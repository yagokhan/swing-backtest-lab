"""Qullamaggie yöntemi (Qulla-21: yarı +2R / kalan 21-EMA runner) · son 6 ay trade raporu (HTML).
RS top-50 sistematik evren · qswing-63 giriş · 20-slot/%5/$20k. Çıktı: reports/qulla_son6ay.html"""
import html
import pandas as pd
import wf_validate as wf
import swing2_backtest as sb

START = "2025-12-21"          # son ~6 ay (bugün 2026-06-21)
POOL = sb.UNIVERSE_PRESETS["sp500_ndx"]

def qulla21():
    c = wf.champion_cfg(POOL, use_rs=True)
    c.exit_mode = "split"
    c.split_a = "target"; c.split_a_param = 2.0
    c.split_b = "ema21";  c.split_b_param = 0.0
    c.split_ratio = 0.5
    return c

# market BİR kez (tam span warmup), sonra son 6 ay penceresi
base = qulla21(); base.start_date = "2021-06-18"; base.end_date = ""
market = sb.load_market(base)

cfg = qulla21(); cfg.start_date = START; cfg.end_date = ""
bt = sb.Swing2Backtester(cfg, market=market)
bt.run()
m = bt.metrics()

closed = sorted(bt.trades, key=lambda t: t.exit_date)
last_date = m["equity"].index[-1]

# açık pozisyonlar (gerçekleşmemiş)
open_rows = []
for sym, pos in bt.positions.items():
    s = bt.data[sym]["Close"]
    cur = s.loc[:last_date].dropna().iloc[-1]
    upct = (cur / pos.entry - 1) * 100
    open_rows.append((sym, pos.entry_date, pos.entry, cur, pos.shares, upct,
                      sb.SECTOR_MAP.get(sym, "—")))
open_rows.sort(key=lambda r: -r[5])

wins = [t for t in closed if t.pnl > 0]
losses = [t for t in closed if t.pnl <= 0]
total_pnl = sum(t.pnl for t in closed)
avg_win = (sum(t.pnl_pct for t in wins) / len(wins)) if wins else 0
avg_loss = (sum(t.pnl_pct for t in losses) / len(losses)) if losses else 0
best = max(closed, key=lambda t: t.pnl_pct) if closed else None
worst = min(closed, key=lambda t: t.pnl_pct) if closed else None

def fpct(x): return f"{x:+.1f}%"
def cls(x): return "pos" if x > 0 else ("neg" if x < 0 else "")

rows_html = "".join(
    f"<tr><td>{html.escape(t.symbol)}</td><td>{t.entry_date.date()}</td>"
    f"<td>{t.exit_date.date()}</td><td>${t.entry:.2f}</td><td>${t.exit:.2f}</td>"
    f"<td class='{cls(t.pnl)}'>${t.pnl:+,.0f}</td>"
    f"<td class='{cls(t.pnl_pct)}'>{fpct(t.pnl_pct)}</td>"
    f"<td>{html.escape(str(t.outcome))}</td><td>{html.escape(t.sector)}</td></tr>"
    for t in closed)

open_html = "".join(
    f"<tr><td>{html.escape(s)}</td><td>{ed.date()}</td><td>${e:.2f}</td>"
    f"<td>${c:.2f}</td><td>{sh:.1f}</td>"
    f"<td class='{cls(u)}'>{fpct(u)}</td><td>{html.escape(sec)}</td></tr>"
    for s, ed, e, c, sh, u, sec in open_rows) or \
    "<tr><td colspan='7' style='text-align:center;color:#888'>açık pozisyon yok</td></tr>"

pf = m["profit_factor"]
pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"

doc = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qullamaggie Yöntemi · Son 6 Ay Trade Raporu</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;background:#0f1115;color:#e6e8eb}}
 .wrap{{max-width:1080px;margin:0 auto;padding:24px}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#9aa0a6;font-size:13px;margin-bottom:20px}}
 .cards{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px}}
 .card{{background:#1a1d24;border:1px solid #262a33;border-radius:10px;padding:14px 18px;min-width:130px;flex:1}}
 .card .k{{color:#9aa0a6;font-size:12px}} .card .v{{font-size:20px;font-weight:600;margin-top:4px}}
 table{{width:100%;border-collapse:collapse;margin-bottom:28px;font-size:13px}}
 th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #21252d}}
 th{{color:#9aa0a6;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}}
 tr:hover td{{background:#161922}}
 .pos{{color:#3fb950}} .neg{{color:#f85149}}
 h2{{font-size:16px;margin:24px 0 10px}}
 .note{{background:#1a1d24;border-left:3px solid #d29922;padding:12px 16px;border-radius:6px;color:#c9d1d9;font-size:13px;line-height:1.55}}
 .foot{{color:#6e7681;font-size:12px;margin-top:24px}}
</style></head><body><div class="wrap">
<h1>👑 Qullamaggie Yöntemi — Son 6 Ay Trade Raporu</h1>
<div class="sub">Çıkış: yarı pozisyon +2R'de banka · kalan yarı 21-EMA runner (kapanış teyidi) ·
giriş: qswing-63 kırılım · evren: sistematik RS top-50 (S&P500+Nasdaq100) ·
20-slot / %5 / $20k · dönem: {START} → {last_date.date()}</div>

<div class="cards">
 <div class="card"><div class="k">Getiri (gerçekleşen)</div><div class="v {cls(m['roi'])}">{fpct(m['roi'])}</div></div>
 <div class="card"><div class="k">SPY (aynı dönem)</div><div class="v {cls(m['spy_roi'])}">{fpct(m['spy_roi'])}</div></div>
 <div class="card"><div class="k">Alpha</div><div class="v {cls(m['alpha'])}">{m['alpha']:+.1f}</div></div>
 <div class="card"><div class="k">Kazanma oranı</div><div class="v">{m['win_rate']:.0f}%</div></div>
 <div class="card"><div class="k">Profit Factor</div><div class="v">{pf_str}</div></div>
 <div class="card"><div class="k">Max düşüş</div><div class="v neg">{m['max_dd']:.1f}%</div></div>
 <div class="card"><div class="k">Kapanan işlem</div><div class="v">{len(closed)}</div></div>
 <div class="card"><div class="k">Açık pozisyon</div><div class="v">{len(open_rows)}</div></div>
</div>

<h2>Kapanan işlemler ({len(closed)})</h2>
<table><thead><tr><th>Hisse</th><th>Giriş T.</th><th>Çıkış T.</th><th>Giriş</th><th>Çıkış</th>
<th>P&L $</th><th>P&L %</th><th>Sebep</th><th>Sektör</th></tr></thead>
<tbody>{rows_html or "<tr><td colspan='9' style='text-align:center;color:#888'>kapanan işlem yok</td></tr>"}</tbody></table>

<h2>Açık pozisyonlar ({len(open_rows)})</h2>
<table><thead><tr><th>Hisse</th><th>Giriş T.</th><th>Giriş</th><th>Güncel</th><th>Adet</th>
<th>Gerçekleşmemiş %</th><th>Sektör</th></tr></thead><tbody>{open_html}</tbody></table>

<div class="note"><b>Özet:</b> {len(wins)} kazanan / {len(losses)} kaybeden ·
ort. kazanan {avg_win:+.1f}% · ort. kaybeden {avg_loss:+.1f}% ·
toplam gerçekleşen P&L ${total_pnl:+,.0f}
{("· en iyi " + html.escape(best.symbol) + " " + fpct(best.pnl_pct)) if best else ""}
{("· en kötü " + html.escape(worst.symbol) + " " + fpct(worst.pnl_pct)) if worst else ""}.
<br><br><b>Uyarı (dürüstlük):</b> Evren havuzu <i>bugünkü</i> S&P500+Nasdaq100 üyeliği
(point-in-time değil) → kalıntı survivorship bias var; sonuçlar bir miktar iyimser.
Bu bir kâğıt-trade backtest'idir, gerçek emir/komisyon kayması yaklaşıktır.</div>

<div class="foot">Üretim: swing-backtest-lab · rs-universe-debias · Qulla-21 split exit · {last_date.date()}</div>
</div></body></html>"""

import os
os.makedirs("reports", exist_ok=True)
out = "reports/qulla_son6ay.html"
with open(out, "w") as f:
    f.write(doc)

print(f"Yazildi: {out}")
print(f"Donem: {START} -> {last_date.date()}")
print(f"Kapanan islem: {len(closed)} | Acik: {len(open_rows)}")
print(f"Getiri {m['roi']:+.1f}% | SPY {m['spy_roi']:+.1f}% | alpha {m['alpha']:+.1f} | "
      f"win {m['win_rate']:.0f}% | PF {pf_str} | DD {m['max_dd']:.1f}%")

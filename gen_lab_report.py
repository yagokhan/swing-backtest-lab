#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 Deney Laboratuvarı sayfası üreticisi → dashboard_static/exp_lab.html (:8061 /lab)

2026-07-01 deney günlüğü: canlı Qulla-21 COMBO'ya DOKUNMADAN denenen iyileştirme
alternatifleri. Batarya/walk-forward tabloları o günkü koşuların gömülü snapshot'ı
(scratch: lab_battery.py, lab_iter2.py — monkeypatch, motor değişmedi); grafik ve
KPI'lar bu script her çalıştığında baz + aday yeniden koşularak tazelenir.
Çalıştır: python3 gen_lab_report.py  (~2 dk, disk cache ile)"""
import swing2_backtest as s
import pandas as pd, copy, json, os, datetime

# ---- canlı combo zemini (rapordakiyle birebir) ----
cfg = s.Config()
cfg.period = "5y"; cfg.price_source = "fmp"; cfg.disk_cache = True
cfg.use_earnings = False; cfg.per_ticker_download = False
cfg.entry_mode = "qswing_breakout"; cfg.qswing_breakout_lb = 63
cfg.exit_mode = "split"; cfg.split_a = "target"; cfg.split_a_param = 2.0
cfg.split_b = "ema21"; cfg.split_b_param = 0.0; cfg.split_ratio = 0.5
cfg.use_rs_universe = True; cfg.rs_n = 50
cfg.rs_pool = s.UNIVERSE_PRESETS["sp500_ndx"]; cfg.universe = cfg.rs_pool
cfg.max_positions = 20; cfg.compounding = True; cfg.liquidate_at_end = True
cfg.max_position_pct = 0.075; cfg.free_runner_slots = True

print("Veri yükleniyor (cache)...", flush=True)
market = s.load_market(cfg)
NPOOL = len(market["data"])

def run(ov, sd="2021-05-01", ed=""):
    c = copy.deepcopy(cfg)
    for k, v in ov.items(): setattr(c, k, v)
    c.start_date = sd; c.end_date = ed
    bt = s.Swing2Backtester(c, market=market); bt.run()
    return bt.metrics()

print("Grafik için baz + aday koşuluyor...", flush=True)
mB = run({})                       # canlı combo (A payı 0.50)
mC = run({"split_ratio": 0.6})     # aday (A payı 0.60)

# güncel-veri sağlaması: 3 pencerede baz vs aday (her regen'de yeniden hesaplanır)
print("Güncel-veri sağlaması (2y/1y)...", flush=True)
FRESH = []
for _wn, _sd in (("5 yıl", "2021-05-01"), ("Son 2 yıl", "2024-07-01"), ("Son 1 yıl", "2025-07-01")):
    if _wn == "5 yıl":
        _b, _c = mB, mC
    else:
        _b, _c = run({}, sd=_sd), run({"split_ratio": 0.6}, sd=_sd)
    FRESH.append((_wn, _b, _c))

def series(eq, base=100.0):
    n = eq / eq.iloc[0] * base
    return [{"time": d.strftime("%Y-%m-%d"), "value": round(float(v), 2)} for d, v in n.items()]

def dd_series(eq):
    dd = (eq / eq.cummax() - 1) * 100
    return [{"time": d.strftime("%Y-%m-%d"), "value": round(float(v), 2)} for d, v in dd.items()]

spy_eq = market["spy"]["Close"].reindex(mB["equity"].index).ffill()
data = {"eq_b": series(mB["equity"]), "eq_c": series(mC["equity"]),
        "spy": series(spy_eq), "dd_b": dd_series(mB["equity"]), "dd_c": dd_series(mC["equity"])}

# =====================================================================
# 2026-07-01 DENEY SNAPSHOT'I (scratch koşularından; ayrıntı docstring'de)
# =====================================================================
BATTERY = {
 "runner": [
  ("Mevcut: 21-EMA (baz)", (63.8,-17.9,2.25), (70.0,-14.4,3.13), (33.9,-8.8,2.49)),
  ("8-EMA (daha hızlı)",   (39.0,-19.4,2.12), (51.2,-17.4,2.74), (47.2,-8.9,3.07)),
  ("50-MA (daha yavaş)",   (107.1,-18.2,2.65),(61.2,-20.9,2.49), (43.0,-13.6,2.58)),
  ("ATR-iz 2.5×",          (76.4,-16.9,2.52), (38.4,-15.7,2.23), (45.7,-10.6,3.01)),
  ("ATR-iz 3.25×",         (53.3,-20.3,2.06), (54.7,-17.2,2.36), (54.4,-13.8,3.33)),
 ],
 "ratio": [
  ("%30 hedef / %70 runner", (54.8,-12.7,2.07), (54.9,-11.4,2.61), (37.2,-8.3,2.51)),
  ("%40 / %60",              (49.3,-17.3,2.18), (52.1,-14.1,2.40), (43.2,-9.4,2.82)),
  ("Mevcut: %50 / %50 (baz)",(63.8,-17.9,2.25), (70.0,-14.4,3.13), (33.9,-8.8,2.49)),
  ("⭐ %60 / %40",           (99.2,-17.5,3.08), (73.7,-15.7,3.89), (50.2,-9.3,3.43)),
  ("%70 / %30",              (105.1,-21.0,3.28),(69.9,-18.5,3.45), (34.6,-10.6,2.44)),
 ],
 "cooldown": [
  ("Mevcut: engel yok (baz)",(63.8,-17.9,2.25), (70.0,-14.4,3.13), (33.9,-8.8,2.49)),
  ("Aynı gün tekrar yasak",  (68.7,-19.7,2.39), (34.8,-15.6,2.24), (45.9,-9.5,3.22)),
  ("3 gün bekle",            (68.8,-19.7,2.40), (34.8,-15.6,2.24), (45.9,-9.5,3.22)),
  ("5 gün bekle",            (70.9,-19.7,2.46), (35.0,-15.6,2.22), (45.9,-9.5,3.22)),
  ("10 gün bekle",           (82.5,-20.3,2.77), (60.8,-15.0,3.13), (43.3,-10.0,2.89)),
 ],
 "score": [
  ("Mevcut: kapı yok (baz)", (63.8,-17.9,2.25), (70.0,-14.4,3.13), (33.9,-8.8,2.49)),
  ("Skor ≥ 60",              (58.3,-17.2,2.13), (57.5,-16.4,2.98), (57.8,-10.9,3.09)),
  ("Skor ≥ 70",              (75.7,-16.3,2.41), (47.5,-14.2,2.82), (39.2,-10.6,2.30)),
  ("Skor ≥ 80",              (41.0,-9.1,2.29),  (26.5,-8.9,2.34),  (15.6,-8.9,1.95)),
 ],
 "rs_n": [
  ("Mevcut: RS top-50 (baz)",(63.8,-17.9,2.25), (70.0,-14.4,3.13), (33.9,-8.8,2.49)),
  ("RS top-30 (dar)",        (128.5,-20.7,3.36),(55.2,-17.9,3.02), (56.5,-9.3,3.33)),
  ("RS top-75 (geniş)",      (81.2,-16.6,2.61), (40.6,-14.9,2.21), (37.8,-10.1,2.45)),
 ],
}
# walk-forward (5 pencere): isim → [(roi,dd,pf)×5]  sıra: 5y tam · ayı 21-23 · topar 23-25 · son 2y · son 1y
WF_COLS = ["5 yıl tam", "Ayı 2021-23", "Toparlanma 2023-25", "Son 2 yıl", "Son 1 yıl"]
WF = [
 ("Mevcut canlı (baz)", [(63.8,-17.9,2.25),(3.7,-17.6,1.14),(18.6,-17.0,1.71),(70.0,-14.4,3.13),(33.9,-8.8,2.49)]),
 ("A payı %55",         [(76.5,-18.6,2.89),(0.3,-18.6,1.01),(35.9,-16.3,2.27),(72.0,-16.6,3.18),(45.1,-9.4,2.90)]),
 ("⭐ A payı %60",      [(99.2,-17.5,3.08),(6.3,-15.8,1.25),(29.5,-19.3,2.00),(73.7,-15.7,3.89),(50.2,-9.3,3.43)]),
 ("A payı %65",         [(84.2,-22.9,2.94),(1.7,-22.9,1.07),(26.9,-20.9,1.91),(60.9,-16.6,2.85),(44.8,-12.0,2.98)]),
 ("%60 + 50-MA runner", [(109.5,-19.6,2.67),(7.7,-12.6,1.26),(36.8,-19.6,2.15),(58.2,-21.1,2.70),(49.7,-12.0,3.01)]),
 ("%60 + RS top-30",    [(74.7,-24.0,2.35),(-0.9,-24.0,0.96),(40.0,-16.5,2.39),(52.5,-15.5,2.86),(68.7,-10.5,4.41)]),
 ("RS top-30 tek",      [(128.5,-20.7,3.36),(1.0,-20.7,1.04),(32.2,-17.7,2.00),(55.2,-17.9,3.02),(56.5,-9.3,3.33)]),
]

def cell(roi, dd, pf, best=False):
    cls = "pos" if roi > 0 else "neg"
    star = ";outline:2px solid #58a6ff;outline-offset:-2px" if best else ""
    return (f"<td style='text-align:center{star}'><b class='{cls}'>{roi:+.1f}%</b>"
            f"<br><span class='mut'>DD {dd:.1f} · PF {pf:.2f}</span></td>")

def battery_table(rows):
    out = ["<table><tr><th>Varyant</th><th>5 yıl</th><th>Son 2 yıl</th><th>Son 1 yıl</th></tr>"]
    for name, r5, r2, r1 in rows:
        star = name.startswith("⭐")
        nm = f"<b>{name}</b>" if ("baz" in name or star) else name
        out.append(f"<tr><td>{nm}</td>{cell(*r5, best=star)}{cell(*r2, best=star)}{cell(*r1, best=star)}</tr>")
    out.append("</table>")
    return "".join(out)

def wf_table():
    out = ["<table><tr><th>Varyant</th>" + "".join(f"<th>{c}</th>" for c in WF_COLS) + "</tr>"]
    for name, cells in WF:
        star = name.startswith("⭐")
        nm = f"<b>{name}</b>" if ("baz" in name or star) else name
        out.append(f"<tr><td>{nm}</td>" + "".join(cell(*c, best=star) for c in cells) + "</tr>")
    out.append("</table>")
    return "".join(out)

today = datetime.date.today().isoformat()
pfB = f"{mB['profit_factor']:.2f}"; pfC = f"{mC['profit_factor']:.2f}"

def _pf(m):
    p = m["profit_factor"]
    return f"{p:.2f}" if p != float("inf") else "∞"

fresh_rows = []
for _wn, _b, _c in FRESH:
    ok = _c["roi"] > _b["roi"] and _c["profit_factor"] > _b["profit_factor"]
    fresh_rows.append(
        f"<tr><td><b>{_wn}</b></td>"
        f"<td style='text-align:center'>{_b['roi']:+.1f}%<br><span class='mut'>DD {_b['max_dd']:.1f} · PF {_pf(_b)}</span></td>"
        f"<td style='text-align:center'>{_c['roi']:+.1f}%<br><span class='mut'>DD {_c['max_dd']:.1f} · PF {_pf(_c)}</span></td>"
        f"<td style='text-align:center'>{'<b class=pos>✓ aday önde</b>' if ok else '<b class=neg>✗ geride</b>'}</td></tr>")
fresh_table = ("<table><tr><th>Pencere</th><th>Mevcut canlı</th><th>⭐ 60/40 aday</th><th>Sonuç</th></tr>"
               + "".join(fresh_rows) + "</table>")

html_out = f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🧪 Deney Laboratuvarı — Qulla-21</title>
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
 .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}}
 .kpi{{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px 12px}}
 .kpi .v{{font-size:20px;font-weight:700}} .kpi .l{{font-size:12px;color:var(--mut)}}
 .chart{{height:330px;border:1px solid var(--bd);border-radius:10px;margin:10px 0}}
 .leg{{font-size:12.5px;color:var(--mut);margin:2px 0 14px}} .leg b{{padding:0 4px}}
 blockquote{{border-left:3px solid var(--amb);margin:10px 0;padding:4px 14px;color:#d8c690;background:#1a1f17;border-radius:0 8px 8px 0}}
 a{{color:var(--blu)}} .back{{font-size:13px}} ul{{margin:6px 0 6px 20px;padding:0}} li{{margin:5px 0}}
</style></head><body><div class="wrap">
<p class="back"><a href="/">← Dashboard'a dön</a> &nbsp;·&nbsp; <a href="/rapor">📊 Ana rapora dön</a></p>
<h1>🧪 Deney Laboratuvarı — İyileştirme Denemeleri</h1>
<p class="mut">👑 Qulla-21 COMBO · deney günleri 2026-07-01/02 · sayfa üretimi {today} · Havuz: sp500_ndx (~{NPOOL}) → RS top-50 ·
Motor: <code>swing2_backtest.py</code> (deneyler geçici kopyada; <b>canlı sistem değiştirilmedi</b>)</p>

<div class="card">
<b>Bu sayfa nedir?</b> Ana rapordaki analizlerden sonra "daha iyisi mümkün mü?" diye
canlı sisteme <b>hiç dokunmadan</b> yapılan deneylerin günlüğü. 18 varyant × 3 zaman
penceresi tarandı; umut verenler ayrıca 5 pencerelik yürüyen-testten (ayı piyasası dahil)
geçirildi. <b>Sonuç: 1 güçlü aday bulundu (aşağıda ⭐) ve 02.07.2026'da kullanıcı onayıyla
CANLIYA ALINDI</b> — defter geçmişe dönük yeniden kuruldu (combo + 60/40 baştan itibaren tek konfig).
</div>

<h2>1) Günün kısa özeti — neyi denedik, neden?</h2>
<div class="card">
<ul>
<li><b>CNC olayı:</b> Aynı gün hem eski pozisyon +2R kârla kapandı hem yeni kırılımla tekrar girildi.
Bu "saçma mı?" sorusu iki deney doğurdu: <b>(a)</b> +2R yarısına 21-EMA güvenlik stopu koymak,
<b>(b)</b> tekrar-girişe bekleme süresi koymak. <b>İkisi de zarar etti</b> (aşağıda) → mevcut davranış doğru.</li>
<li><b>Ana rapordan bilinen:</b> Tüm kârın kaynağı +2R yarısı; 21-EMA runner yarısı uzun vadede ~başabaş
ama büyük kuyrukları yakalıyor. Bu bilgi "kârlı bacağa daha çok para ver" fikrini doğurdu → ⭐ günün kazananı.</li>
</ul>
</div>

<h2>2) Deney bataryası — 5 aile × 3 pencere</h2>
<p>Hepsi canlı COMBO zemininde (poz %7,5 + slot-serbest + RS top-50). Hücre: <b>getiri</b> / en derin düşüş (DD) / kâr faktörü (PF).
Baz = şu an canlıda çalışan ayarlar.</p>

<h3>2a) Runner (bekleyen yarı) çıkış kuralı — 21-EMA yerine ne olsa?</h3>
{battery_table(BATTERY["runner"])}
<p><b>Okuma:</b> 50-MA 5 yılda parlak (+107%) ama son 2 yılda bazdan kötü ve düşüşleri daha derin —
pencereden pencereye tutarsız. 8-EMA ve ATR-iz de tutarsız. <b class="amb">Net kazanan yok → 21-EMA kalsın.</b></p>

<h3>2b) ⭐ Para bölüşümü — +2R hedef yarısına ne kadar?</h3>
<p>Şu an pozisyon 50/50 bölünüyor: yarısı +2R hedefinde satılıyor, yarısı runner. Kâr hep +2R bacağından
geldiğine göre ona biraz daha ağırlık versek?</p>
{battery_table(BATTERY["ratio"])}
<p><b>Okuma:</b> <b>%60/%40 üç pencerede de bazı geçiyor</b> (getiri VE kâr faktörü), düşüş derinliği benzer.
%70 tek pencerede şişiyor ama düşüşü derinleşiyor; %30-40 net kötü. Komşuları da (%55, %65) bazdan iyi →
keskin bir tepe değil, geniş bir plato: <b class="pos">tesadüf değil, yapısal bir iyileşme işareti.</b></p>

<h3>2c) Tekrar-giriş beklemesi (CNC sorusu)</h3>
{battery_table(BATTERY["cooldown"])}
<p><b>Okuma:</b> Aynı-gün yasağı son 2 yıl getirisini <b class="neg">70% → 35%'e yarılıyor</b>. Güçlü hisseye
hemen tekrar binmek stratejinin önemli bir kâr kaynağı. <b class="amb">CNC'deki davranış doğru → engel koyma.</b></p>

<h3>2d) Giriş skoru kapısı — zayıf sinyalleri ele</h3>
{battery_table(BATTERY["score"])}
<p><b>Okuma:</b> Tutarlı kazanan yok. İlginç not: <b>skor ≥ 80</b> getiriyi düşürüyor ama en derin düşüşü
%-18'den <b class="pos">%-9'a yarılıyor</b> — çok savunmacı bir profil isteyen için akılda tutulabilir.</p>

<h3>2e) RS evren derinliği — top-50 yerine?</h3>
{battery_table(BATTERY["rs_n"])}
<p><b>Okuma:</b> Top-30 5 yılda +128% ile göz kamaştırıyor AMA yürüyen-testte ayı döneminde çöküyor
(aşağıda) ve düşüşleri hep daha derin — konsantrasyon kaldıracı. <b class="amb">Top-50 kalsın.</b></p>

<h2>3) Yürüyen-test (walk-forward) — adaylar 5 pencerede</h2>
<p>Tek pencerede parlamak kolay; sağlam fikir <b>her rejimde</b> (ayı dahil) ayakta kalır.</p>
{wf_table()}
<div class="card">
<b>Sonuç:</b> <b>⭐ A payı %60</b>, beş pencerenin <b>beşinde de</b> bazı hem getiride hem kâr faktöründe geçen
TEK varyant; ayı döneminde bile daha iyi (+6.3% vs +3.7%, düşüş daha sığ). Kombinasyonlar (50-MA, top-30)
en az bir pencerede çuvalladı → elendi.
</div>

<h2>4) ⭐ Günün adayı: para bölüşümünü 60/40 yap</h2>
<div class="card">
<b>Basit anlatım:</b> Bir hisseye girince parayı ikiye bölüyoruz. Bugün: yarısı "+2R kâr hedefi"nde satılıyor
(kasa), yarısı trend bitene kadar bekliyor (runner). Deney: kasa bacağına %50 yerine <b>%60</b> ver,
runner'a %40 kalsın. Kural, gösterge, zamanlama — <b>hiçbir şey değişmiyor; sadece bölüşüm oranı.</b>
</div>
<div class="kpis">
<div class="kpi"><div class="v">{mB['roi']:+.1f}%</div><div class="l">Mevcut canlı — 5 yıl getiri</div></div>
<div class="kpi"><div class="v pos">{mC['roi']:+.1f}%</div><div class="l">⭐ 60/40 aday — 5 yıl getiri</div></div>
<div class="kpi"><div class="v">{mB['max_dd']:.1f}% → {mC['max_dd']:.1f}%</div><div class="l">En derin düşüş (baz → aday)</div></div>
<div class="kpi"><div class="v">{pfB} → {pfC}</div><div class="l">Kâr faktörü (baz → aday)</div></div>
</div>
<div id="ch_eq" class="chart"></div>
<p class="leg"><b style="color:#3fb950">■</b> ⭐ 60/40 aday <b style="color:#f85149">■</b> mevcut canlı (50/50)
<b style="color:#8b949e">■</b> SPY · 100 = başlangıç · log ölçek</p>
<div id="ch_dd" class="chart"></div>
<p class="leg">Tepeden düşüş (%) — <b style="color:#3fb950">■</b> aday <b style="color:#f85149">■</b> baz</p>

<h3>Güncel-veri sağlaması ({today} verisiyle yeniden hesap)</h3>
<p>Bölüm 2-3'teki tablolar deney gününün (2026-06-30 kapanış) snapshot'ı. Aşağıdaki tablo ise bu sayfa
her üretildiğinde <b>güncel veriyle yeniden</b> hesaplanır — aday hâlâ önde mi diye kalıcı bir sağlama:</p>
{fresh_table}
<p><b>Dürüst not:</b> Veri penceresi bir gün bile kayınca işlem dizisi değişir; avantajın <b>yönü</b> korunuyor
(aday her pencerede getiri ve kâr faktöründe önde) ama <b>büyüklüğü</b> oynak — örn. 5 yıl farkı snapshot'ta
+35 puanken güncel veriyle +10 puana indi. Karar verirken farkın yönüne güven, büyüklüğüne değil.</p>

<h2>5) 🧬 Ek analiz (02.07): Büyük kazananların DNA'sı</h2>
<div class="card">
<b>Soru:</b> Çok yüksek kazanç getiren pozisyonları <b>giriş anında</b> ayırt eden ortak bir kriter var mı?
5 yıllık baz koşudaki 232 pozisyonun her biri için giriş günündeki ~22 özellik hesaplandı (oynaklık,
momentum, ortalamalardan uzama, hacim, kırılım günü gücü, öncelik skoru, sektör...) ve büyük kazananlar
(en iyi %10 = 24 pozisyon) geri kalanla karşılaştırıldı.
</div>
<ul>
<li><b>Kâr kuyrukta yaşıyor:</b> toplam kârın <b>%58'i</b> en iyi 24 pozisyondan geliyor;
<b>%24'ü</b> sadece 5 pozisyondan (DELL, MU, WDC, SMCI, MRVL — hepsi aşırı-momentumlu teknoloji/çip).</li>
<li><b class="pos">Evet, kriter var — "sıcaklık":</b> büyük kazananlar girişte <b>daha oynak</b> (ATR%),
ortalamalardan <b>daha uzamış</b>, göreli gücü (RS) daha yüksek ve kırılım günü <b>daha güçlü</b>
(büyük mum + gap'li açılış) hisseler. Bu özellikler birbirine sıkı bağlı (korelasyon 0.5–0.85) →
aslında hepsi TEK faktör: <b>sıcak momentum ismi</b>.</li>
<li><b>Şaşırtıcı taraf:</b> "sakin/az oynak" girişler EN KÖTÜ dilim — hem en düşük ortalama getiri
(+1.3%) hem en derin kayıplar (-28%'e varan; sıcak dilimin en kötüsü -18%). Yani bu sistemde asıl risk
uzamış hisseyi kovalamak değil, <b>sönük kırılıma binmek.</b></li>
<li><b>Sistemin skoru öngörmüyor:</b> giriş öncelik skoru (0-100) büyük kazananı ayırt etmiyor
(dönemin iki yarısında yön tutmadı) — bölüm 2d'deki "skor kapısı işe yaramadı" bulgusuyla tutarlı.</li>
</ul>
<table>
<tr><th>Giriş günü özelliği (dilim)</th><th>Sakin ⅓</th><th>Orta ⅓</th><th>Sıcak ⅓</th><th>İki yarıda yön</th></tr>
<tr><td>ATR% (oynaklık)</td><td>+1.3% · kârın %7'si</td><td>+4.1% · %25</td><td class="pos">+8.8% · %68</td><td class="pos">✓ aynı</td></tr>
<tr><td>SMA50 üstü uzama</td><td>+2.3% · %13</td><td>+2.9% · %17</td><td class="pos">+9.0% · %70</td><td class="pos">✓ aynı</td></tr>
<tr><td>RS (SPY'a karşı 60g)</td><td>+3.5% · %21</td><td>+2.4% · %15</td><td class="pos">+8.4% · %64</td><td class="pos">✓ aynı</td></tr>
<tr><td>Kırılım günü mum gücü</td><td>+2.6% · %16</td><td>+3.3% · %21</td><td class="pos">+8.3% · %63</td><td class="pos">✓ aynı</td></tr>
<tr><td>Öncelik skoru (mevcut sıralama)</td><td>+5.5% · %37</td><td>+2.7% · %18</td><td>+6.0% · %45</td><td class="neg">✗ tutarsız</td></tr>
</table>
<p class="mut">Hücre: dilimin ortalama pozisyon getirisi · toplam kârdaki payı. "İki yarıda yön": dönem ikiye
bölününce (bölme: 2024-02) fark her iki yarıda da aynı yönde mi? ATR% farkı ayrıca 6 yılın 6'sında da pozitif.</p>

<h3>Sömürü denemesi: ATR% giriş filtresi — aday DEĞİL, fikir havuzunda</h3>
<p>"Madem sıcaklık ayırt ediyor, sakin girişleri hiç almasak?" → ATR% eşiği 5 pencerelik yürüyen-teste sokuldu:</p>
<table>
<tr><th>Pencere</th><th>Baz (canlı)</th><th>ATR ≥ 2.5</th><th>ATR ≥ 3.0</th></tr>
<tr><td>5 yıl tam</td><td>+64.5% · PF 2.25</td><td class="pos">+124.6% · PF 2.76</td><td class="pos">+106.0% · PF 2.57</td></tr>
<tr><td>Ayı 2021-23</td><td>+3.7% · PF 1.14</td><td class="pos">+10.6% · PF 1.39 (DD -17→-11)</td><td>+3.9% · PF 1.14</td></tr>
<tr><td>Toparlanma 23-25</td><td>+18.6% · PF 1.71</td><td class="pos">+40.1% · PF 2.08</td><td class="pos">+40.3% · PF 2.21</td></tr>
<tr><td>Son 2 yıl</td><td class="pos">+65.8% · PF 2.89</td><td class="neg">+60.0% · PF 2.38</td><td class="neg">+61.9% · PF 2.48</td></tr>
<tr><td>Son 1 yıl</td><td>+32.1% · PF 2.37</td><td class="pos">+45.2% · PF 2.50</td><td class="pos">+49.0% · PF 2.75</td></tr>
</table>
<p><b>Neden aday değil?</b> 4/5 pencerede önde ama <b class="amb">eşik platosu tırtıklı</b>:
2.25→+85, 2.5→+125, 2.75→+163, 3.0→+106. Sonuç birkaç mega işlemin filtreye girip çıkmasına aşırı duyarlı —
60/40 adayının düz platosu gibi güven vermiyor. Ayrıca kriter aynı veride keşfedildi (seçim yanlılığı) ve
"iyileştirme yığma" dersinden ötürü 60/40 ile birlikte bilinçli olarak TEST EDİLMEDİ. Durumu:
<b>izlemeye değer fikir</b> — belki gelecekte, 60/40 kararı oturduktan sonra tek başına yeniden ele alınır.</p>

<h2>6) Elenenler — kısa mezarlık</h2>
<ul>
<li><b>+2R yarısına 21-EMA stopu:</b> işlem sayısı 4×, kâr faktörü 2.25→1.22. Stopsuz +2R bacağı,
CNC örneğindeki gibi geri çekilmeye dayanıp hedefe ulaşıyor — <b>stopsuzluk koruyor.</b></li>
<li><b>Tekrar-giriş yasağı:</b> son 2 yıl getirisini yarılıyor.</li>
<li><b>Runner kuralı değişimi (8-EMA / 50-MA / ATR-iz):</b> pencereler arası tutarsız.</li>
<li><b>Skor kapısı:</b> tutarlı fayda yok (savunmacı ≥80 profili hariç).</li>
<li><b>RS top-30 / top-75:</b> top-30 = kaldıraçlı konsantrasyon (ayıda çöker), top-75 sulandırıyor.</li>
<li><b>Kombinasyonlar (60/40 + 50-MA, 60/40 + top-30):</b> tek tek iyi görünen parçalar birleşince
en az bir rejimde bozuluyor → üst üste iyileştirme yığmak overfit tuzağı.</li>
</ul>

<h2>7) Dürüst uyarılar</h2>
<blockquote>
<b>1.</b> Bütün deneyler AYNI 5 yıllık veri üzerinde yapıldı; kazananı sonuçlara bakarak seçtik.
Bu her zaman bir miktar "geçmişe uydurma" riski taşır. 5 pencerede tutarlılık + geniş plato
güçlü işaretler, ama garanti değil.<br>
<b>2.</b> 60/40 <b>02.07.2026'da canlıya alındı</b> (kullanıcı onayı); kağıt defter geçmişe dönük
yeniden kuruldu. Eski 50/50 defter yedekte (<code>.bak.20260702-0954</code>) — tek satırla geri dönülebilir.<br>
<b>3.</b> Runner payı %40'a inince büyük kuyruk kazançlarının (DELL +120% gibi) portföye katkısı
biraz küçülür; 60/40'ın ekstra getirisi bunu tarihsel olarak fazlasıyla telafi etti — ama gelecekte
kuyruklara daha bağımlı bir dönem gelirse fark daralabilir.
</blockquote>

<h2>8) Durum</h2>
<div class="card">
<b>Canlı:</b> 👑 Qulla-21 COMBO (poz %7,5 + slot-serbest) + <b class="pos">⭐ 60/40 split — 02.07.2026'da
CANLIYA ALINDI</b> (<code>split_ratio 0.6</code>). Defter kullanıcı isteğiyle <b>geçmişe dönük</b> yeniden
kuruldu: START'tan (27.05) itibaren combo+60/40 tek konfig çalışmış gibi (20 pozisyon, +6.9%). ·
<b>Geri alma:</b> <code>split_ratio 0.5</code> + eski defter yedeği (<code>.bak.20260702-0954</code>) geri kopyalanır.
</div>
<p class="mut">Üretim: <code>gen_lab_report.py</code> · Deney scriptleri: scratch (lab_battery.py, lab_iter2.py, ema_guard.py, winner_dna 1-3) ·
Bu sayfa salt-okur; canlı trade mantığına etkisi yoktur.</p>
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
const eq = mkChart('ch_eq', true);
eq.addLineSeries({{color:'#3fb950',lineWidth:2}}).setData(DATA.eq_c);
eq.addLineSeries({{color:'#f85149',lineWidth:2}}).setData(DATA.eq_b);
eq.addLineSeries({{color:'#8b949e',lineWidth:1}}).setData(DATA.spy);
eq.timeScale().fitContent();
const dd = mkChart('ch_dd', false);
dd.addAreaSeries({{lineColor:'#3fb950',topColor:'rgba(63,185,80,.25)',bottomColor:'rgba(63,185,80,0)',lineWidth:2}}).setData(DATA.dd_c);
dd.addAreaSeries({{lineColor:'#f85149',topColor:'rgba(248,81,73,.25)',bottomColor:'rgba(248,81,73,0)',lineWidth:2}}).setData(DATA.dd_b);
dd.timeScale().fitContent();
</script></body></html>"""

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_static", "exp_lab.html")
with open(out, "w", encoding="utf-8") as fh:
    fh.write(html_out)
print(f"yazıldı → {out} ({len(html_out)/1024:.0f} KB)", flush=True)

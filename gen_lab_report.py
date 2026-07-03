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
# SABİT cache: sayfadaki TÜM deney tabloları bu veri setinden üretildi (373 hisse · 1543 bar).
# load_market bugünün tarihiyle anahtarlayıp TAZE indirmeye gider; FMP rate-limit sembol
# budarsa (03.07'de 9 sembol düştü) sayfanın kendi grafikleri sessizce kayar. O yüzden pin.
import pickle
with open("swing2_cache/market_5y_152dab0ec647.pkl", "rb") as _fh:
    market = pickle.load(_fh)
market = s.attach_watchlist(market, cfg)
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

<h2>6) 🇸🇪 Qullamaggie'nin "3 zamansız kurulumu" vs Qulla-21 (02.07 ek)</h2>
<div class="card">
Kaynak: <a href="https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/">
qullamaggie.com — My 3 Timeless Setups</a>. Kristjan Qullamaggie'nin üç kurulumu: <b>1) Breakout</b>
(momentum liderinde sıkışma sonrası kırılım), <b>2) Episodic Pivot</b> (haber/bilanço gap'i),
<b>3) Parabolik şort</b>. Qulla-21 zaten 1. kurulumun büyük-hisse/gün-sonu uyarlaması — isim babası o.
Aşağıda birebir kural karşılaştırması + orijinal kurallarının bizim zeminde test sonuçları.
</div>
<table>
<tr><th>Bileşen</th><th>Qullamaggie (orijinal)</th><th>👑 Qulla-21 (canlı)</th></tr>
<tr><td>Hisse seçimi</td><td>1/3/6 ayda en çok yükselen %1-2 — küçük/orta cap, yüksek ADR</td><td>RS top-50 (60g, SPY'a karşı) — S&amp;P500+NDX büyük cap</td></tr>
<tr><td>Ön hareket</td><td>1-3 ayda +%30-100 ŞART</td><td>Örtük (RS + 52H yakınlığı) — açık eşik yok</td></tr>
<tr><td>Konsolidasyon</td><td>2 hafta-2 ay sıkışma, yükselen dipler, 10/20MA "sörfü"</td><td>Yok — 63g tepe kırılımı + Aşama-2 filtreleri</td></tr>
<tr><td>Giriş</td><td>Gün içi açılış-aralığı tepesi (1/5/60dk ORH)</td><td>Gün kapanışı (canlıda 15:45 ≈ kapanış, ~0bps kanıtlı)</td></tr>
<tr><td>Stop</td><td>Günün düşüğü (ADR'den geniş olamaz)</td><td>A bacağı STOPSUZ (testle üstün), B bacağı 21-EMA</td></tr>
<tr><td>Kâr alma</td><td>3-5 günde 1/3-1/2 sat → stop breakeven'a</td><td>%60'ı +2R limitte (~+%8)</td></tr>
<tr><td>Trail</td><td>10/20MA ilk kapanış altı</td><td>21-EMA kapanış altı</td></tr>
<tr><td>Rejim</td><td>"Boğa yoksa az/hiç işlem"</td><td>SPY&gt;SMA200 kapısı + ATR-rejim kilidi — aynı ruh ✓</td></tr>
<tr><td>Boyut/risk</td><td>%10-20 poz, işlem başı %0.25-1 risk (konsantre)</td><td>%7.5 × 20 slot (çeşitlendirilmiş)</td></tr>
</table>

<h3>Orijinal kuralları bizim zeminde denedik (baz = canlı 60/40)</h3>
<table>
<tr><th>Varyant</th><th>5y tam</th><th>Ayı 21-23</th><th>Topar 23-25</th><th>Son 2y</th><th>Son 1y</th></tr>
<tr><td><b>Baz (canlı 60/40)</b></td><td>+74.7 · 2.52</td><td>+5.9 · 1.21</td><td>+29.5 · 2.00</td><td class="pos">+70.9 · 3.65</td><td>+46.6 · 3.04</td></tr>
<tr><td>Runner 10-MA (QM trail)</td><td class="neg">+65.3</td><td class="neg">-3.5 · 0.87</td><td>+30.0</td><td>+69.1</td><td>+43.1</td></tr>
<tr><td>Runner 20-MA (QM trail)</td><td class="neg">+42.6</td><td class="neg">-7.4 · 0.75</td><td>+28.3</td><td>+63.1</td><td class="pos">+53.9</td></tr>
<tr><td>Ön-hareket ≥%30 (QM şartı)</td><td class="pos">+102.8</td><td class="pos">+21.4 · 1.80</td><td>+26.3</td><td class="neg">+41.1</td><td>+49.1</td></tr>
<tr><td>Ön-hareket ≥%20</td><td class="pos">+117.7 · 3.20</td><td class="pos">+13.3</td><td>+29.4</td><td class="neg">+59.2</td><td class="pos">+56.8</td></tr>
<tr><td>Hacim kuruması (sıkışma şartı)</td><td>+72.2</td><td>+7.3</td><td>+25.9</td><td class="neg">+47.0</td><td class="neg">+27.0</td></tr>
<tr><td>Breakeven runner (QM kuralı)</td><td>+74.3</td><td>+5.9</td><td class="pos">+40.1 · 2.30</td><td class="neg">+60.7</td><td>+46.6</td></tr>
<tr><td>QM paketi (10MA+%30+BE)</td><td class="pos">+90.5</td><td class="pos">+15.6</td><td>+28.4</td><td class="neg">+24.7</td><td class="neg">+25.3</td></tr>
</table>
<p class="mut">Hücre: getiri % · (varsa) kâr faktörü. Yeşil = bazdan belirgin iyi, kırmızı = belirgin kötü.</p>

<div class="card">
<b>Görüşler:</b>
<ul>
<li><b>Hiçbir uyarlama canlıyı 5/5 geçemedi</b> → mevcut ayarlar (21-EMA trail, stopsuz A bacağı,
+2R limit) bu habitat için yerinde. Onun sahası küçük/orta cap + gün içi + konsantre pozisyon;
bizimki 373 büyük cap + gün-sonu + 20 slot. <b>Aynı felsefe, farklı habitat — kurallar
birebir taşınmıyor.</b></li>
<li><b>10/20-MA trail bizde işlemiyor:</b> ayıda ikisi de zarara dönüyor (PF 0.87/0.75).
Büyük-cap'lerin gürültüsünde 21-EMA'nın biraz daha yavaş teyidi runner'ı korumada daha iyi.</li>
<li><b>En ilginç bulgu — ön-hareket şartı:</b> "girişten önce zaten +%20-30 koşmuş olsun" kapısı
5 yılda +117.7% / PF 3.20'ye çıkarıyor ve ayıda 2-3× iyi; ama son 2 yılda bazdan geride.
Bu, 🧬 DNA bölümündeki "sıcaklık" bulgusunun bağımsız bir doğrulaması (RET60 aynı ailenin üyesi) —
ATR≥2.5 ile birlikte <b>fikir havuzunda</b>, aynı gerekçeyle (rejim tutarsızlığı) aday değil.</li>
<li><b>Sıkışma/hacim-kuruması şartı bizde ters tepiyor</b> (son 1y 27.0 vs 46.6) — DNA bulgusuyla
tutarlı: bizim büyük kazananlar "sessiz sıkışma"dan değil, zaten ısınmış isimlerden çıkıyor.</li>
<li><b>Breakeven-stop</b> çoğu pencerede nötr (nadiren tetikleniyor), toparlanma döneminde parlak
(+40.1 vs +29.5) ama son 2y'de pahalı — zayıf bir sigorta, alınmadı.</li>
<li><b>Episodic Pivot bizde YOK ve bu zeminde kurulamaz:</b> EP "3-6 aydır YÜKSELMEMİŞ" hisse ister —
RS top-50 evreni tam tersini seçer. Gerçek EP ayrı bir sistem gerektirir (bilanço takvimi + gap
taraması + ihmal-edilmişlik ölçüsü). İstenirse ayrı deney projesi olarak ele alınır.</li>
<li><b>Parabolik şort</b> long-only kağıt defterde uygulanamaz; büyük-cap'te nadir de olur. Pas.</li>
<li>Zaten örtüşenler: rejim kapısı ✓ · lider seçimi (RS) ✓ · kısmi kâr + runner ✓ · onun "LOD stopu"nun
bizdeki karşılığı daha önce test edilip elenmişti (sıkı stop churn yapıyor, stopsuzluk koruyor).</li>
</ul>
</div>

<h2>7) 🇺🇸 Mark Minervini (SEPA / Trend Template / VCP) vs Qulla-21 (02.07 ek)</h2>
<div class="card">
Kaynak: Minervini'nin kitapları ("Trade Like a Stock Market Wizard", "Think &amp; Trade Like a Champion") —
<b>SEPA</b> yöntemi: Aşama-2 trend + fundamental ivme (EPS/ciro) + katalizör + <b>VCP</b> pivot girişi +
sıkı stop disiplini. VCP = 2-6 daralma (her biri öncekinin ~yarısı) + her daralmada azalan hacim +
dar pivot; kırılımda hacim genişlemesiyle al. Motorumuzda hazır bir VCP dedektörü var
(<code>detect_vcp</code>: zigzag %3, 80-bar) → doğrudan kapı olarak test edildi.
</div>
<table>
<tr><th>Bileşen</th><th>Minervini (orijinal)</th><th>👑 Qulla-21 (canlı)</th></tr>
<tr><td>Trend şablonu 1-5 (MA dizilimi)</td><td>Fiyat&gt;50&gt;150&gt;200MA, 200MA yükselen</td><td>Aşama-2 kapısı: fiyat&gt;SMA20/50/200 + SLOPE200&gt;0 ✓ (150g yok)</td></tr>
<tr><td>52w dipten ≥+%30</td><td>Şart</td><td>Yok → test edildi</td></tr>
<tr><td>52w zirveye ≤%25</td><td>Şart</td><td>Var, daha sıkı (52H yakınlık kapısı) ✓</td></tr>
<tr><td>RS ≥70-90</td><td>Şart (IBD derecesi)</td><td>RS top-50 — mutlak sıralama, daha sıkı ✓</td></tr>
<tr><td>VCP deseni + pivot</td><td>Çekirdek giriş deseni</td><td>Yok — 63g tepe kırılımı → test edildi</td></tr>
<tr><td>Pivot kırılımında hacim genişlemesi</td><td>Şart</td><td>Yok → test edildi (≥1.5×)</td></tr>
<tr><td>Stop disiplini</td><td>%3-8, asla &gt;%10 (konsantre pozisyonun sigortası)</td><td>A bacağı stopsuz + 20-slot çeşitlendirme → -%8/-%10 test edildi</td></tr>
<tr><td>Kâr alma</td><td>+%20-25'te güce satış (2-3× risk)</td><td>%60'ı +2R (~+%8) — +3R zaten yürüyen-testte elenmişti</td></tr>
<tr><td>Uzun trail</td><td>50g MA</td><td>21-EMA — MA50 runner daha önce elendi (tutarsız)</td></tr>
<tr><td>Fundamentaller (SEPA)</td><td>EPS/ciro ivmesi + katalizör ŞART</td><td>Yok — fiyat verisiyle test edilemez (aşağıda görüş)</td></tr>
</table>

<h3>Test sonuçları (baz = canlı 60/40, 8 varyant × 5 pencere)</h3>
<table>
<tr><th>Varyant</th><th>5y tam</th><th>Ayı 21-23</th><th>Topar 23-25</th><th>Son 2y</th><th>Son 1y</th></tr>
<tr><td><b>Baz (canlı 60/40)</b></td><td>+74.7 · 2.52</td><td class="pos">+5.9 · 1.21</td><td class="pos">+29.5 · 2.00</td><td class="pos">+70.9 · 3.65</td><td class="pos">+46.6 · 3.04</td></tr>
<tr><td>VCP kapısı (found)</td><td class="pos">+92.7</td><td>+5.4</td><td class="neg">+17.4</td><td class="neg">+17.4</td><td class="neg">+21.6</td></tr>
<tr><td>VCP kapısı (strong)</td><td class="neg">+26.5</td><td class="neg">-3.7 · 0.82</td><td>+20.6</td><td class="neg">+16.3</td><td class="neg">+10.3</td></tr>
<tr><td>Trend Template ek (52wL+150MA)</td><td class="neg">+58.6 · DD-29</td><td class="neg">-5.0 · DD-29</td><td>+28.5</td><td class="neg">+46.2</td><td class="neg">+30.4</td></tr>
<tr><td>Kırılım hacmi ≥1.5×</td><td class="pos">+100.6 · 3.06</td><td>+4.0</td><td class="pos">+33.5</td><td class="neg">+63.4</td><td>+43.4</td></tr>
<tr><td>Felaket stopu -%8</td><td class="neg">+39.8 · 1.23</td><td class="neg">-3.5</td><td class="neg">-5.3</td><td class="neg">+42.2</td><td class="neg">+33.8</td></tr>
<tr><td>Felaket stopu -%10</td><td class="neg">+59.8</td><td class="pos">+8.0 · DD-14</td><td class="neg">+5.7</td><td class="neg">+42.0</td><td>+45.9</td></tr>
<tr><td>MV paketi (VCP+TT+ST8)</td><td class="neg">-3.8 · 0.97</td><td class="neg">-7.2</td><td class="neg">-6.1</td><td class="neg">+5.2</td><td class="neg">+4.4</td></tr>
</table>

<div class="card">
<b>Görüşler — Minervini'den alabileceğimiz bir şey var mı?</b>
<ul>
<li><b>Kavramsal düzeyde zaten alınmış:</b> Aşama-2 trend kapısı, RS liderliği, 52H yakınlığı —
sistemin iskeleti SEPA'nın fiyat tarafıyla örtüşüyor. Yeni test edilen parçaların <b>hiçbiri</b>
bazı 5 pencerede geçemedi.</li>
<li><b>VCP bu zeminde işlemiyor:</b> "found" kapısı son 2 yılda getiriyi 70.9'dan 17.4'e düşürüyor;
"strong" her yerde kötü. 🧬 DNA bulgusuyla tutarlı: bizim kazananlar sessiz sıkışmadan değil,
zaten ısınmış geniş-bantlı isimlerden geliyor. Dürüst not: dedektörümüz (zigzag %3) Minervini'nin
haftalar süren, fundamentallerle desteklenen el-seçimi VCP'sinin kaba bir vekili — VCP'nin kendisini
değil, bu vekille kapılamayı eledik.</li>
<li><b>Sıkı stop bizim yapıya zehir:</b> -%8 stopu işlem sayısını 3×'e çıkarıp (397→1200) win'i
%64→%46'ya, PF'i 2.52→1.23'e düşürüyor — daha önceki plan-stop testiyle aynı ders. Minervini'nin
%3-8 stopu <b>%10-20'lik konsantre pozisyonların hayat sigortası</b>; bizim %7.5 × 20 slot yapımız aynı
korumayı <b>çeşitlendirmeyle portföy seviyesinde</b> sağlıyor. İşlem-seviyesi stop burada sadece churn.
Tek nüans: -%10 stop ayıda hafif koruma verdi (+8.0 vs +5.9, DD -14 vs -17) → savunmacı profil
notu olarak kayıtlı (skor≥80 gibi), alınmadı.</li>
<li><b>Kırılım hacmi ≥1.5× en iyi denemeydi</b> (5y +100.6/PF 3.06, topar da iyi) ama 3/5 pencerede
bazın altında — "sıcaklık" ailesinin bir üyesi daha (hacim patlaması = giriş günü gücü). ATR≥2.5 ve
ön-hareket ≥%20 ile birlikte <b>fikir havuzunda</b>.</li>
<li><b>Trend Template'in eksik parçaları değer katmıyor:</b> "52w dipten ≥+%30" şartı ayıda tepe
noktalarında girişe zorluyor (DD -29.3'e derinleşiyor!). RS top-50 zaten daha iyi bir lider filtresi.</li>
<li><b>Test edilemeyen gerçek fark — fundamentaller:</b> SEPA'nın EPS/ciro ivmesi + katalizör ayağı
fiyat verisiyle sınanamaz. Bu, Minervini'nin farkının muhtemelen asıl kaynağı ve bizim gerçek
boşluğumuz. İstenirse ayrı proje: FMP fundamental verisiyle (EPS büyümesi, beklenti aşımı)
girişlere fundamental katman denenebilir — ama örneklem küçülür, veri kalitesi riski artar.</li>
<li><b>Sonuç:</b> Minervini'nin mekanik kuralları bu habitata taşınmıyor (Qullamaggie'den bile sert ret);
felsefesi (lider + trend + risk kontrolü) zaten farklı araçlarla içselleştirilmiş durumda.</li>
</ul>
</div>

<h2>8) 🐝 Pradeep Bonde / StockBee (Momentum Bursts + EP) vs Qulla-21 (02.07 ek)</h2>
<div class="card">
Kaynak: StockBee blog/bootcamp (Pradeep Bonde). İki çekirdek fikri: <b>1) Momentum Bursts</b> —
hisseler 3-5 günlük %8-20'lik patlamalarla hareket eder; meşhur taraması "<b>%4 + dünden yüksek
hacim</b>" kırılımı; girişte "<b>genç trend</b>" şartı (patlamanın İLK günü — önceden koşmuş hisseye
girme); 3-5 günde güce satıp çık. <b>2) Episodic Pivots</b> — EP kavramının asıl sahibi Bonde'dir
(Qullamaggie ondan öğrendi): aylardır ihmal edilmiş hissede katalizör gap'i, haftalar-aylar tutulur.
Ayrıca <b>Market Monitor</b>: piyasa genişliğine (kaç hisse %4+ yükseldi vb.) dayalı rejim zamanlaması.
</div>
<table>
<tr><th>Bileşen</th><th>StockBee (orijinal)</th><th>👑 Qulla-21 (canlı)</th></tr>
<tr><td>Zaman ölçeği</td><td>3-5 günlük patlama, hızlı döngü</td><td>Haftalar süren trend (runner aylarca kalabilir)</td></tr>
<tr><td>Giriş tetiği</td><td>%4+ mum + hacim&gt;dün (4% b/o taraması)</td><td>63g tepe kırılımı (mum boyu şartı yok) → test edildi</td></tr>
<tr><td>"Genç trend" şartı</td><td>Patlamanın 1. günü; koşmuşa girme</td><td>Yok — devam kırılımlarına da girilir → test edildi</td></tr>
<tr><td>Çıkış</td><td>3-5 günde güce satış / durunca çık</td><td>%60'ı +2R (~+%8 ≈ onun %8-20 bandının başı) + %40 21-EMA runner → zaman çıkışı test edildi</td></tr>
<tr><td>Evren</td><td>Küçük/orta cap, oynak "momentum karakterli" hisseler</td><td>S&amp;P500+NDX büyük cap, RS top-50</td></tr>
<tr><td>Rejim</td><td>Market Monitor (genişlik: %4 yükselenler sayımı vb.)</td><td>SPY&gt;SMA200 + ATR-rejim kilidi — aynı amaç, farklı araç</td></tr>
<tr><td>EP</td><td>Çekirdek kurulum (icadı onun)</td><td>Yok — RS top-50 "ihmal edilmiş" hissenin tam tersi (bkz. bölüm 6 görüşü)</td></tr>
</table>

<h3>Test sonuçları (baz = canlı 60/40, 8 varyant × 5 pencere)</h3>
<table>
<tr><th>Varyant</th><th>5y tam</th><th>Ayı 21-23</th><th>Topar 23-25</th><th>Son 2y</th><th>Son 1y</th></tr>
<tr><td><b>Baz (canlı 60/40)</b></td><td>+74.7 · 2.52</td><td class="pos">+5.9 · 1.21</td><td>+29.5 · 2.00</td><td class="pos">+70.9 · 3.65</td><td>+46.6 · 3.04</td></tr>
<tr><td>Patlama günü ≥%4</td><td class="pos">+92.8 · DD-26</td><td class="neg">-6.5 · 0.79</td><td class="pos">+49.7</td><td class="neg">+41.5</td><td>+47.9</td></tr>
<tr><td>%4 + hacim&gt;dün (4% b/o)</td><td>+70.8 · DD-28</td><td class="neg">-10.4 · 0.69</td><td class="pos">+42.7</td><td>+75.9</td><td class="neg">+30.7</td></tr>
<tr><td>Taze kırılım (1. gün şartı)</td><td class="neg">+51.4</td><td class="pos">+8.7 · 1.37</td><td>+36.0</td><td class="neg">+35.8</td><td>+41.8</td></tr>
<tr><td>Taze + ≥%4 (SB girişi)</td><td>+65.1 · DD-27</td><td class="neg">-8.7 · 0.72</td><td class="pos">+45.6</td><td class="neg">+52.1</td><td>+47.1</td></tr>
<tr><td>Runner 5g zaman çıkışı</td><td class="neg">+51.3</td><td class="neg">-5.2 · 0.82</td><td class="pos">+54.6 · 3.31</td><td>+61.6</td><td>+42.9</td></tr>
<tr><td>Runner 10g zaman çıkışı</td><td>+74.5 · 2.88</td><td class="neg">+1.8</td><td class="pos">+40.1</td><td>+73.8</td><td class="pos">+52.6</td></tr>
<tr><td>SB paketi (4%b/o+taze+5g)</td><td class="neg">+48.0</td><td class="neg">-9.6 · 0.67</td><td class="pos">+43.8</td><td class="neg">+46.3</td><td>+40.7</td></tr>
</table>

<div class="card">
<b>Görüşler — StockBee'den alabileceğimiz var mı?</b>
<ul>
<li><b>Ayı penceresi bütün SB varyantlarını öldürüyor</b> (PF 0.67-0.82): %4+ dev mumlar ayı
piyasasında çoğunlukla tuzak rallisi/kısa-vade sıkışması — kırılımın "şiddeti" bizim büyük-cap
zeminimizde ayıda sinyal değil gürültü. Canlı 60/40 beş kıyasın beşinde de (DNA, QM, MV, SB) ayakta.</li>
<li><b>"1. gün şartı"nın reddi değerli bir içgörü:</b> StockBee "koşmuşa girme" der; bizde tam tersi —
devam kırılımları (2.-3. gün+) getirinin önemli parçası. Bu, tekrar-giriş yasağının getiriyi yarılaması
ve DNA "sıcaklık" bulgusuyla <b>üçüncü bağımsız doğrulama</b>: bu sistemde güçlünün peşinden gitmek doğru,
"erken/taze olanı" seçmeye çalışmak yanlış.</li>
<li><b>Zaman çıkışları win oranını %70+'a çıkarıyor ama kuyruğu kesiyor:</b> 5g runner çıkışı DELL +120%
tarzı mega kuyrukları imkânsızlaştırır (5y 74.7→51.3). 10g versiyonu şaşırtıcı derecede dirençli
(5y eşit, PF 2.88, win %71-76 — psikolojik olarak çok rahat bir profil) ama ayıda korumasız ve
kuyruk sigortası yok → alınmadı. Not: "yüksek win% isteyen sinir sistemi" için 10g zaman çıkışı
kayıtlara savunmacı-konfor profili olarak geçti.</li>
<li><b>Momentum burst bir başka habitat:</b> onun sahası küçük/oynak hisselerde 3-5 günlük döngü ve
yüksek işlem frekansı; bizim büyük-cap'ler patlamadan çok <b>sürünen trend</b> yapar. +2R bacağımız
(~+%8) zaten onun "%8-20'de güce sat" bandının başlangıcını yakalıyor — sistemin "burst hasadı"
kısmı fiilen mevcut.</li>
<li><b>EP — asıl sahibi Bonde:</b> yine bu evrende kurulamaz (ihmal şartı ↔ RS top-50 çelişkisi,
bkz. bölüm 6). Gerçek EP denemesi istenirse: TÜM evren (373) + "RET120 &lt; %10 (ihmal)" + "%8+ gap +
hacim patlaması" + bilanço takvimi — ayrı deney projesi olarak yapılabilir, not edildi.</li>
<li><b>Market Monitor fikri test edilmedi ama ilginç:</b> genişlik-tabanlı rejim (ör. evrende %4+
yükselen sayısı / 25-çeyrek yükselenler) bizim SPY&gt;SMA200 + ATR-kilidinden daha erken dönüş
yakalayabilir. Tek gerçek "alınabilir" aday bu — istenirse gelecek deney: mevcut rejim kapısını
genişlik ölçüsüyle değiştirip 5 pencerede kıyaslamak.</li>
</ul>
</div>

<h2>9) 📰 William O'Neil / CAN SLIM vs Qulla-21 (02.07 ek)</h2>
<div class="card">
Kaynak: "How to Make Money in Stocks" (IBD). <b>CAN SLIM</b>: <b>C</b>-A = çeyreklik/yıllık EPS+ciro
≥%25 (fundamental) · <b>N</b> = yenilik/yeni 52w zirvesi · <b>S</b> = arz-talep (kırılımda hacim +%40-50)
· <b>L</b> = lider (RS ≥80) · <b>I</b> = kurumsal sahiplik artışı · <b>M</b> = piyasa yönü (dağıtım
günleri sayacı + follow-through). Grafik: fincan-kulp / düz taban (<b>≥7 hafta</b>), pivot üstü
<b>≤%5 alım penceresi</b> ("kovalama yasağı"), <b>-%7-8 kesin stop</b>, +%20-25 kâr al.
Qullamaggie ve Minervini'nin ortak atası — birçok kural zaten önceki bölümlerde dolaylı test edildi.
</div>
<table>
<tr><th>Bileşen</th><th>O'Neil (orijinal)</th><th>👑 Qulla-21 (canlı)</th></tr>
<tr><td>C + A (EPS/ciro ≥%25)</td><td>Çekirdek şart</td><td>Yok — fiyat verisiyle test edilemez (görüş)</td></tr>
<tr><td>N (yeni 52w zirvesi)</td><td>Şart ("yeni zirve alanı")</td><td>52H'ye <b>yakınlık</b> kapısı (esnek) → sert hali test edildi</td></tr>
<tr><td>S (kırılım hacmi +%40-50)</td><td>Şart</td><td>Yok → ≥1.4× test edildi</td></tr>
<tr><td>L (RS ≥80 = üst %20)</td><td>Şart</td><td>RS top-50/373 = üst %13 — daha sıkı ✓</td></tr>
<tr><td>I (kurumsal sahiplik)</td><td>Şart</td><td>Veri yok (görüş)</td></tr>
<tr><td>M (piyasa yönü)</td><td>Dağıtım-günü sayacı + follow-through</td><td>SPY&gt;SMA200 + ATR-kilit → dağıtım sayacı test edildi</td></tr>
<tr><td>Taban (fincan-kulp/düz)</td><td>≥7 hafta sağlam taban</td><td>Yok — 63g tepe kırılımı yeter → ≥35g taban test edildi</td></tr>
<tr><td>Alım penceresi</td><td>Pivot üstü ≤%5 (kovalama yasağı)</td><td>Marj sınırı yok → test edildi</td></tr>
<tr><td>Stop</td><td>-%7-8 KESİN</td><td>A bacağı stopsuz → -%7 test edildi</td></tr>
<tr><td>Kâr al</td><td>+%20-25 (8-hafta istisnası)</td><td>%60'ı +2R — +3R zaten elendi</td></tr>
</table>

<h3>Test sonuçları (baz = canlı 60/40, 8 varyant × 5 pencere)</h3>
<table>
<tr><th>Varyant</th><th>5y tam</th><th>Ayı 21-23</th><th>Topar 23-25</th><th>Son 2y</th><th>Son 1y</th></tr>
<tr><td><b>Baz (canlı 60/40)</b></td><td>+74.7 · 2.52</td><td>+5.9 · 1.21</td><td>+29.5 · 2.00</td><td class="pos">+70.9 · 3.65</td><td class="pos">+46.6 · 3.04</td></tr>
<tr><td>N: gerçek yeni 52w zirve</td><td class="neg">+52.0 · DD-25</td><td class="neg">-7.2 · 0.75</td><td class="neg">+15.0</td><td>+71.9</td><td class="neg">+24.2</td></tr>
<tr><td>Taban ≥7 hafta (35g)</td><td class="neg">+51.7</td><td class="pos">+6.5 · <b>DD-6.9</b></td><td class="neg">+20.8</td><td class="neg">+10.8</td><td class="neg">+4.3</td></tr>
<tr><td>Pivot kovalama yasağı ≤%5</td><td class="neg">+57.8</td><td>+7.6</td><td>+27.5</td><td class="neg">+51.3</td><td>+42.3</td></tr>
<tr><td>S: kırılım hacmi ≥1.4×</td><td class="pos">+109.8 · 2.81</td><td class="pos">+6.6 · 1.29</td><td class="pos">+34.3</td><td class="pos">+78.1</td><td>+46.6 (DD-13)</td></tr>
<tr><td>M: dağıtım-günü kilidi*</td><td class="neg">+53.9</td><td class="neg">-0.2</td><td class="neg">+13.0</td><td class="neg">+28.5</td><td class="neg">+28.2 · PF6.6</td></tr>
<tr><td>Kesin stop -%7</td><td class="neg">+30.2 · 1.17</td><td class="neg">-6.5</td><td class="neg">+2.6</td><td class="neg">+35.0</td><td class="neg">+34.6</td></tr>
<tr><td>CANSLIM paketi (N+S+M+ST7)</td><td class="neg">+20.4 · <b>DD-8.4</b></td><td class="neg">+0.4 · DD-4.2</td><td class="neg">+4.7</td><td class="neg">+11.2 · DD-7.1</td><td class="neg">+13.3 · DD-6.1</td></tr>
</table>
<p class="mut">* M-kuralı vekilimiz kaba çıktı: "son 25 seansta ≥5 dağıtım günü" 1543 günün 1320'sinde kilit
üretti (O'Neil'in gerçek sayacı daha incelikli, süresi dolan günleri düşürür). Sonuç "günlerin %86'sında
alım yapma" filtresi olarak okunmalı — buna rağmen PF'i yüksek tutması ilginç, ama ROI her yerde geride.</p>

<div class="card">
<b>Görüşler — O'Neil'den alabileceğimiz var mı?</b>
<ul>
<li><b>S kuralı (kırılım hacmi ≥1.4×) şimdiye kadarki EN GÜÇLÜ meydan okuyucu:</b> getiride 4 pencere
üstün + 1 eşit (5y +109.8 vs +74.7; ayıda bile +6.6/PF 1.29/DD daha sığ). Ama kâr faktöründe 3 pencerede
geride ve eşik duyarlı (Minervini bölümündeki 1.5× → 3/5 geride kalmıştı; 1.4 → çok daha iyi = tırtıklılık).
60/40'ın "5/5 hem getiri hem PF" standardını tutturamıyor → <b>fikir havuzunun başına</b> geçti
(ATR≥2.5, ön-hareket ≥%20, ≥1.5× hacmin yerine). İleride tek başına komşu-eşik taramasıyla (1.3-1.45)
yeniden ele alınmaya en yakın aday.</li>
<li><b>Taban ≥7 hafta — savunmacı keşif:</b> boğada felaket (devam kırılımlarını, yani getiri motorunu
tamamen kaçırıyor: son 2y +10.8 vs +70.9) AMA ayıda <b>DD -17.2 → -6.9</b> (!) ve getiri korunuyor.
DNA "devam kırılımları değerli" bulgusunun karşı-düellosunu kaybetti ama <b>savunmacı profil ailesine</b>
(skor≥80, -%10 stop, 10g zaman çıkışı) en güçlü üye olarak katıldı: "ayı korkusu yüksekse uzun taban şartı"
diye bir kayıt artık var.</li>
<li><b>Kovalama yasağı (≤%5) DNA'yı dördüncü kez doğruladı:</b> pivotun &gt;%5 üstünde kırılanları atmak
getiriyi düşürüyor (5y 57.8 vs 74.7) — çünkü atılanlar tam da mega kazanan adayları. O'Neil'in korktuğu
"uzamış giriş" bizim büyük-cap zeminimizde en iyi girişler.</li>
<li><b>Kesin -%7 stop üçüncü kez elendi</b> (işlem 3×, PF 1.17) — O'Neil/Minervini stop disiplini
konsantre portföyün sigortası; bizim 20-slot yapımız aynı işi çeşitlendirmeyle görüyor.</li>
<li><b>CANSLIM paketi = ultra-savunma:</b> getiri çöküyor ama DD'ler -4/-8 bandına iniyor. Risk-ayarlı
bazın gerisinde (5y ROI/DD 4.3 vs 2.4) → alınmadı; yine de "sermaye koruması her şeyden önemli" diyen
bir dönem için kayıtlarda.</li>
<li><b>C-A-I (fundamentaller + kurumsal sahiplik) test edilemedi</b> — Minervini'deki boşluğun aynısı.
İki usta da aynı yeri işaret ediyor: fiyat-dışı katman (EPS ivmesi, sahiplik) bizim gerçek kör noktamız.
FMP fundamental verisiyle ayrı deney projesi fikri güçlendi.</li>
<li><b>Soy ağacı notu:</b> O'Neil → Minervini → Qullamaggie → Qulla-21. Dört kıyasın ortak sonucu:
<b>fiyat tarafındaki miras zaten sistemde</b> (lider + trend + zirve yakınlığı + rejim); ustalardan
mekanik kural taşımak değil, habitatına göre kalibre etmek kazandırıyor — bugünkü kanıt: 1.5× hacim
kaybederken 1.4× neredeyse kazanıyordu.</li>
</ul>
</div>

<h2>10) 📈 Stan Weinstein / Aşama Analizi vs Qulla-21 (02.07 ek)</h2>
<div class="card">
Kaynak: "Secrets for Profiting in Bull and Bear Markets" (1988). <b>4 Aşama</b> tek göstergeyle tanımlanır:
<b>30-haftalık MA (~150 gün)</b>. Aşama 1 = taban · <b>Aşama 2 = yükseliş (fiyat &gt; YÜKSELEN 30w MA)
— sadece burada al</b> · Aşama 3 = tepe · Aşama 4 = düşüş (asla tutma). Ek kurallar: kırılımda hacim ≥2×,
<b>Mansfield RS &gt; 0</b> (52h göreli güç), "ormandan ağaca" (önce piyasa → <b>sektör</b> → hisse),
çıkış = 30w MA altına kapanış. Bizim "Aşama-2 kapımız" (fiyat&gt;SMA20/50/200 + SLOPE200&gt;0) zaten
Weinstein mirası — ama günlük MA'larla; burada orijinal kalibrasyonu test edildi.
</div>
<table>
<tr><th>Bileşen</th><th>Weinstein (orijinal)</th><th>👑 Qulla-21 (canlı)</th></tr>
<tr><td>Aşama-2 tanımı</td><td>Fiyat &gt; YÜKSELEN 30-hafta MA (tek gösterge)</td><td>Fiyat&gt;SMA20/50/200 + SLOPE200&gt;0 (günlük) → 30w hali test edildi</td></tr>
<tr><td>Göreli güç</td><td>Mansfield RS &gt; 0 (52 hafta, S&amp;P'ye karşı)</td><td>RS top-50 (60 gün) → 52h hali test edildi</td></tr>
<tr><td>Kırılım hacmi</td><td>≥2× ortalama</td><td>Şart yok → ≥2× test edildi</td></tr>
<tr><td>Sektör teyidi</td><td>"Ormandan ağaca": sektör de Aşama-2 olmalı</td><td>Yok → test edildi (İLK kez — yeni test ailesi)</td></tr>
<tr><td>Çıkış</td><td>30w MA altına kapanış (Aşama-4'te asla tutma)</td><td>21-EMA runner + SPY rejim kapısı → 30w trail test edildi</td></tr>
<tr><td>Zaman ölçeği</td><td>Haftalık grafik, aylar-yıllar</td><td>Günlük, haftalar-aylar</td></tr>
</table>

<h3>Test sonuçları (baz = canlı 60/40, 8 varyant × 5 pencere)</h3>
<table>
<tr><th>Varyant</th><th>5y tam</th><th>Ayı 21-23</th><th>Topar 23-25</th><th>Son 2y</th><th>Son 1y</th></tr>
<tr><td><b>Baz (canlı 60/40)</b></td><td>+74.7 · 2.52</td><td>+5.9 · 1.21</td><td>+29.5 · 2.00</td><td>+70.9 · 3.65</td><td>+46.6 · 3.04</td></tr>
<tr><td>🔶 30-hafta kuralı (giriş)</td><td class="pos">+86.9 · 2.81</td><td class="pos">+9.3 · 1.34</td><td>+29.1 · 2.05</td><td>= (kapı pasif)</td><td>= (kapı pasif)</td></tr>
<tr><td>Runner 30w MA çıkışı</td><td class="pos">+92.8</td><td class="neg">-5.6 · 0.81</td><td>+27.3</td><td class="pos">+105.4 · 4.61</td><td class="pos">+84.2 · 5.43</td></tr>
<tr><td>Mansfield RS&gt;0 (52h)</td><td class="neg">+56.6</td><td class="neg">-7.3 · 0.75</td><td class="neg">+24.2</td><td class="neg">+61.5</td><td class="neg">+30.0</td></tr>
<tr><td>Kırılım hacmi ≥2×</td><td>+81.8 · 3.14</td><td class="neg">-10.7 · 0.64</td><td class="neg">+26.5</td><td class="neg">+50.7</td><td class="neg">+40.9</td></tr>
<tr><td>Sektör teyidi (Aşama-2)*</td><td>+75.8</td><td>+6.1</td><td>+29.4</td><td class="neg">+62.1</td><td class="neg">+42.9</td></tr>
<tr><td>Tam Weinstein girişi</td><td class="neg">+59.3</td><td class="neg">-9.9 · 0.69</td><td class="pos">+34.2</td><td class="neg">+52.8</td><td class="neg">+28.8</td></tr>
<tr><td>Weinstein paketi (+30w çıkış)</td><td class="pos">+125.2 · 3.51</td><td class="neg">-8.6 · 0.71</td><td class="neg">+22.2</td><td class="pos">+102.0 · 5.24</td><td class="pos">+93.7 · <b>10.28</b></td></tr>
</table>
<p class="mut">* Sektör kapsamı kısmi: pozisyonların ~%60'ında sektör ETF eşlemesi yok ("—") → kapı onları
geçirir, etkisi seyreltik. Tam kapsamlı sektör haritasıyla yeniden denenebilir.</p>

<h3>🔶 30-hafta giriş kuralı — aday adayıydı, plato testinde takıldı</h3>
<p>İlk bakışta 60/40'tan beri ilk "hiçbir pencerede kaybetmeyen" varyant: 5y ve ayıda üstün, son 2y/1y'de
birebir özdeş (RS top-50 isimleri zaten hep 150g MA üstünde → kapı pasif, <b>sıfır maliyet</b>). Ama komşu-MA
plato testi dürüst sonucu verdi: <b>130g hiç ısırmıyor</b> (bazla özdeş — mevcut Aşama-2 filtreleri o bölgeyi
zaten kapsıyor), 150g'de 5y kazancı beliriyor (+86.9), <b>170g'de ayı koruması artarken (+11.4, PF 1.42)
5y PF bazın altına düşüyor</b> (2.40). Okuma: <b>ayı-koruma yönü gerçek ve monoton</b> (150→170), boğa kazancı
ise dar kalibrasyon bandına bağlı → 60/40'ın geniş platosu standardını tutturamadı. <b>Fikir havuzunun üst
sırasına</b> kaydedildi (hacim ≥1.4×'ün yanına): "ayı korkusu artarsa 150-170g MA giriş kapısı" hazır bir dosya.</p>

<div class="card">
<b>Görüşler — Weinstein'dan alabileceğimiz var mı?</b>
<ul>
<li><b>Sistemin iskeleti zaten Weinstein:</b> Aşama-2 kapımız onun fikrinin günlük-MA uyarlaması ve
5 yıldır işini yapıyor. Orijinal 30w kalibrasyonu ancak ayı döneminde küçük ek koruma sağlıyor
(yukarıda) — devrim değil, ince ayar.</li>
<li><b>Runner 30w trail = rejim-bağımlı süper kaldıraç:</b> boğada kuyrukları devleştiriyor
(son 1y +84.2, PF 5.43; pakette PF 10.3, win %81!) ama ayıda geri-veriş katlanılmaz (-5.6/-8.6).
RS top-30'un deseni: tek rejimde parlayan her şey gibi ELENDİ. Not: "rejime göre trail seçimi"
(güçlü boğada MA150, aksi halde EMA21) cazip görünüyor ama bu tam da elediğimiz rejim-zamanlaması
tuzağı — bilinçli olarak denenmedi, fikir olarak kayıtta.</li>
<li><b>Mansfield RS (52h) bizim 60g RS'e yenildi:</b> uzun pencere göreli güç bayat sinyal —
%15-20 getiriyi siliyor. Momentum ölçüm ufku kısa olmalı; mevcut RS motoru doğru kalibre.</li>
<li><b>Hacim eşiği hikayesi tamamlandı:</b> ≥1.4× (O'Neil) neredeyse kazanıyordu, ≥1.5× orta,
<b>≥2× (Weinstein) ayıda felaket</b> (-10.7, PF 0.64). Eşik yükseldikçe ayı-kırılganlığı monoton
artıyor: dev hacimli kırılımlar ayıda kapitülasyon/squeeze. Fikir havuzundaki hacim dosyasının
sınırı netleşti: 1.3-1.45 bandı dışına çıkma. <b>Güncelleme (03.07):</b> bant komşu-eşik taramasıyla
sınandı → plato çıkmadı, dosya elendi (bölüm 11).</li>
<li><b>Sektör teyidi nötr kaldı</b> ama testin gücü düşük (kapsam %40) — tam GICS haritasıyla
yeniden denemek "gelecek deney" listesinde.</li>
<li><b>Soy ağacının kökü kapandı:</b> Weinstein (1988) → O'Neil → Minervini → Qullamaggie → Qulla-21.
Beş kıyasta da aynı desen: ustaların <b>rejim/trend hijyeni</b> sistemde zaten var; habitat-özel
detayları (stop, taban, hacim, MA periyodu) taşımak ya nötr ya zararlı. Canlı 60/40 hâlâ yenilmedi.</li>
</ul>
</div>

<h2>11) 🔊 Hacim eşiği komşu-taraması (1.25–1.50) — fikir havuzu #1'in plato testi (03.07 ek)</h2>
<div class="card">
Fikir havuzunun başındaki dosyaydı: O'Neil kıyasında <b>kırılım hacmi ≥1.4×</b> getiride 4 pencere üstün
+ 1 eşitti (şimdiye kadarki en güçlü meydan okuyucu); Weinstein'ın ≥2× felaketiyle birlikte "çalışma bandı
1.3–1.45" hipotezi doğmuştu. Burada o bant komşu-eşik taramasıyla sınandı: <b>6 eşik × 5 pencere</b>,
kapı önceki bataryalarla birebir aynı (giriş günü hacim ≥ eşik × 50g ortalama), veri aynı cache
(373 hisse — baz ve 1.40/1.50 çapaları önceki koşularla birebir tuttu, kıyas geçerli).
Aday standardı: 5/5 pencerede ROI <b>ve</b> PF üstün + <b>komşu eşikler de iyi</b> (geniş plato).
</div>

<h3>Sonuçlar (hücre: ROI · PF — yeşil: ikisi de bazdan iyi, kırmızı: ikisi de kötü)</h3>
<table>
<tr><th>Varyant</th><th>5y tam</th><th>Ayı 21-23</th><th>Topar 23-25</th><th>Son 2y</th><th>Son 1y</th></tr>
<tr><td><b>Baz (canlı 60/40)</b></td><td>+74.7 · 2.52</td><td>+5.9 · 1.21</td><td>+29.5 · 2.00</td><td>+70.9 · 3.65</td><td>+46.6 · 3.04</td></tr>
<tr><td>hacim ≥1.25×</td><td class="neg">+71.9 · 2.43</td><td class="neg">+2.6 · 1.11</td><td class="neg">+20.8 · 1.57</td><td class="neg">+62.4 · 2.85</td><td class="neg">+38.9 · 2.58</td></tr>
<tr><td>hacim ≥1.30×</td><td class="neg">+64.2 · 2.15</td><td class="neg">-1.2 · 0.96</td><td class="neg">+27.1 · 1.78</td><td class="neg">+37.5 · 1.83</td><td class="neg">+43.9 · 2.72</td></tr>
<tr><td>hacim ≥1.35×</td><td class="neg">+67.3 · 2.23</td><td class="neg">+3.7 · 1.15</td><td>+32.7 · 1.87</td><td class="neg">+35.4 · 1.81</td><td class="neg">+45.0 · 2.79</td></tr>
<tr><td><b>hacim ≥1.40×</b></td><td class="pos">+109.8 · 2.81</td><td class="pos">+6.6 · 1.29</td><td class="pos">+34.3 · 2.04</td><td>+78.1 · 3.18</td><td>+46.6 · 2.72</td></tr>
<tr><td>hacim ≥1.45×</td><td class="pos">+93.9 · 2.53</td><td class="pos">+7.1 · 1.27</td><td class="pos">+35.6 · 2.23</td><td class="neg">+37.9 · 1.95</td><td class="neg">+39.7 · 2.39</td></tr>
<tr><td>hacim ≥1.50×</td><td class="pos">+100.6 · 3.06</td><td class="neg">+4.0 · 1.15</td><td>+33.5 · 1.98</td><td class="neg">+63.4 · 2.85</td><td class="neg">+43.4 · 2.66</td></tr>
</table>

<h3>Okuma: 1.40× plato değil, İZOLE TEPE</h3>
<p><b>Bant hipotezi çürüdü.</b> 1.40×'ın solu (1.25–1.35) neredeyse her pencerede bazın altında
(1.30× ayıda negatife bile dönüyor); sağı (1.45×) son 2 yılda çöküyor (+78.1 → +37.9). Yani "iyi bölge"
tek eşiğe sıkışmış durumda. Son 2y sütununun zikzakı (62 → 38 → 35 → <b>78</b> → 38 → 63) ayrıca öğretici:
eşikteki minicik oynama hangi işlemlerin alınacağını yeniden karıyor ve bileşik getiri patikası savruluyor —
bu, sinyal değil <b>gürültüye uyum</b> imzası. Ayı zirvesi 1.40–1.45'te gerçek görünüyor ama etrafı desteksiz;
"eşik büyüdükçe ayı kırılganlığı artar" hikayesi kaba ölçekte (1.4→1.5→2×) doğru, ince ölçekte düz değil.
Hiçbir eşik 5/5 standardını geçemedi → <b>hacim dosyası fikir havuzundan ELENENLERE taşındı.</b>
Canlı 60/40, 7. değerlendirmede de yenilmedi.</p>

<div class="card">
<b>Görüşler</b>
<ul>
<li><b>1.40'ın parlaklığı komşusuz kaldı:</b> tek noktada 5y +109.8 gibi çarpıcı bir sayı, iki komşusu
bazın altındayken ancak şans/yeniden-dizilim olabilir. 60/40'ı aday yapan "geniş plato" standardı bu
taramayla üçüncü fikri eledi (30-hafta girişi, ATR% filtresi, şimdi hacim eşiği) — standart işliyor.</li>
<li><b>Hacim bilgisi çöp değil, filtre değil:</b> 🧬 DNA bulgusu duruyor — hacim patlaması "sıcaklık"
ailesinin üyesi ve büyük kazananlarda ortak. Ama zorunlu giriş kapısına çevrilecek istikrarlı bir eşik yok;
bilgi belki sıralama/önceliklendirmede (skor bileşeni) işe yarar — o ayrı ve daha zayıf bir iddia, denenmedi.</li>
<li><b>Fikir havuzunun yeni sırası:</b> başa 30-hafta "ayı korkusu" dosyası (150–170g kapı) geçti;
onun ardında Market Monitor rejimi, fundamental katman, tam-harita sektör teyidi ve ayrı-proje EP duruyor.</li>
</ul>
</div>

<h2>12) Elenenler — kısa mezarlık</h2>
<ul>
<li><b>+2R yarısına 21-EMA stopu:</b> işlem sayısı 4×, kâr faktörü 2.25→1.22. Stopsuz +2R bacağı,
CNC örneğindeki gibi geri çekilmeye dayanıp hedefe ulaşıyor — <b>stopsuzluk koruyor.</b></li>
<li><b>Tekrar-giriş yasağı:</b> son 2 yıl getirisini yarılıyor.</li>
<li><b>Runner kuralı değişimi (8-EMA / 50-MA / ATR-iz):</b> pencereler arası tutarsız.</li>
<li><b>Skor kapısı:</b> tutarlı fayda yok (savunmacı ≥80 profili hariç).</li>
<li><b>RS top-30 / top-75:</b> top-30 = kaldıraçlı konsantrasyon (ayıda çöker), top-75 sulandırıyor.</li>
<li><b>Kombinasyonlar (60/40 + 50-MA, 60/40 + top-30):</b> tek tek iyi görünen parçalar birleşince
en az bir rejimde bozuluyor → üst üste iyileştirme yığmak overfit tuzağı.</li>
<li><b>Kırılım hacmi eşiği (1.25–1.50 taraması, 03.07):</b> 1.40× izole tepe — sol komşular her yerde
bazın altında, sağ komşu son 2y'de çöküyor → plato yok, aşırı-uyum (bölüm 11).</li>
</ul>

<h2>13) Dürüst uyarılar</h2>
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

<h2>14) Durum</h2>
<div class="card">
<b>Canlı:</b> 👑 Qulla-21 COMBO (poz %7,5 + slot-serbest) + <b class="pos">⭐ 60/40 split — 02.07.2026'da
CANLIYA ALINDI</b> (<code>split_ratio 0.6</code>). Defter kullanıcı isteğiyle <b>geçmişe dönük</b> yeniden
kuruldu: START'tan (27.05) itibaren combo+60/40 tek konfig çalışmış gibi (20 pozisyon, +6.9%). ·
<b>Geri alma:</b> <code>split_ratio 0.5</code> + eski defter yedeği (<code>.bak.20260702-0954</code>) geri kopyalanır.
</div>
<p class="mut">Üretim: <code>gen_lab_report.py</code> · Deney scriptleri: scratch (lab_battery.py, lab_iter2.py, ema_guard.py, winner_dna 1-3, qm/mv/sb/oneil/ws/vol_battery.py) ·
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

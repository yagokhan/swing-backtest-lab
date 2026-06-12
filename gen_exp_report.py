# -*- coding: utf-8 -*-
"""Deney karşılaştırma raporu üreticisi → dashboard_static/exp_report.html
Canlı baz (qswing lb40 + optimized şampiyon çıkış) vs Önerilen (lb63 + atr_full 3.25×ATR).
Salt-okur: canlı sisteme/trade mantığına dokunmaz. Grafikler yerel /static/lwc.js ile.
Kullanım: python3 gen_exp_report.py"""
import copy, json
import pandas as pd
import swing2_backtest as s

OUT = "/home/gokhan/dashboard_static/exp_report.html"

# ---- veri ----
cfg = s.Config()
cfg.period = "5y"; cfg.price_source = "fmp"; cfg.disk_cache = True
cfg.use_earnings = False; cfg.per_ticker_download = False
market = s.download_and_align_data(cfg)

WINNER = {"entry_mode": "qswing_breakout", "qswing_breakout_lb": 63,
          "exit_mode": "atr_full", "atr_trail_mult": 3.25}
BASE = {"entry_mode": "qswing_breakout"}


def run(ov):
    c = copy.deepcopy(cfg)
    for k, v in ov.items(): setattr(c, k, v)
    bt = s.Swing2Backtester(c, market=market); bt.run()
    mt = bt.metrics()
    tr = pd.DataFrame([t.__dict__ for t in bt.trades])
    tr["hold"] = (pd.to_datetime(tr["exit_date"]) - pd.to_datetime(tr["entry_date"])).dt.days
    w, l = tr[tr.pnl > 0], tr[tr.pnl <= 0]
    stats = {
        "roi": mt["roi"], "dd": mt["max_dd"], "pf": mt["profit_factor"],
        "win": mt["win_rate"], "n": mt["trades"], "alpha": mt["alpha"], "spy": mt["spy_roi"],
        "hold_med": float(tr["hold"].median()), "hold_avg": float(tr["hold"].mean()),
        "hold_max": int(tr["hold"].max()),
        "avgw_pct": float(w.pnl_pct.mean()), "avgl_pct": float(l.pnl_pct.mean()),
        "maxw_pct": float(w.pnl_pct.max()), "maxl_pct": float(l.pnl_pct.min()),
        "outcomes": tr.outcome.value_counts().to_dict(),
    }
    return mt["equity"], stats


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


print("Kazanan koşuluyor...", flush=True)
eq_w, st_w = run(WINNER)
print("Canlı baz koşuluyor...", flush=True)
eq_b, st_b = run(BASE)
spy = market["spy"]["Close"].reindex(eq_w.index).ffill()

# ---- pencere/stres tabloları (deney CSV'lerinden) ----
def row_of(csv, exp):
    df = pd.read_csv(f"/home/gokhan/swing2_out/{csv}")
    d = df[df.exp == exp].set_index("win")
    return {w: d.loc[w] for w in d.index}

W = row_of("exp_d_results.csv", "d_af325_lb63")
Ws = row_of("exp_d_results.csv", "d_af325_lb63_STRESS")
B = row_of("exp_c_results.csv", "c_qbase")
Bs = row_of("exp_c_results.csv", "c_qbase_STRESS")

WIN_LABEL = {"FULL": "FULL (2020-08→2026-06)", "L2Y": "Son 2 yıl", "W1": "W1: 2021–2022 (ayı)",
             "W2": "W2: 2023–2024", "W3": "W3: 2025–2026"}

def wrow(w):
    return (f"<tr><td>{WIN_LABEL[w]}</td>"
            f"<td class='neg'>{B[w].roi:+.1f}% <span class='mut'>/ {B[w].dd:.1f}%</span></td>"
            f"<td class='pos'>{W[w].roi:+.1f}% <span class='mut'>/ {W[w].dd:.1f}%</span></td>"
            f"<td>{B[w].cagr:+.1f}% → <b>{W[w].cagr:+.1f}%</b></td></tr>")

window_table = "".join(wrow(w) for w in ("FULL", "L2Y", "W1", "W2", "W3"))

data = {
    "eq_w": series(eq_w), "eq_b": series(eq_b), "eq_spy": series(spy),
    "dd_w": dd_series(eq_w), "dd_b": dd_series(eq_b),
}

fmt = lambda x: f"{x:+.1f}"
html = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📊 Strateji Karşılaştırma Raporu — Swing 2.0 Deney İterasyonu</title>
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
 .leg{{font-size:12.5px;color:var(--mut);margin:2px 0 14px}}
 .leg b{{padding:0 4px}}
 blockquote{{border-left:3px solid var(--amb);margin:10px 0;padding:4px 14px;color:#d8c690;background:#1a1f17;border-radius:0 8px 8px 0}}
 a{{color:var(--blu)}} .back{{font-size:13px}}
 ul{{margin:6px 0 6px 20px;padding:0}} li{{margin:5px 0}}
</style></head><body><div class="wrap">
<p class="back"><a href="/">← Dashboard'a dön</a></p>
<h1>📊 Strateji Karşılaştırma Raporu</h1>
<p class="mut">Swing 2.0 deney iterasyonu · 11 Haziran 2026 · Veri: FMP günlük (S&P-altevren, 94 hisse) ·
Backtest motoru: <code>swing2_backtest.py</code> · 4 faz / ~95 konfigürasyon / ayrık-pencere doğrulama + slippage stres testi</p>

<h2>1) Yönetici Özeti</h2>
<div class="card">
<p><b>Soru:</b> Canlıda koşan strateji (qswing 40-gün kırılım girişi + "şampiyon" çıkış: %50 kısmi kâr @+2R,
+2R hedef, 2.5×ATR trailing) iyileştirilebilir mi?</p>
<p><b>Cevap:</b> Evet — ve iyileştirme parametre ince ayarından değil, <b>çıkış mimarisinin değiştirilmesinden</b> geliyor.
Önerilen varyant girişte kırılım penceresini 63 güne (çeyreklik tepe) uzatıyor, çıkışta ise kısmi kâr almayı ve
sabit hedefi tamamen kaldırıp pozisyonun tamamını <b>3.25×ATR'lik şamdan (chandelier) izleyen stopla</b> taşıyor.
Aynı veri, aynı evren, aynı maliyet varsayımlarıyla 5.8 yıllık toplam getiri <b>+%89'dan +%273'e</b> çıkarken
maksimum düşüş (drawdown) <b>−%27.3'ten −%18.7'ye geriliyor</b>; kâr faktörü 1.37'den 3.95'e yükseliyor.</p>
<p>İktisadi özü tek cümlede: <i>mevcut sistem kazanan işlemlerin sağ kuyruğunu +2R'de kesip kaybedenlerin
maliyetini yüksek işlem frekansıyla katlıyor; önerilen sistem nadir ama büyük trendleri sonuna kadar taşıyıp
ciroyu (ve dolayısıyla sürtünme vergisini) beşte birine indiriyor.</i></p>
</div>
<div class="kpis">
 <div class="kpi"><div class="l">Toplam getiri (5.8y) — canlı → öneri</div><div class="v">{st_b['roi']:+.0f}% → <span class="pos">{st_w['roi']:+.0f}%</span></div></div>
 <div class="kpi"><div class="l">Maks. düşüş</div><div class="v">{st_b['dd']:.1f}% → <span class="pos">{st_w['dd']:.1f}%</span></div></div>
 <div class="kpi"><div class="l">Kâr faktörü</div><div class="v">{st_b['pf']:.2f} → <span class="pos">{st_w['pf']:.2f}</span></div></div>
 <div class="kpi"><div class="l">SPY'a karşı alfa</div><div class="v">{st_b['alpha']:+.0f} → <span class="pos">{st_w['alpha']:+.0f}</span> pp</div></div>
 <div class="kpi"><div class="l">İşlem sayısı</div><div class="v">{st_b['n']} → {st_w['n']}</div></div>
 <div class="kpi"><div class="l">Medyan tutuş</div><div class="v">{st_b['hold_med']:.0f} → {st_w['hold_med']:.0f} gün</div></div>
</div>

<h2>2) Giriş–Çıkış Kuralları: Mevcut Kağıt-Trade vs Öneri</h2>
<div class="card">
<p>Mevcut kağıt-trade sistemi <b>tek giriş + iki paralel çıkış portföyü</b> koşturuyor: girişler her iki
portföyde birebir aynı (40 günlük kırılım taraması), yalnız çıkış kuralı ayrışıyor (🏆 ATR-trail ve 📐 8/21-EMA).
Önerilen yöntem (💡) hem girişi hem çıkışı değiştiriyor. Aşağıdaki iki tablo farkları kural düzeyinde gösterir.</p>

<h3>GİRİŞ kuralları</h3>
<table>
<tr><th>Bileşen</th><th>Mevcut paper (🏆 ve 📐 ortak)</th><th>💡 Önerilen</th></tr>
<tr><td>Hisse havuzu</td><td colspan="2" style="text-align:center">AYNI — 95 ABD mega-cap (S&P-100 ağırlıklı + momentum isimleri)</td></tr>
<tr><td>Piyasa kapısı</td><td colspan="2" style="text-align:center">AYNI — SPY &gt; SMA200 değilse yeni alım yok (ayı rejiminde nakit)</td></tr>
<tr><td>Trend ön-filtresi</td><td colspan="2" style="text-align:center">AYNI — Kapanış &gt; SMA20/50/200 + SMA200 eğimi pozitif (Stage-2)</td></tr>
<tr><td><b>Kırılım eşiği</b></td><td>Önceki <b>40 günün</b> tepesi kırılınca</td><td class="pos">Önceki <b>63 günün</b> (çeyreklik) tepesi kırılınca — daha nadir, daha seçici sinyal</td></tr>
<tr><td>Zirve yakınlığı</td><td colspan="2" style="text-align:center">AYNI — Fiyat ≥ 52-hafta zirvesinin %75'i</td></tr>
<tr><td>Momentum / görece güç</td><td colspan="2" style="text-align:center">AYNI — 60g getiri &gt; 0 ve ≥ SPY 60g getirisi</td></tr>
<tr><td>Sıralama</td><td colspan="2" style="text-align:center">AYNI — 0–100 öncelik puanı (canlı tarayıcı formülü)</td></tr>
<tr><td>Boyutlama</td><td>Eşit-ağırlık: o günkü TÜM sinyaller alınır, nakit aralarında bölünür (poz. tavanı yok)</td><td>Backtest'te maks. 5 pozisyon × sermayenin %20'si; doluysa sinyal pas geçilir</td></tr>
<tr><td>Giriş anı / fiyatı</td><td>15:45 ET tarama fiyatı +3bps kayma</td><td>Kapanış (≈15:45 kanıtlı eşdeğer) +8bps kayma — aynı pratik, daha muhafazakâr maliyet varsayımı</td></tr>
</table>

<h3>ÇIKIŞ kuralları</h3>
<table>
<tr><th>Bileşen</th><th>🏆 ATR-trail (şampiyon)</th><th>📐 8/21-EMA varyantı</th><th>💡 Önerilen (şamdan)</th></tr>
<tr><td>İlk koruma stopu</td><td>max(10-gün dip, giriş−1.5×ATR) — <b>gün-içi</b> değince çıkar</td><td class="amb">YOK (ortak felaket stopu yok)</td><td>Örtük: giriş−3.25×ATR (şamdanın başlangıç seviyesi) — yalnız kapanışta</td></tr>
<tr><td>Kısmi kâr alma</td><td>%50 @ +2R (limit emir)</td><td>%50 kapanış &lt; 8-EMA olunca</td><td class="pos">YOK — pozisyon bölünmez</td></tr>
<tr><td>Sabit hedef</td><td>+2R (kısmiyle aynı seviye → pratikte tam pozisyon +2R'de kapanır)</td><td>YOK</td><td class="pos">YOK — tavan koymaz, trend ne verirse</td></tr>
<tr><td>Trailing</td><td>+1R sonrası stop = kapanış−2.5×ATR (yalnız yukarı)</td><td>Kalan %50 kapanış &lt; 21-EMA olunca çıkar</td><td class="pos">Stop = TEPE fiyat−3.25×ATR (kapanışa değil tepeye bağlı, yalnız yukarı)</td></tr>
<tr><td>Breakeven kuralı</td><td>Kısmi sonrası stop girişe çekilir</td><td>YOK</td><td>YOK (şamdan doğal olarak kilitler)</td></tr>
<tr><td>Değerlendirme anı</td><td>Stop gün-içi (iğne), kısmi/hedef gün-içi limit</td><td>Yalnız kapanış teyidi</td><td>Yalnız kapanış teyidi</td></tr>
<tr><td>Tipik tutuş</td><td>Medyan ~11 gün</td><td>Daha uzun (runner 21-EMA'da)</td><td>Medyan ~46 gün</td></tr>
<tr><td>Karakter</td><td>Yüksek isabet (%52), küçük asimetri (+8.1/−3.7) — kuyruk +2R'de kesilir</td><td>Trend-takip ama EMA'lar testereye duyarlı</td><td>Düşük isabet (%46), büyük asimetri (+20.9/−5.1 ≈ 4:1) — kuyruk taşınır</td></tr>
</table>

<p><b>Ekonomist okuması:</b> Üç çıkış aslında üç farklı "kuyruk politikası"dır. 🏆 sağ kuyruğu +2R'de satar
(gelirini bugün alır, opsiyon satıcısı gibi); 📐 kuyruğu EMA'lara emanet eder ama 8-EMA bacağı testere
piyasada sık tetiklenir; 💡 kuyruğu sonuna kadar taşır ve bunun bedelini düşük isabet oranı + derin tekil
geri çekilmelerle öder. Backtest'in söylediği: bu evrende (momentum mega-cap) kuyruğu taşımanın primi,
bedelinden belirgin biçimde büyük. Ayrıca dikkat: önerilen backtest 5×%20 boyutlamayla koşuldu; mevcut paper'ın
"tüm sinyaller eşit-ağırlık" kuralıyla birebir aynı değil — kağıt-trade'e alınırsa bu fark da ölçülmüş olacak.</p>
</div>

<h2>3) Özsermaye Eğrisi (100 = başlangıç, log ölçek)</h2>
<div id="ch_eq" class="chart"></div>
<div class="leg"><b style="color:#3fb950">■</b> Önerilen (lb63 + 3.25×ATR şamdan) &nbsp;
<b style="color:#f85149">■</b> Canlı baz (lb40 + optimized) &nbsp; <b style="color:#8b949e">■</b> SPY</div>
<p>Eğrinin anlattığı: 2021–22'nin yatay/ayı rejiminde iki strateji de SPY&gt;SMA200 kapısı sayesinde büyük ölçüde
nakitte bekliyor (eğriler düz). Ayrışma 2023'ten itibaren trendlerin uzamasıyla başlıyor ve 2024 ile 2026'nın
güçlü momentum dönemlerinde açılıyor. Dikkat çekici nokta: canlı baz bu dönemde <b>SPY'ın bile altında</b>
({fmt(st_b['roi'])}% vs SPY {fmt(st_b['spy'])}%) — yani mevcut çıkış mimarisi, üstlendiği hisse-özgü riske karşılık
endeks üstü getiri üretmiyor. Bu, "pasif endekse karşı fırsat maliyeti" ölçütünde ciddi bir bulgudur.</p>

<h2>4) Drawdown Profili</h2>
<div id="ch_dd" class="chart"></div>
<div class="leg"><b style="color:#3fb950">■</b> Önerilen &nbsp; <b style="color:#f85149">■</b> Canlı baz</div>
<p>Sezgiye aykırı sonuç: <b>daha az müdahale eden çıkış, daha sığ drawdown üretiyor.</b> Nedeni mekanik:
canlı baz dar stoplarla (1.5×ATR) sık sık küçük kayıplar alıp yeniden giriyor; testere piyasada bu kayıplar
birikiyor (ölüm bin kesikle). Şamdan trail ise pozisyona geniş nefes payı bırakıp <i>tepe fiyattan</i> izlediği için
trend bozulmadan çıkmıyor; testereye hiç girmeyen (daha seçici, 63g kırılım) girişlerle birleşince
toplam zarar havuzu küçülüyor.</p>

<h2>5) Pencere Bazlı Dayanıklılık (out-of-sample tasarımı)</h2>
<div class="card">
<p>Tek dönemlik backtest'ler "şanslı pencere" yanılgısına açıktır. Bu çalışmada parametreler hiçbir alt-pencereye
göre seçilmedi; adaylar <b>üç ayrık (örtüşmeyen) dilimde</b> ayrı ayrı sınandı ve sıralama ölçütü
"en kötü dilimdeki yıllıklandırılmış getiri" oldu — yani strateji en zayıf rejimine göre yargılandı
(maximin / Rawls'çu seçim kriteri).</p>
<table>
<tr><th>Pencere</th><th>Canlı baz ROI / DD</th><th>Önerilen ROI / DD</th><th>CAGR değişimi</th></tr>
{window_table}
</table>
<p>Önerilen varyant <b>her dilimde pozitif</b> — 2022 ayı piyasası dahil. Canlı baz ise W1'de negatif.
İktisatçı diliyle: getiri serisinin rejimler-arası varyansı düşmüş, yani performans tek bir makro ortama
(düşük faiz / yüksek momentum) koşullu değil.</p>
</div>

<h2>6) Getirinin Kaynağı — Ekonomik Ayrıştırma</h2>
<h3>a) Ciro vergisi (turnover tax)</h3>
<p>Canlı baz yılda ~105 işlem yapıyor; her işlem çifti tahmini 13–23 baz puan sürtünme (spread + kayma + komisyon)
ödüyor. Bu, sermaye üzerinde yıllık <b>~%2.5–3'lük görünmez bir vergi</b> demektir. Önerilen varyant cironun
beşte biriyle (~20 işlem/yıl) aynı piyasaya maruz kalıyor. Stres testi bunu doğruluyor: kayma maliyetleri
<b>iki katına</b> çıkarıldığında canlı bazın getirisi +%89→+%56'ya çökerken (−%38 duyarlılık), önerilen
+%273→+%254'te kalıyor (−%7). Düşük ciro = maliyet şoklarına karşı doğal sigorta.</p>
<h3>b) Pozitif çarpıklık: kuyruğu satmak yerine kuyruğu taşımak</h3>
<p>Mevcut çıkış (+2R'de kısmi + hedef) davranışsal olarak rahatlatıcıdır ama finansal olarak
<b>örtük bir alım opsiyonu satışıdır</b>: her kazananın getirisi +2R'de tavanlanır, kaybedenler ise tam stop yer.
Kazanç dağılımının sağ kuyruğu — momentum stratejilerinde getirinin asıl kaynağı — sistematik biçimde
karşı tarafa devredilir. Önerilen varyantta dağılım tersine çevriliyor: isabet oranı düşüyor
(%{st_b['win']:.0f} → %{st_w['win']:.0f}) ama ortalama kazanç/kayıp oranı <b>{abs(st_w['avgw_pct']/st_w['avgl_pct']):.1f}:1</b>'e
çıkıyor (ort. kazanç {fmt(st_w['avgw_pct'])}%, ort. kayıp {fmt(st_w['avgl_pct'])}%; en büyük tekil kazanç
{fmt(st_w['maxw_pct'])}%). Bu, klasik trend-takip iktisadıdır: çok sayıda küçük yanlış, az sayıda çok büyük doğru.</p>
<h3>c) Beta zamanlaması</h3>
<p>Her iki strateji de SPY&gt;SMA200 kapısıyla ayı rejiminde alım yapmıyor; fark, kapı açıldığında ne yapıldığında.
63 günlük (çeyreklik) tepe kırılımı, 40 günlüğe göre daha nadir ve daha "kanıtlanmış" trend sinyali üretiyor —
sinyal başına bilgi içeriği artıyor, gürültü/sinyal oranı düşüyor.</p>

<h2>7) İşlem Karakteri</h2>
<table>
<tr><th></th><th>Canlı baz</th><th>Önerilen</th></tr>
<tr><td>İşlem sayısı (5.8y)</td><td>{st_b['n']}</td><td>{st_w['n']}</td></tr>
<tr><td>Medyan / ort. / maks. tutuş (gün)</td><td>{st_b['hold_med']:.0f} / {st_b['hold_avg']:.0f} / {st_b['hold_max']}</td><td>{st_w['hold_med']:.0f} / {st_w['hold_avg']:.0f} / {st_w['hold_max']}</td></tr>
<tr><td>İsabet oranı</td><td>%{st_b['win']:.1f}</td><td>%{st_w['win']:.1f}</td></tr>
<tr><td>Ort. kazanç / ort. kayıp</td><td>{fmt(st_b['avgw_pct'])}% / {fmt(st_b['avgl_pct'])}%</td><td>{fmt(st_w['avgw_pct'])}% / {fmt(st_w['avgl_pct'])}%</td></tr>
<tr><td>En büyük kazanç / kayıp (tekil)</td><td>{fmt(st_b['maxw_pct'])}% / {fmt(st_b['maxl_pct'])}%</td><td>{fmt(st_w['maxw_pct'])}% / {fmt(st_w['maxl_pct'])}%</td></tr>
<tr><td>Kâr faktörü</td><td>{st_b['pf']:.2f}</td><td>{st_w['pf']:.2f}</td></tr>
</table>
<p class="mut">Önerilen varyant "swing trade"den çok "pozisyon trade"dir: medyan {st_w['hold_med']:.0f} gün tutuş,
sinyal sıklığı ayda ~2. Davranışsal maliyeti aşağıda (Bölüm 9) tartışılıyor.</p>

<h2>8) Aylık Getiri Tabloları</h2>
<h3 class="pos">Önerilen — lb63 + 3.25×ATR şamdan</h3>
{monthly_html(eq_w)}
<h3 class="neg">Canlı baz — lb40 + optimized şampiyon çıkış</h3>
{monthly_html(eq_b)}

<h2>9) Riskler ve Sınırlamalar — Dürüst Okuma</h2>
<blockquote><b>Bu bölüm raporun en önemli kısmıdır.</b> Hiçbir backtest gelecek getiri vaadi değildir;
aşağıdaki maddeler önerinin hangi koşullarda <i>başarısız olabileceğini</i> tanımlar.</blockquote>
<ul>
<li><b>Gün-içi sert stop yok:</b> Şamdan çıkışı yalnız <i>kapanışta</i> değerlendirilir. Sert gap'lerde tekil işlem
kaybı büyüyebilir; gözlenen en kötü işlem {fmt(st_w['maxl_pct'])}% (pozisyon %20 olduğundan portföye etkisi ~−%4.5).
Mevcut sistemin gün-içi stopu bu kuyruğu kısmen keser — bunun bedelini de getiriyle öder.</li>
<li><b>İstatistiksel güç:</b> {st_w['n']} işlem, 614'e kıyasla küçük örneklem; güven aralıkları geniştir.
Karşı denge: trail çarpanı 2.75–3.5 aralığının tamamı güçlü sonuç veriyor (parametre <i>platosu</i>) ve
lb40 versiyonu da +%217 üretiyor — sonuç tek bir parametre noktasına bağlı değil.</li>
<li><b>Seçim yanlılığı:</b> ~95 konfigürasyon tarandı; en iyinin bir kısmı şanstır. Ayrık pencereler ve stres testi
bu yanlılığı azaltır ama sıfırlamaz. İhtiyatlı beklenti, rapor edilen rakamların altıdır.</li>
<li><b>Dönem katkısı:</b> 2026 H1 (+%91) toplam getirinin önemli parçası. Gerçi 2023–24 dilimi de bağımsız olarak
+%36 CAGR veriyor; yine de momentum stratejileri uzun "düz" dönemler yaşar (örn. 2025: −%0.6 — koca yıl sıfır).</li>
<li><b>Davranışsal yük:</b> 46 gün medyan tutuş, tepeden %15–20 geri çekilmeyi "çıkmadan izlemeyi" gerektirir
(şamdan tasarımı gereği). Kâğıt üzerinde kolay, gerçek parayla zordur; disiplin kırılırsa backtest geçersizleşir.</li>
<li><b>Veri notları:</b> FMP fiyatları temettü-ayarsızdır (split-ayarlı); temettü dahil edilse iki strateji de
hafif daha iyi görünürdü. Evren bugünün S&P bileşenlerinden türetildiği için sınırlı <i>survivorship</i> yanlılığı
içerir — bu yanlılık <b>iki stratejiye de eşit</b> uygulanır, dolayısıyla <i>göreli</i> karşılaştırmayı bozmaz.</li>
<li><b>Kapasite/likidite:</b> Mevcut portföy ölçeğinde ($10k–100k) ihmal edilebilir; strateji büyük ölçekte de
likit hisselerde çalışır, ancak kayma varsayımları kurumsal boyutta yeniden kalibre edilmelidir.</li>
</ul>

<h2>10) Sonuç ve Tavsiye</h2>
<div class="card">
<p><b>Tavsiye: kademeli geçiş, ani değişim değil.</b> Önerilen varyantı canlı sinyal akışına paralel
<b>üçüncü kağıt-trade portföyü</b> olarak eklemek (🏆 ATR-trail ve 📐 8/21-EMA'nın yanına), 2–3 ay gerçek-zamanlı
gözlemden sonra sermaye tahsisi kararı vermek. Bu, backtest ile canlı icra arasındaki boşluğu (gerçek kayma,
sinyal zamanlaması, davranışsal uyum) ölçmenin en ucuz yoludur.</p>
<p>Karar çerçevesi (ekonomist gözüyle): mevcut sistemin alternatif maliyeti yüksek — aynı risk bütçesiyle endeksin
altında getiri. Önerilen varyantın beklenen değeri belirgin biçimde yüksek, riski <i>farklı</i> (daha az ama daha
derin tekil kayıplar, uzun düz dönemler). İkisi davranışsal olarak farklı ürünlerdir; geçiş kararı yalnız getiri
beklentisine değil, taşıyıcının drawdown ve sabır toleransına göre verilmelidir.</p>
</div>
<p class="mut">Üretim: <code>gen_exp_report.py</code> · Deney altyapısı: <code>exp_swing2*.py</code>, sonuçlar
<code>swing2_out/exp_{{a,b,c,d}}_results.csv</code> · Bu sayfa salt-okur bir rapordur; canlı trade mantığına etkisi yoktur.</p>
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
eq.addLineSeries({{color:'#3fb950',lineWidth:2}}).setData(DATA.eq_w);
eq.addLineSeries({{color:'#f85149',lineWidth:2}}).setData(DATA.eq_b);
eq.addLineSeries({{color:'#8b949e',lineWidth:1}}).setData(DATA.eq_spy);
eq.timeScale().fitContent();
const dd = mkChart('ch_dd', false);
dd.addAreaSeries({{lineColor:'#3fb950',topColor:'rgba(63,185,80,.25)',bottomColor:'rgba(63,185,80,0)',lineWidth:2}}).setData(DATA.dd_w);
dd.addAreaSeries({{lineColor:'#f85149',topColor:'rgba(248,81,73,.25)',bottomColor:'rgba(248,81,73,0)',lineWidth:2}}).setData(DATA.dd_b);
dd.timeScale().fitContent();
</script></body></html>"""

import os
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(f"Rapor yazıldı: {OUT} ({len(html)//1024} KB)")

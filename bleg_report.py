"""bleg_lab.py --run çıktısından (bleg_results.json) /adaylar sayfasına
'%40'lık runner bacağı — kârda mı zararda mı?' bölümünü üretir/günceller.
Sadakat kanıtı (fidelity_ok) olmadan yazmaz. İdempotent: BLEG:BEGIN/END markörleri."""
import datetime
import json

OUT_JSON = "/home/gokhan/swing2_out/bleg_results.json"
ADAYLAR = "/home/gokhan/dashboard_static/adaylar.html"

VLABEL = {
    "baz":   "⚪ Baz (eski canlı)",
    "atr":   "🔵 Aday 1 · Hareketliye öncelik",
    "tavan": "🟢 Aday 2 · En çok kazandıran",
    "blend": "🟡 Aday 3 · En dengeli ⭐ canlı",
}
KEYS = ["baz", "atr", "tavan", "blend"]
WINS_TR = ["5 yıl (tümü, 2021→2026)", "Düşüş dönemi 2021-23 (zor dönem)",
           "Toparlanma 2023-25", "Son 2 yıl", "Son 1 yıl"]

TR = lambda v: ("%.1f" % v).replace(".", ",")
TR2 = lambda v: ("%.2f" % v).replace(".", ",")


def _usd(v):
    v = int(round(v))
    sign = "−" if v < 0 else ""
    return sign + "$" + format(abs(v), ",").replace(",", ".")


def _pct(v, plus=True):
    if v is None:
        return "—"
    s = ("+" if v >= 0 and plus else ("−" if v < 0 else "")) + "%"
    return s + TR(abs(v))


def _winloss_bar(win_rate):
    """Yeşil (kâr) / kırmızı (zarar) oransal şerit — saf CSS, JS yok."""
    w = max(2.0, min(98.0, win_rate))
    return ('<span style="display:inline-flex;width:150px;height:12px;border-radius:6px;'
            'overflow:hidden;vertical-align:middle;border:1px solid var(--bd)">'
            '<span style="width:%.1f%%;background:var(--grn)"></span>'
            '<span style="width:%.1f%%;background:var(--red)"></span></span>') % (w, 100 - w)


def report():
    d = json.load(open(OUT_JSON))
    assert d.get("fidelity_ok"), "sadakat kanıtı olmadan rapor yazılmaz"
    V = d["variants"]

    # --- Tablo 1: 5 yıl anlık — yöntem başına runner bacağı bilançosu ---
    t1 = []
    for k in KEYS:
        r = V[k]["rows"][0]
        hl = ' style="background:rgba(201,133,0,.08)"' if k == "blend" else ""
        t1.append(
            "<tr%s><td>%s</td><td>%d</td><td>%s&nbsp;&nbsp;%s (%d/%d)</td>"
            "<td>%s</td><td>%s</td><td class='pos'>%s</td><td class='neg'>%s</td>"
            "<td><b>%s</b></td><td>%s</td><td>%d · %s</td></tr>" % (
                hl, VLABEL[k], r["n_ema"], _winloss_bar(r["win_rate"]),
                _pct(r["win_rate"], plus=False), r["n_win"], r["n_ema"],
                _pct(r["med_win_pct"]), _pct(r["med_loss_pct"]),
                _usd(r["usd_win"]), _usd(r["usd_loss"]), _usd(r["usd_net"]),
                _pct(r["best_pct"]), r["n_eod"], _usd(r["usd_eod"])))
    table1 = ('<div style="overflow-x:auto"><table><tr>'
              '<th>Yöntem</th><th>EMA21 çıkışı (n)</th><th>Yeşil kapanan</th>'
              '<th>Kazanç medyanı</th><th>Kayıp medyanı</th><th>Kazananlardan</th>'
              '<th>Kaybedenlerden</th><th>Net</th><th>En iyi tek</th>'
              '<th>Pencere-sonu kalıntı (n · $)</th></tr>' + "".join(t1) + "</table></div>")

    # --- Tablo 2: tüm pencereler × yöntemler tam ızgara ---
    t2 = []
    for wi, wn in enumerate(WINS_TR):
        for k in KEYS:
            r = V[k]["rows"][wi]
            hl = ' style="background:rgba(201,133,0,.08)"' if k == "blend" else ""
            netcls = "pos" if r["usd_net"] >= 0 else "neg"
            t2.append(
                "<tr%s><td>%s · %s</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td>"
                "<td class='%s'>%s</td><td>%s g</td><td>%d · %s</td></tr>" % (
                    hl, wn, VLABEL[k], r["n_ema"], _pct(r["win_rate"], plus=False),
                    _pct(r["med_win_pct"]), _pct(r["med_loss_pct"]), netcls,
                    _usd(r["usd_net"]),
                    ("%d" % r["med_hold"]) if r["med_hold"] is not None else "—",
                    r["n_eod"], _usd(r["usd_eod"])))
    table2 = ('<div style="overflow-x:auto"><table><tr>'
              '<th>Dönem · Yöntem</th><th>EMA21 çıkışı</th><th>Yeşil</th>'
              '<th>Kazanç med.</th><th>Kayıp med.</th><th>Net $</th>'
              '<th>Tutma (med.)</th><th>Kalıntı (n · $)</th></tr>'
              + "".join(t2) + "</table></div>")

    # --- prose için birkaç anlık sayı ---
    b = V["blend"]["rows"][0]
    wr_lo = min(V[k]["rows"][0]["win_rate"] for k in KEYS)
    wr_hi = max(V[k]["rows"][0]["win_rate"] for k in KEYS)
    net_all_pos_5y = all(V[k]["rows"][0]["usd_net"] > 0 for k in KEYS)
    bear_net = {k: V[k]["rows"][1]["usd_net"] for k in KEYS}

    section = """<!-- BLEG:BEGIN -->
<h2 id="bleg">🎯 %40'lık runner bacağı — kârda mı zararda mı kapanıyor? (2026-07-07)</h2>
<blockquote><p><b>Soru:</b> Her alımın <b>%40'ı</b> "runner" bacağıdır: +2R hedefi yoktur,
fiyat <b>21 günlük üstel ortalamanın (EMA21) altına kapanınca</b> satılır — trend sürdükçe
aylarca taşınır. Bu bacak EMA21'de kapandığında <b>ne kadarı yeşil (kârda), ne kadarı kırmızı
(zararda) çıkıyor?</b> Yukarıdaki 🛡️ deneyi %60'lık A bacağını inceledi; bu bölüm onun ikizi:
runner bacağını dört yöntemde de (Baz · Aday 1 · Aday 2 · Aday 3) aynı sabit veride, motor
davranışı değişmeden ölçer. Kanıt: her koşunun ROI'si /adaylar getiri tablosuyla birebir
(<b>20/20 batarya-birebir</b>; blend'de işlem sayısı da tuttu).</p></blockquote>

<p><b>Kısa cevap: EMA21'de kapanan runner bacaklarının çoğu KIRMIZI — 5 yılda yalnız ~%@@WRLO@@–@@WRHI@@ yeşil
(kabaca 3 bacaktan 1'i).</b> Ama bacak yine de <b>net PARA KAZANDIRIYOR</b>, çünkü kazanan azınlık,
kaybeden çoğunluktan çok daha büyük: kaybedenler EMA21 takibinin verdiği küçük geri-ödemede
sıkışık (medyan ~−%5), kazananlarsa şişman kuyruklu (Aday 3'te kazanç medyanı +%@@MEDW@@,
%90'lık dilim +%@@BIGW@@, en iyi tek runner <b>+%@@BEST@@</b>). Runner'ın tüm felsefesi budur:
<b>çok sayıda küçük geri-ödemeyi, az sayıda büyük koşucuyla fonlamak.</b> Kazananlar medyan
@@MEDHW@@ işlem günü taşınırken kaybedenler @@MEDHL@@ günde biçiliyor — yani sistem kaybedeni
erken bırakıp kazananı koşturuyor.</p>

<h3 style="font-size:15px;margin:18px 0 6px">Tek bakışta: 5 yılda runner bacağının bilançosu</h3>
@@TABLE1@@
<p class="note">"EMA21 çıkışı" = %40'lık bacağın kapanış&lt;21-EMA kuralıyla gerçekten satıldığı
işlemler. "Yeşil kapanan" şeridi kâr/zarar oranını gösterir (yeşil = kârda kapanan pay).
"Pencere-sonu kalıntı" = dönem biterken EMA21'i hâlâ kırmamış, taşınmaya devam eden bacaklar
(gerçek çıkış değil, backtest penceresinin kestiği koşucular — bunlar çoğunlukla yeşildir, zaten
o yüzden çıkmamışlar). Tutarlar bileşik büyüyen sermaye üstünden dolardır; komisyon/kayma dahil.</p>

<h3 style="font-size:15px;margin:22px 0 6px">Dönem dönem — dört yöntem yan yana</h3>
@@TABLE2@@
<p class="note"><b>Desen dört yöntemde de aynı:</b> yükseliş dönemlerinde runner bacağı güçlü net
pozitif, <b>düşüş döneminde (2021-23) net ~sıfır/negatif</b> (@@BEARLINE@@) — trend olmayınca
runner testerede kırpılır; o pencereleri +2R hedefli A bacağı ve piyasa-genişliği freni taşır.
Yöntemler arasındaki fark runner <i>mekaniğinden</i> değil, hangi hisselerin içeri girdiğinden
(sıralama + fren) doğar: kazanma oranları birbirine yakın (~%28–42), asıl ayrım kazanan
kuyruğunun büyüklüğünde. @@NETLINE@@</p>
<!-- BLEG:END -->
""".replace("@@WRLO@@", TR(wr_lo)).replace("@@WRHI@@", TR(wr_hi)) \
   .replace("@@MEDW@@", TR(b["med_win_pct"])).replace("@@BIGW@@", TR(b["big_win_pct"])) \
   .replace("@@BEST@@", TR(b["best_pct"])).replace("@@MEDHW@@", str(int(b["med_hold_win"]))) \
   .replace("@@MEDHL@@", str(int(b["med_hold_loss"]))) \
   .replace("@@TABLE1@@", table1).replace("@@TABLE2@@", table2) \
   .replace("@@BEARLINE@@", "Aday 3 %s · Baz %s · Aday 1 %s · Aday 2 %s" % (
       _usd(bear_net["blend"]), _usd(bear_net["baz"]),
       _usd(bear_net["atr"]), _usd(bear_net["tavan"]))) \
   .replace("@@NETLINE@@", ("5 yıl toplamında dört yöntemde de runner bacağı net pozitif."
                            if net_all_pos_5y else ""))

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

    html = upsert(html, "<!-- BLEG:BEGIN -->", "<!-- BLEG:END -->", section,
                  "<h2>Karar öncesi tartılan noktalar</h2>")
    open(ADAYLAR, "w").write(html)
    print("adaylar.html güncellendi · BLEG bölümü eklendi/yenilendi")


if __name__ == "__main__":
    report()

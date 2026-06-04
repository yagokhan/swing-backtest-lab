# qswing Girişi + İki Çıkış Stratejisi — Ekonomist Bakışıyla Analiz

> **Amaç:** Giriş olarak `qswing` (Qullamaggie kırılım) kullanırken iki çıkış adayını
> — **(A) 10-gün MA trail** ve **(B) 8-EMA hibrit** — bir ekonomistin/portföy
> kuramının diliyle tartmak. Tüm sayılar bu repodaki motorla (`swing2_backtest.py`),
> **sp500 evreni · 5 yıl · FMP /stable** üzerinde üretildi.
>
> *Eğitim/araştırma amaçlıdır; yatırım tavsiyesi değildir. Geçmiş performans geleceği garanti etmez.*

---

## 0. Yönetici Özeti

İki çıkış de **neredeyse aynı toplam getiriyi** üretiyor (ROI ~%117 vs ~%119), ama
**getiri dağılımının şeklini** tamamen farklı kuruyorlar. Mesele "hangisi daha çok
kazandırır" değil; **"hangi risk dokusunu istiyorsun"** sorusudur:

| | **10g MA trail** | **8-EMA hibrit** |
|---|---|---|
| Karakter | Yüksek frekanslı, **simetriğe yakın** hasat | Düşük frekanslı, **konveks (pozitif çarpık)** |
| İşlem davranışı | Çok sayıda küçük kazanç + küçük kayıp | Az sayıda **çok büyük** kazanç + sık küçük kayıp |
| Ekonomik analoji | **Opsiyon satıcısı** (theta hasadı, covered-call) | **Opsiyon alıcısı** (kuyruğu satın alır, premyumu öder) |
| Kime uygun | İstikrar, yüksek isabet, düşük sermaye devri tercih eden | Kuyruk yakalamak, daha iyi DD, sermaye devrine tahammül eden |

---

## 1. Giriş: qswing (Qullamaggie kırılımı) — neyi "hasat" ediyor?

### Mekanik (koddaki gerçek kurallar)
Bir hisse şu **eşzamanlı** koşulları geçince alınır (`_qswing_entry_ok` + Aşama-2 ön-filtreleri):

1. **Rejim açık** — SPY > SMA200 (piyasa düşüşünde yeni alım yok).
2. **Aşama 2 trend** — Fiyat > SMA20 **ve** SMA50 **ve** SMA200; **SLOPE200 > 0** (200-gün eğimi pozitif).
3. **Kırılım** — Bugünün kapanışı önceki **40 günün en yükseğini** aşıyor (yeni alan açma).
4. **Zirve yakınlığı** — Fiyat 52-hafta zirvesine yakın (`qswing_near_high × HIGH52`).
5. **Görece güç (RS)** — 60-gün getiri − SPY 60-gün getirisi ≥ eşik; ham 60g getiri pozitif.

Giriş = kırılım kapanışı. Stop = **10-gün dip (LOW10)**, ATR ile tabanlanır
(`close − atr_stop_mult × ATR`). **Risk birimi (R)** = giriş − stop. Pozisyon boyutu
bu R'ye göre ölçeklenir (sabit risk/işlem).

### Ekonomik temel — bu bir **momentum faktörü** hasadıdır
- **Kesitsel + zaman-serisi momentum** (Jegadeesh–Titman 1993; Moskowitz–Ooi–Pedersen 2012):
  RS filtresi kazananları kazananlarla kıyaslar (kesitsel), 40g kırılım + pozitif 60g getiri
  zaman-serisi devamlılığını yakalar.
- **Davranışsal mikro-temel:** Kırılım, bilginin yavaş yayılmasından (under-reaction),
  çıpalama (anchoring) ve disposition etkisinden doğan **gecikmeli fiyat keşfini** ister.
  52-hafta zirvesi yakınlığı, "zirve direnci" çıpasının kırılmasının bilgi içerdiği
  hipotezine dayanır (George–Hwang 2004, "52-week high momentum").
- **Rejim koşullandırma (SPY>SMA200):** Momentum primi rejime bağlıdır; ayı piyasalarında
  momentum **çöküşleri (momentum crashes)** yaşar (Daniel–Moskowitz 2016). Rejim filtresi
  bu sol-kuyruk maruziyetini azaltan basit bir **durum-değişkeni (state variable)** kontrolüdür.
- **Likidite/kalite vekili:** sp500 evreni + Aşama-2 trend, mikro-cap gürültüsünü ve
  değer tuzaklarını dışlar — taşınan risk primi "trend süren, likit, büyük-cap momentum"dur.

> **Özet:** Giriş, *"piyasa yukarı rejimdeyken, görece güçlü ve yeni zirve alanı açan
> likit hisseyi al"* diyen bir momentum-faktör motorudur. Tek başına bir **kenar (edge)**
> üretmez; kenarı **çıkışın getiri dağılımını nasıl şekillendirdiği** belirler.

---

## 2. Çıkış A — 10-gün MA Trail (Qullamaggie tarzı)

### Mekanik (`exit_mode="ma_trail"`, `ma_trail_len=10`, SMA)
1. **Felaket stopu:** Gün-içi fiyat ilk plan stopuna (LOW10/ATR) değerse market emriyle çık.
2. **Kısmi kâr:** +2R'ye ulaşınca pozisyonun **%50'sini** sat (limit emri).
3. **Trailing çıkış:** Kapanış **10-gün SMA'nın altına** inince kalanı kapat (MOC).

### Ekonomik yorum
- **Kısa pencereli trend takip = hızlı ortalama-dönüş savunması.** 10g SMA "sıcak" bir
  trail'dir; momentum patlamasının ivmesi kesilir kesilmez çıkar. Bu, **sağ kuyruğu budar**
  (büyük trendleri erken bırakır) ama **dirseği (drawdown'ı) korur**.
- **Opsiyon satıcısı analojisi:** Kazananın bir kısmını +2R'de kilitleyip kalanı sıkı trail'le
  yönetmek, bir **covered-call** gibidir: yukarı potansiyelin bir kısmını "satıp" karşılığında
  **daha yüksek isabet oranı ve daha düşük varyans** (theta benzeri istikrar) alırsın.
- **Yüksek sermaye devri (capital velocity):** Hızlı çıkış → pozisyonlar hızlı serbest kalır →
  daha çok yeni fırsat döndürülür. Aynı dönemde **~502 pozisyon** (630 işlem bacağı) açıldı —
  hibridin iki katından fazla. Sermayenin **yeniden devri** getiriye katkı sağlar.

### Ampirik profil (sp500 · 5y)
- ROI **%117.2** · SPY %97.3 · **Alpha +%19.9**
- MaxDD **−%23.7** · Win **%51.7** · **PF 1.58** · 630 işlem
- Çıkış dağılımı: MA8=354 · PARTIAL=128 · STOP=143 · EOD=5
- **Ort. kazanan +%6.9** (medyan +3.5, max +84) · **ort. kaybeden −%2.7** (medyan −2.6, min −12.3)
- Ödeme oranı (avg win/avg loss) ≈ **2.6** · simetriğe yakın, dar dağılım

---

## 3. Çıkış B — 8-EMA Hibrit (iki kademeli trend takip)

### Mekanik (`exit_mode="tp_grid"`, `tp_mode="HYBRID_TREND"`, kapanış teyitli)
1. **Sabit TP yok.**
2. **İlk %50:** Kapanış **8-EMA**'nın altına inince satılır (hızlı bacak).
3. **Kalan %50 (runner):** Kapanış **21-EMA**'nın altına inince satılır (yavaş bacak).
4. Koruma, 8-EMA kırılımının kendisidir (ilk yarıyı erken boşaltır).

### Ekonomik yorum
- **Konveksite üretimi:** 21-EMA runner, **sağ kuyruğu açık bırakır.** Güçlü trendler
  haftalarca 21-EMA üstünde kalabilir; strateji bu **fat-tail** olaylarını yakalar. Bedeli,
  trend kısa sürerse 8-EMA/21-EMA'nın sık tetiklenip **küçük kayıplar** yazmasıdır.
- **Opsiyon alıcısı analojisi:** Pozitif çarpıklık + yüksek basıklık (kurtosis) ister; tıpkı
  **uzun opsiyon** gibi: çoğu işlemde küçük "premyum" ödersin (düşük isabet), ama nadir
  büyük kazançlar tüm getiriyi taşır. Max kazanan **+%168.8** — dağılımın motoru budur.
- **Düşük devir, yüksek tutma:** Runner sermayeyi uzun tutar → daha az pozisyon (**~244**).
  Sermaye devri düşük ama **işlem başına beklenen değer yüksek**.

### Ampirik profil (sp500 · 5y)
- ROI **%118.9** · SPY %97.3 · **Alpha +%21.6**
- MaxDD **−%21.2** (A'dan iyi) · Win **%38.2** · **PF 2.14** (A'dan belirgin iyi) · 487 işlem
- Çıkış dağılımı: PARTIAL=243 (8-EMA yarısı) · EMA21=239 (runner) · EOD=5
- **Ort. kazanan +%14.8** (medyan +5.5, **max +168.8**) · **ort. kaybeden −%4.0** (medyan −3.3, min −21.5)
- Ödeme oranı ≈ **3.7** · belirgin pozitif çarpık, kalın sağ kuyruk

---

## 4. Yan Yana — Dağılımın Şekli Asıl Hikâye

| Metrik | 10g MA trail (A) | 8-EMA hibrit (B) | Ekonomik okuma |
|---|---|---|---|
| ROI | %117.2 | %118.9 | Net getiri ~eşit |
| Alpha (SPY üstü) | +%19.9 | +%21.6 | İkisi de piyasayı geçti |
| **Max Drawdown** | −%23.7 | **−%21.2** | B daha sığ dip |
| Win oranı | **%51.7** | %38.2 | A çok daha sık haklı |
| **Profit Factor** | 1.58 | **2.14** | B'nin $ kâr/$ zarar oranı çok daha iyi |
| İşlem (bacak) | 630 | 487 | A daha çok döner |
| Pozisyon (~) | ~502 | ~244 | **A 2× sermaye devri** |
| Ort. kazanan | +%6.9 | **+%14.8** | B kazananı koşturur |
| Ort. kaybeden | **−%2.7** | −%4.0 | A kaybı daha erken keser |
| Max kazanan | +%84 | **+%168.8** | B kuyruğu yakalar |
| Ödeme oranı | 2.6 | **3.7** | B daha konveks |
| Getiri çarpıklığı | Düşük (simetriğe yakın) | **Yüksek pozitif** | Farkın özü |

**Aynı motor (qswing), aynı evren, aynı dönem — ama iki ayrı risk dokusu:**
- **A**, kazanma olasılığını yükseltip her işlemin varyansını düşürür → *"sık ve küçük"*.
- **B**, isabeti feda edip sağ kuyruğu satın alır → *"seyrek ve büyük"*.

İki çıkışın ROI'si eşitken **PF ve MaxDD'de B üstün** olması dikkat çekici: B, **birim risk
başına daha verimli** görünüyor (daha iyi $ kâr/zarar oranı, daha sığ dip). A'nın cevabı ise
**daha yüksek isabet + daha hızlı sermaye devri**dir.

---

## 5. Ekonomist Çerçevesi — Hangi Kuram Ne Diyor?

1. **Beklenen fayda & çarpıklık tercihi:** Kahneman–Tversky'nin kayıp-kaçınması altında,
   **A'nın yüksek isabeti** psikolojik olarak daha taşınabilir (sık küçük kazançlar). Ancak
   **B'nin pozitif çarpıklığı**, kuyruk-sevdalı (lottery-seeking) yatırımcı için daha çekicidir
   ve teorik olarak daha yüksek geometrik büyümeye yol açabilir (sağ kuyruk bileşik getiriyi taşır).
2. **Kelly / geometrik büyüme:** B'nin yüksek ödeme oranı (3.7) Kelly kesrini yukarı çeker; ama
   düşük isabet varyansı artırır. A'nın simetrik profili daha düşük optimal kaldıraç ama daha
   pürüzsüz bileşiklenme verir. **Pozisyon boyutu kararı, çıkış seçiminden ayrılamaz.**
3. **Opsiyonellik / theta:** A bir **kısa-vega/kısa-gamma** duruşu gibi davranır (yukarıyı satıp
   istikrar alır); B **uzun-gamma** gibidir (oynaklık patlamalarında — güçlü trendlerde — kazanır).
   Hangisini istediğin, **oynaklık rejimi beklentine** bağlıdır.
4. **Rejim bağımlılığı:** Güçlü, sürekli boğa trendinde (düşük çapraz-kesit dağılımı) **B'nin
   runner'ı** parlar. Çalkantılı/yatay (whipsaw) piyasada **A'nın sıkı trail'i** B'nin sık
   8/21-EMA yanlış kırılımlarından korur. Çıkış seçimi örtük bir **oynaklık bahsidir**.
5. **Sermaye devri & kapasite:** A'nın 2× devri, küçük sermayede daha çok bileşiklenme fırsatı
   demek; ama işlem maliyeti/slipaj (komisyon + 15bps stop slipajı) **A'da daha çok ısırır**
   (iki kat işlem). Büyük sermayede B'nin düşük devri likidite dostudur.

---

## 6. Hangi Durumda Hangisi?

- **10g MA trail'i seç** eğer: yüksek isabet ve pürüzsüz eşitlik eğrisi psikolojik olarak
  şartsa; çalkantılı/yatay rejim bekliyorsan; küçük sermaye + hızlı bileşiklenme istiyorsan;
  işlem maliyetlerin düşükse.
- **8-EMA hibridi seç** eğer: kuyruk yakalamak (birkaç büyük kazananın yılı taşıması) felsefene
  uyuyorsa; daha sığ drawdown ve daha yüksek PF (birim-risk verimi) önceliğinse; güçlü trend
  rejimi bekliyorsan; düşük isabete (sık küçük kayıplara) disiplinle tahammül edebiliyorsan.
- **Hibrit-of-hibrit (öneri/tartışma):** İki çıkışı **birleştirmek** — ör. ilk %50'yi A'nın
  +2R kısmi kuralıyla (kâr kilidi + isabet), kalan runner'ı B'nin 21-EMA mantığıyla (konveksite)
  — her iki dünyanın iyi yönünü harmanlayabilir. Backtest ile test edilmeli.

---

## 7. AI Modelinde Tartışmak İçin Açık Sorular

1. ROI eşitken **PF ve MaxDD'de B üstünse**, neden A'yı seçen biri rasyonel olabilir?
   (İpucu: isabet, sermaye devri, işlem maliyeti, psikoloji, kapasite.)
2. B'nin getirisi birkaç **+%100'lük kuyruk** kazanca mı bağlı? Öyleyse bu, dağılımın
   **kırılganlığı (fragility)** mı yoksa **sağlam konveksite** mi? (En iyi 5 işlemi çıkarınca ne olur?)
3. **Rejim ayrıştırması:** 2020–21 (güçlü trend) vs 2022 (ayı) vs 2023–25 alt-dönemlerinde
   A↔B sıralaması değişiyor mu? Çıkış seçimi gerçekten bir oynaklık bahsi mi?
4. **Pozisyon boyutu etkileşimi:** Kelly/sabit-risk altında B'nin yüksek varyansı optimal
   kaldıracı nasıl değiştirir? Boyut sabitlenince sıralama korunur mu?
5. **İşlem maliyeti duyarlılığı:** Komisyon/slipajı 2×–3× yapınca A'nın yüksek devri avantajını
   kayba mı çevirir?
6. **Birleşik çıkış** (A'nın +2R kısmi kilidi + B'nin 21-EMA runner'ı) PF'yi koruyup isabeti
   yükseltir mi?

---

## 8. Metodoloji ve Uyarılar

- **Motor:** `swing2_backtest.py` (bu repo). Anti-contamination veri hattı (sembol-tek-tek
  indirme, gelecek-bar kesme, SPY takvimine reindex).
- **Veri:** FMP `/stable` günlük EOD, auto-adjust. Evren = sp500 preset (~352 likit isim);
  dönem = 5y.
- **Maliyet:** Komisyon + ~8bps limit / ~15bps market(stop/trail) slipaj dahil; bileşik sermaye.
- **Aynı giriş, aynı evren/dönem** — tek değişken **çıkış**. Karşılaştırma adil.
- **Sınırlar:** Tek dönem/evrenin sonucu; aşırı-uydurma (overfit) ve rejim-bağımlılığı riski
  vardır. Sonuçlar **dağılım şeklini anlamak** içindir, kesin gelecek tahmini değil.
- **Yeniden üret:** 8060 arayüzünde giriş=`qswing`, çıkış=`MA-trail 10g` ve `Hibrit (8-EMA)`
  seç ve aynı evren/dönemle koştur; ya da `/api/backtest`'e
  `{"universe":"sp500","period":"5y","entry_mode":"qswing","exit_strategy":"ma_trail|hybrid"}` POST et.

---

*Üretim: bu repodaki backtest motoru · ekonomist-lens analiz · eğitim amaçlı.*

# 👑 Qulla-21 — Yöntem Spesifikasyonu (LLM tartışma dokümanı)

> **Bu doküman ne için?** Kendi başına yeterli, ayrıntılı bir yöntem tanımıdır.
> Bir LLM'e (ChatGPT, Gemini, Claude, …) olduğu gibi yapıştırıp yöntemi tartışmak,
> eleştirtmek veya iyileştirme fikri üretmek için hazırlandı. Repo'ya erişim
> gerektirmez. **Önemli:** öneri istemeden önce §10'daki *deneysel kanonu* okutun —
> orada listelenen fikirler zaten test edilip elendi; yeniden önerilmeleri zaman kaybıdır.
>
> Eğitim/araştırma amaçlıdır; gerçek para kullanılmaz (kağıt-trade). Yatırım tavsiyesi değildir.

Son güncelleme: 2026-08-20 · Canlı durum: §11

---

## 1. Tek paragraf özet

Qulla-21, Qullamaggie tarzı bir **momentum kırılım** stratejisinin canlı, defter-tabanlı
kağıt-trade uygulamasıdır. Her işlem günü kapanışa ~15 dk kala (**15:45 ET**) çalışır:
~373 büyük ABD hissesinden (S&P 500 + Nasdaq 100) o günün **RS top-50** izleme listesini
kurar; piyasa rejimi açıksa (SPY > SMA200 **ve** havuzun ≥%50'si kendi SMA200'ünün
üstünde) **63 günlük tepe kırılımı** yapan liderleri alır; her pozisyonu **%60 / %40**
ikiye böler — %60'ı **+2R limit hedefte** satılır, %40'ı **21-EMA altına kapanana dek**
tutulan "runner"dır. **Klasik zarar-kes stop YOKTUR** (bilinçli ve dört bağımsız deneyle
doğrulanmış bir karar — §10). Sanal $10.000 ile bileşik büyür; tüm geçmiş kalıcı bir
**defterde kilitlidir** (veri revizyonları geçmişi değiştiremez).

## 2. Veri altyapısı

- Kaynak: **FMP** (Financial Modeling Prep) günlük OHLCV; **split-ayarlı, temettü-ayarsız**.
- Tarih penceresi: göstergeler için ~5 yıl geçmiş.
- **Artımlı depo:** ham barlar yerel bir pkl deposunda birikir; her akşam yalnız yeni
  barlar indirilir, göstergeler depodan taze hesaplanır. Haftada bir tam yenileme
  (sessiz yeniden-ayar güvenlik ağı).
- Korumalar: tek-gün >%40 sıçrama → split şüphesi, o sembol tam yenilenir; benchmark'ın
  gerisinde kalan semboller tek-işçiyle tazelenir; yine geride kalırsa açıkça loglanır.
- Bilinen gerçek: FMP verisi **geriye dönük revize olur** (split/düzeltme/kapsam).
  Ölçülmüş etki: tam depo yenilemesi sonrası aynı motorun taze replay'i, kilitli
  defterden **−2,14 puan** saptı (giriş örtüşmesi %92,5). Defter mimarisinin (§8)
  varlık sebebi budur.

## 3. Evren ve izleme listesi (RS top-50)

- Havuz: S&P 500 + Nasdaq 100 birleşimi, ~373 sembol (**sistematik**; elle seçim yok —
  seçim yanlılığını gidermek için kural tabanlı kuruldu).
- Her gün: `RS = RET60 − SPY_RET60` (60 işlem günü getiri farkı) ile sıralanıp
  **ilk 50** o günün izleme listesi olur. Giriş adayları yalnız bu listeden çıkabilir.
- Borsadan çıkan/veri akışı kesilen semboller doğal olarak listeden düşer (güncel barı
  olmayan sembol aday olamaz).

## 4. Günlük döngü ve zamanlama

- Cron: hafta içi **22:45 ve 23:45 TR** (≈15:45 ET; ikincisi yaz/kış saati emniyeti).
  Pencere dışında koşarsa kendini iptal eder.
- Giriş fiyatı varsayımı: **15:45 ET fiyatı ≈ günün kapanışı.** Gerçek Tiingo intraday
  verisiyle kalibre edildi: fark ~0 bps (haircut ihmal edilebilir).
- Günün barı FMP'de henüz yoksa: **4 deneme × 120 sn** (son sınır 16:20 ET; bar o
  saatte kesinleşmiştir). Yine yoksa **sessiz atlamaz** — Telegram'a uyarı düşer,
  defter o gün kilitli kalır, gün ertesi akşam (veya elle offline) işlenir. Artımlı
  yapı çifte işlemi imkânsız kılar.

## 5. Giriş kuralları (tam kapı listesi)

Bir sembolün o gün alınabilmesi için **hepsi** sağlanmalı:

| # | Kapı | Kural (kesin değer) |
|---|------|---------------------|
| 1 | Rejim | `SPY Close > SPY SMA200` |
| 2 | Genişlik freni (A200) | Havuzdaki sembollerin **≥%50**'sinin `Close > kendi SMA200`'ü (gün ortalaması). Rejim açık olsa bile A200 < 50 → o gün yeni alım yok |
| 3 | İzleme listesi | Sembol o günün RS top-50'sinde |
| 4 | Trend dizilimi | `Close > SMA20` ve `> SMA50` ve `> SMA200` |
| 5 | Eğim | `SMA200` eğimi pozitif (20 barlık pencere, `SLOPE200 > 0`) |
| 6 | **Kırılım** | `Close > önceki 63 işlem gününün en yüksek High'ı` (bugünkü bar hariç — nedensel) |
| 7 | 52H yakınlık | `Close ≥ 0,75 × 52-hafta zirvesi` (zirvenin %25 içinde) |
| 8 | Momentum + RS | `RET60 > 0` ve `RS ≥ 0` (SPY'ı geçiyor) |
| 9 | Hacim kuruması | **KAPALI** (VDU tavanı 9 = etkisiz; ızgara testinde VDU şartı getiriyi düşürdü — kırılım barında hacim patlar) |
| 10 | Skor eşiği | **KAPALI** (`qswing_min_score = 0`; skor yalnız sıralamada kullanılır) |
| 11 | Oynaklık kilidi | ATR-rejim hard-switch mevcut ama **varsayılan kapalı** |

Tüm kurallar her gün her sembol için **nedenseldir** (yalnız o güne kadarki barlar).

## 6. Sıralama ve seçim ("denge" — ⭐ Aday 3)

Kapıyı geçen adaylar kalabalıksa sıralama anahtarı:

```
sıra_anahtarı = qscore/100 + ATR%/10        (eşitlikte: SMA20'ye daha yakın önce)
```

- **qscore (0–100):** Qullamaggie hiyerarşili birleşik öncelik skoru —
  RS **45** puan (RS 60+ → tam) · 52H yakınlık **20** (zirve %0→tam, −%10→0) ·
  tazelik **20** (SMA20'ye ≤%5 → tam, %25→0; kovalamayı cezalandırır) ·
  risk kalitesi **15** (risk ≤%3 → tam, %9→0).
- **ATR%/10:** günlük oynaklık payı — "kalite + hareket" karışımı. Sadece kaliteyle
  sıralamaya göre 5 walk-forward penceresinin hepsinde daha iyi çıktığı için seçildi
  (2026-07-05 "Aday 3" kararı; baz motora yalnız iki fark ekler: bu sıralama + A200 freni).

## 7. Tahsis, slotlar, boyutlandırma

- Sermaye: **$10.000** başlangıç, **bileşik** (poz büyüklüğü güncel özsermayeden).
- **20 slot**; her yeni pozisyon = özsermayenin **%7,5**'i (eşit ağırlık; risk-bazlı değil).
- **Combo kuralı (cash-drag düzeltmesi):** +2R bacağı satılmış, yalnız runner'ı kalan
  pozisyon **slot saymaz** (`free_runner_slots`) — runner'lar koltuk işgal etmez,
  sermaye kullanımı ~%52'den yukarı çıktı. Bilinen bedeli: daha derin drawdown (§11).
- Nakit %7,5'lik pozu karşılamıyorsa yeni alım yapılmaz (kısmi poz açılmaz).
- Komisyon **$1/bacak**; giriş kayması **+8 bps** (kapanışa 5 dk kala spread), market
  çıkış kayması **15 bps**.

## 8. Çıkış — split 60/40, stopsuz

Pozisyon girişte iki bağımsız bacağa bölünür (**ortak felaket stopu YOK**):

- **A bacağı (%60):** `+2R` seviyesinde **limit** satış.
  R tanımı: plan stopu = `max(son 10 günün en düşüğü, Close − 1,5×ATR14)`;
  `R = giriş − plan_stopu`; hedef = `giriş + 2R`. **Dikkat:** bu stop yalnız R'yi
  tanımlar — emir olarak KONMAZ; fiyat altına inse de satış tetiklenmez.
- **B bacağı (%40, "runner"):** fiyat **21-EMA'nın altında kapatana kadar** tutulur;
  kapanış teyidi (gün-içi fitil sayılmaz), ertesi işlem market ile.
- Split oranı 5 walk-forward penceresinde 50/50'ye karşı 5/5 üstün geldiği için
  60/40 seçildi (2026-07-02).

**Stopsuzluk bilinçlidir.** Aşağı yönde tek çıkış runner'ın 21-EMA kuralıdır; A bacağı
hedefe ulaşana ya da (runner çıktıktan sonra bile) süresiz bekler. Bu, sistemin hem en
büyük getiri kaynağı hem de en derin drawdown nedenidir — §10'daki dört bağımsız deney,
her tür stop/timeout/tahliye eklemenin sonucu kötüleştirdiğini gösterdi.

## 9. Gerçek defter mimarisi (geçmiş kilitli)

- Kalıcı defter (JSON) **tek doğruluk kaynağı**: nakit, pozisyonlar (bacak yapısıyla),
  tüm işlemler, gün-gün equity eğrisi.
- İlk kurulumda backtest ile START→bugün bir kez doldurulur, sonra **dondurulur**.
  Her akşam defter motora yüklenir, **yalnız yeni gün(ler)** işlenir. Bir kez işlenen
  gün değişmez; açık pozisyon gerçekten satılana kadar düşmez.
- Her commit **atomiktir** ve önceki durum tarihli yedeğe alınır. Ana defter kayıpsa
  ama yedek varsa sistem sıfırdan başlamayı **reddeder** (fail-closed).
- Split/revizyon koruması: seri yenilenmişse pozisyon adetleri aynı ölçeğe çekilir.
- **Doğrulama kapısı (v2):** yayın/commit öncesi günün giriş/açık/replay-çıkış
  fiyatları bağımsız quote uç noktasıyla çapraz kontrol edilir; %25 üstü ölçek
  sapmasında yayın ve commit durur, Telegram'a KRİTİK uyarı düşer (fail-closed).
- Kod-doğruluğu denetimi de yapısaldır (veri revizyonu ROI paritesini imkânsız kılar):
  taze replay ile giriş-seti örtüşmesi ≥%90 **ve** erken-dönem eğri izlemesi <%0,3 aranır.

## 10. Deneysel kanon — DENENDİ ve ELENDİ (yeniden önermeyin)

Tümü aynı motor, 5 yıl, 5 walk-forward penceresi + **jitter testi** (başlangıç gününü
birkaç gün kaydırınca sonuç ayakta kalmalı) + komşu-parametre kontrolüyle test edildi.

| Fikir | Sonuç |
|-------|-------|
| A bacağına stop veya timeout (13 varyant) | Hepsi bazdan **kötü** — uzun trend kuyruklarını kesiyor |
| Kâr-şartlı break-even / trailing stop (runner) | Grid şampiyonu jitterda çöktü (ort −6p); BE yapısal no-op (21-EMA domine) |
| Alternatif korumalar: RS çöküşü, hacim kırılımı, "giyotin" (dipteki pozu kes) | Hepsi elendi; giyotin jitter testinde 5 başlangıcın 3'ünde kayıp |
| Stopsuz bekleyenleri tahliye / koşulsuz timeout | Kaybettiriyor (timeout ROI korunumu %41); işgalcinin toparlanma opsiyonu koltuğundan değerli |
| Ters-boyutlandırma ("sıçrayana tam kal") | Yön doğru ama aday yok — en iyi varyant komşusuz tepe (overfit imzası) |
| ML sahte-kırılım filtresi (XGBoost, 4.489 örnek) | Walk-forward **AUC ≈ 0,47** — kestirim gücü yok; 6 varyant da negatif |
| VIX şalteri (oynaklıkta risk kes) | Reddedildi |
| Hacim-kuruması (VDU) giriş şartı | Getiriyi düşürdü — kapalı |
| Kalite eşiğiyle tahsis (Giyotin-2) | İlk bakışta jitter geçti, sonra maskesi düştü: 5 yılda yalnız 4 olay (n≈4), statü düşürüldü |

**Atıf teşhisi (neden stop işe yaramıyor):** brüt zararın **%96,3**'ü pozisyon +2R'ye
hiç ulaşmadan oluşuyor; ama kanama zamana dağınık, bilanço günleri payı ≤%9, gece
boşluğu azınlık kanalı — **hedeflenebilir tek bir olay yok**. Kuyruğu üreten isimler
kârı üreten isimlerle aynı; kuyruğu kesen her mekanizma kârı da kesiyor.

**Kabul kriteri (hâlâ yürürlükte):** bir değişiklik ancak 5 pencerenin ≥4'ünde bazdan
iyi + ayı döneminde bozulmuyor + komşu parametrelerde çalışıyor + maliyet/kayma sonrası
avantaj koruyor + **yeni forward dönemde** doğrulanıyorsa canlıya alınır.

**Kabul edilen tek yapısal değişiklikler:** combo (slot boşaltma + %7,5; cash-drag
düzeltmesi) ve Aday 3 (denge sıralaması + A200 freni). İkisi de bu kriterden geçti.

## 11. Canlı sonuç durumu (2026-08-20 itibarıyla)

- Pencere: **2026-05-27 → 2026-08-19** (59 işlem günü). Equity **$9.760,50 (−%2,4)** ·
  aynı dönem SPY ≈ **+%2,5** · yaşanan MaxDD **−%18,4**. 21 açık pozisyon.
- **Beklenti karnesi (2026-08-16):** canlı pencere, 5 yıl içinde her 10 işlem gününde
  bir başlatılan **124 taze-başlangıçlı, aynı-konfig 56 günlük koşuya** karşı yargılandı:
  - ROI yüzdeliği **P55–P63** (dağılımın ortası — kötü bir pencere DEĞİL).
  - Alpha: pencerelerin **%63'ünde alpha ≤ 0** — kısa pencerede SPY'a yenilmek bu
    stratejinin olağan hali; kazanç patlamalı pencerelerden gelir (örn. bir pencerede +%33).
  - **Tek kuyruk bulgu: MaxDD −%18,4 = P99** (koşuların yalnız %1'i daha derin).
    Combo'nun bilinen bedeli; aktif izleme kalemi.
  - Gölge replay: eski yöntemde kalınsaydı ≈$292 daha kötü olurdu (geçiş pişmanlığı yok).
  - **Karar: normal varyans — kurallar değiştirilmedi.**
- Temmuz kaybı (−$1.623) ayrıştırıldı: SPY düzdü (%0,0); kaybın %95'i tutulan 6 derin
  kırmızı isimden — piyasa değil, isim seçimi/tutma kuyruğu.

## 12. Bilinen zayıflıklar ve açık sorular (tartışmaya davet)

1. **MaxDD kuyruğu (P99):** stopsuzluk + combo derin çukur üretiyor. Stop eklemeden
   çukuru yumuşatmanın denenmemiş bir yolu var mı? (Denenenler: §10 — çoğu yol kapalı.
   Metodoloji notundaki açık aday: rejimi ikili kapı yerine %50/%75/%100 **risk çarpanı**
   yapmak — henüz test edilmedi.)
2. **Giriş kalitesi:** zararın %96,3'ü +2R öncesi → tek açık kaldıraç girişte.
   Denenmemiş adaylar: kırılım barının hacmi/kapanış konumu, ATR'ye göre aşırı uzama
   filtresi, aynı-gün kapanış dolumu vs ertesi-gün açılış dolumu kıyası.
3. **Split/runner kombinasyonları:** %40/%60, %50/%50, 8-EMA/21-EMA runner grid'i
   5 pencerede sistematik karşılaştırılmadı (60/40 + 21-EMA mevcut şampiyon).
4. **Sektör/korelasyon yoğunlaşması:** Temmuz kaybının 6 isimden gelmesi (çoğu
   yarı-iletken/donanım) yoğunlaşma sorusunu açık bırakıyor; RS top-50 doğal olarak
   tek temaya yığılabiliyor. Sektör tavanı denenmedi (dikkat: kuyruğu üreten isimler
   kârı üretenlerle aynı — naif tavan getiriyi de kesebilir).
5. **Dağılımın in-sample gölgesi:** 124 koşunun tarihi, Aday 3'ün seçildiği veriyi
   içeriyor → yüzdelikler hafif iyimser olabilir; forward kesit (karar sonrası dönem)
   ayrı izleniyor ama henüz kısa (~30 gün).
6. Operasyonel: NYSE tatil listesi 2027 sonunda bitiyor (bakım borcu); borsadan çıkan
   semboller (delist) evrenden doğal düşüyor ama tutulan bir pozisyon delist olursa
   davranış tanımsız (henüz yaşanmadı).

## 13. Terimler

- **R:** giriş − plan stopu (LOW10 / 1,5×ATR tabanı); pozisyon riski birimi. Stop emri değildir.
- **Runner:** +2R satışından sonra trendi koşturan %40'lık bacak.
- **RS:** 60 işlem günü getirisi − SPY'ın aynı dönem getirisi.
- **A200:** havuzda kendi SMA200'ünün üstünde kapatan sembol yüzdesi (genişlik).
- **Jitter testi:** başlangıç gününü ±birkaç gün kaydırıp sonucun ayakta kalıp kalmadığına bakmak; tek-yol şansını ayıklar.
- **Combo:** %7,5 poz + runner'ın slot saymaması (cash-drag düzeltme paketi).
- **Defter (ledger):** kilitli geçmişli kalıcı işlem kaydı; tek doğruluk kaynağı.

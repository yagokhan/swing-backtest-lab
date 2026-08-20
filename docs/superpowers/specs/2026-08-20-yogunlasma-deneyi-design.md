# Yoğunlaşma Deneyi (tema/korelasyon tavanı) — Tasarım

**Tarih:** 2026-08-20 · **Durum:** Onaylandı (kullanıcı)
**Soru:** Qulla-21'in aynı temaya yığılması (RS top-50'nin doğal sonucu) **ödediğimiz bir prim mi,
yoksa bedava mı?** Yani tema/korelasyon tavanı, kabul kriterinden geçen bir canlı kural adayı mı?

## Nereden çıktı (ölçüm, 2026-08-20)

Bir LLM haber-radarı önerisi değerlendirilirken canlı defter ölçüldü ve öneri **kendi gerekçesini
çürüttü**; ölçüm asıl hedefi gösterdi:

1. **Kayıp gece değil gündüz:** açık pozisyonların tutuş süresi boyunca gece boşlukları net
   **+$401**, gündüz hareketi **−$1.470**. "Gece kötü haber patlıyor" hikâyesi toplamda yanlış.
2. **Kayıp birkaç güne yığılı:** her ismin en kötü 3 günü toplam kaybın **~%103'ü** (−$1.008 /
   −$979). O günler olmasa pozisyonlar aşağı yukarı başabaş.
3. **Şok günlerinin yalnız 2/21'i bilanço günü** = hasarın **%8'i** (2026-07-31 atıf teşhisinin
   ≤%9 bulgusunun bağımsız teyidi → bilanço-kapısı düşük öncelikli).
4. **Şok günleri isimler arasında ORTAK — asıl bulgu:**

   | gün | INTC | LRCX | TER | STX | WDC | GLW | ENPH | SPY |
   |---|---|---|---|---|---|---|---|---|
   | 2026-07-01 | −9,0 | −9,7 | −11,7 | −5,2 | −6,3 | −13,6 | −4,9 | **−0,1** |
   | 2026-07-02 | −5,3 | −10,2 | −13,6 | −10,4 | −9,9 | −10,8 | −8,0 | **−0,1** |
   | 2026-06-23 | −6,1 | −9,3 | −8,1 | −5,1 | −8,4 | −7,5 | −9,9 | −1,5 |

   SPY düz dururken altı-yedi isim aynı anda %5-14 düşmüş. Bu **altı ayrı haber değil, tek tema
   çözülmesi**. Temmuz kaybının %95'inin 6 isimden gelmesi bulgusunun mekanizması bu.

**Sonuç:** kayıp kanalı idiyosinkratik haber değil, **eş-hareketli yığılma**. Radar bu günlerde
şirkete özel haber bulamazdı (doğru şekilde sessiz kalırdı). Ölçülebilir ve **backtest edilebilir**
kaldıraç yoğunlaşmadır.

## Neden etiket değil korelasyon

Birlikte çöken isimlerin endüstri etiketleri **ayrı**: LRCX (yarı-iletken ekipman), WDC/STX
(bilgisayar donanımı), GLW (elektronik bileşen), **ENPH (güneş enerjisi)**. Etiket tabanlı bir
tavan ENPH'yi bu kümeye asla koymazdı. Ayrıca motordaki `SECTOR_MAP` elle yazılmış ve 373 sembolün
yalnız **95'ini** kapsıyor (kullanılamaz). FMP `stable/profile` sector/industry verebilir
(doğrulandı: LRCX → Technology / Semiconductors) ama yukarıdaki kör noktayı çözmez.

**Gerçekleşen korelasyon** veriden ölçülür, etikete muhtaç değildir, temayı olduğu gibi yakalar ve
mevcut depodan (`~/.swing_daily_store.pkl`) hesaplanır → yeni veri kaynağı yok, 5 yıl tam
backtest edilebilir. Etiket varyantı yine de kıyas tabanı olarak test edilir (hipotezi test etmenin
yolu budur), FMP profil etiketleri tek seferlik çekilip cache'lenir.

## Karar kuralı (ön-kayıtlı, kanon standardı)

Bir varyant **ancak** şu beşini birden sağlarsa aday sayılır:
1. 5 walk-forward penceresinin **≥4**'ünde bazdan iyi (baz = mevcut canlı konfig: Aday 3 + combo + 60/40),
2. ayı/düzeltme döneminde bozulmamış,
3. **jitter dayanıklı**: başlangıç ±birkaç gün kaydırılınca (5 başlangıç) ayakta kalıyor,
4. **komşu parametrelerde** de çalışıyor (tek-tepe/zikzak = overfit imzası → RET),
5. maliyet/kayma sonrası avantajını koruyor.

Ana ölçüt **risk-ayarlı**: Calmar ve MaxDD. Yalnız ROI artışı kabul gerekçesi değildir.

**ADAY YOK sonucu geçerli ve beklenen bir sonuçtur** — "yoğunlaşma ödediğimiz prim değil, kârın
kaynağı" cevabı da bilgidir ve yayınlanır.

## Bileşenler

### §1 Motor entegrasyonu
`YogunlasmaBacktester(qp.DengeBacktester)` — `DengeBacktester`'ın `Swing2Backtester`'ı
genişletmesiyle **aynı kalıp**. Tek fark: `_step` içindeki aday listesi sıralandıktan sonra,
`_open` çağrılmadan önce bir **kabul kapısı** uygulanır. Sıralama, kapılar, tahsis, çıkış —
hiçbiri değişmez.

Kritik davranış: aday reddedilince döngü **sıradaki adaya** geçer (sermaye boşta kalmaz). Yani bu
savunma değil, **sahip olunan şeyi değiştiren** bir müdahale; ölçüm bunu içerir.

### §2 Varyant aileleri (ön-kayıtlı grid)
- **K — Korelasyon kapısı:** adayın açık kitaptaki pozisyonlarla 60 işlem günlük günlük-getiri
  korelasyonlarının **ortalaması** ρ'yu aşarsa alınmaz. ρ ∈ {0,50 · 0,60 · 0,70 · 0,80}.
  Kitap boşsa her aday geçer. Yetersiz geçmişi olan sembol (<60 bar) korelasyonsuz sayılır (geçer).
- **E — Etiket tavanı:** FMP endüstri etiketi başına en fazla K açık pozisyon. K ∈ {3 · 4 · 5 · 6}.
  Etiketi bilinmeyen sembol tavana takılmaz (bilinmezlik ceza değil).
- **B — Yumuşak boyut:** reddetme yerine, korelasyon ρ eşiğini aşan adayın pozisyon büyüklüğü
  **yarıya** indirilir (%7,5 → %3,75). ρ ∈ {0,60 · 0,70}. Sert kapının "iyi ismi de kaçırma"
  riskine karşı.

### §3 Yargı protokolü
5 walk-forward penceresi × (baz + 10 varyant) + jitter (5 başlangıç) + komşu kontrol.
Her koşudan: ROI · MaxDD · Calmar · PF · işlem sayısı · **ortalama kitap korelasyonu**
(müdahalenin gerçekten yoğunlaşmayı düşürüp düşürmediğinin teyidi — kapı çalışmıyorsa sonuç
yorumlanamaz).

### §4 Doğruluk sigortaları (fail-closed)
1. **Baz eşdeğerlik kapısı:** kapı devre dışıyken (ρ=1,0 / K=∞) `YogunlasmaBacktester`
   `DengeBacktester` ile **birebir** aynı sonucu vermeli (aynı equity eğrisi). Tutmazsa deney
   YAYINLANMAZ — önce fark teşhis edilir.
2. **Kapı etkinlik kontrolü:** her varyantta ortalama kitap korelasyonu bazdan düşük olmalı;
   değilse kapı fiilen çalışmıyordur → o varyant "no-op" olarak işaretlenir, sonucu sayılmaz.
3. **Salt-okur:** canlı ledger/state/store'a ve `load_market_incremental`'a yazılmaz; deney
   yalnız mevcut depodan okur.
4. Koşu sayısı azaltılırsa açıkça loglanır — sessiz kısıtlama yok.

## Çıktılar
- `yogunlasma_lab.py` (ev dizini, `*_lab.py` geleneği) — `--grid` / `--jitter` / `--rapor`
  alt komutları; ara sonuçlar `~/swing2_out/yogunlasma/*.json` (yeniden koşmadan rapor derlenir).
- `test_yogunlasma_lab.py` — saf fonksiyon testleri (korelasyon penceresi, kapı mantığı, etiket
  sayımı, yumuşak boyut aritmetiği); motor koşusundan bağımsız.
- Chat'te karar özeti + KARAR satırı.
- `/adaylar` sayfasına kendi bölümü — **aday çıksa da çıkmasa da** (dürüstlük defteri geleneği).
- Repo push + bellek kaydı.

## Kapsam dışı
- Canlı konfig değişikliği (deney sonucu ne olursa olsun, bu spec canlıya dokunmaz).
- LLM haber radarı (ölçümle önceliği düştü; ayrı karar — kuyruk sigortası gerekçesi duruyor).
- Bilanço kapısı / `use_earnings` bayrağı (hasarın %8'i → düşük öncelik, ayrı deney).
- Sektör ETF verisiyle hedge/nötrleştirme (yeni mimari, kapsam dışı).

## Riskler
- **Kanon riski (ana risk):** kuyruğu üreten yoğunlaşma, kârı üreten yoğunlaşmanın kendisi olabilir
  (Mart→Haziran'daki +%33'lük pencere de muhtemelen aynı tema yığılmasından geldi). Kapı kuyruğu
  keserken kârı da kesebilir → ADAY YOK sonucu olasılığı yüksek.
- **Süre:** 5 pencere × 11 konfig × jitter → dakikalar-saatler. Market bir kez yüklenir; aşarsa
  jitter yalnız finalist varyantlara uygulanır (loglanır).
- **In-sample gölgesi:** 5y tarih canlı kuralın seçildiği veriyi içerir → sonuçlar hafif iyimser
  olabilir; kabul kriterinin "yeni forward dönemde doğrulanma" şartı bu yüzden korunur.
- **Korelasyon penceresi seçimi:** 60 gün RS penceresiyle hizalı seçildi; farklı pencere farklı
  sonuç verebilir → komşu kontrolünde 40/90 gün de bakılır.

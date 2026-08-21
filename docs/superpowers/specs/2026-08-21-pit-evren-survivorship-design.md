# Point-in-Time Evren — Survivorship Bias Ölçümü (2026-08-21)

## Soru

Qulla-21 statik bir `sp500_ndx` listesi (373 sembol) üzerinde koşuyor. Bu liste
**bugünün** üyelerinden oluşuyor. 2021-2026 arasında batan ya da satın alınan
şirketler evrende hiç yok:

SIVB (battı 2023-03) · FRC (battı 2023-05) · ATVI · SGEN · ABMD · TWTR · VMW ·
SPLK · XLNX · CERN · CTXS · ZNGA · MXIM · PBCT · DISCA

Backtest onları hiç alamadı → hiç kaybetmedi. **Stopsuz** bir sistemde
([[swing2-splitstop-deney]], 4 kez teyit edildi) bu ölçülmemiş bir kuyruk riski:
delist olan pozisyondan çıkış mekanizması yok.

Ölçülecek: **hayatta kalma yanılgısı geçmiş sonuçları ne kadar şişirdi?**

## FMP plan gerçeği (2026-08-21'de ölçüldü, varsayılmadı)

| Uç nokta | Sonuç |
|---|---|
| `api/v3/delisted-companies` | **403** — v3 planda tamamen kapalı |
| `stable/delisted-companies?page=0` | OK — 100 kayıt |
| `stable/delisted-companies?page>=1` | **402** — sayfalama paywall |
| `stable/historical-sp500-constituent` | **402** — PIT üyelik yok |
| `stable/batch-eod`, `eod-bulk`, `batch-quote` | **402** |
| `stable/stock-list` | OK — 38.756 sembol |
| `stable/actively-trading-list` | OK — 26.247 sembol |
| `stable/historical-price-eod/full` | OK — **ölü tickerlar dahil** |

Erişilebilen delist listesi yalnız **2026-08-03 sonrasını** kapsıyor ve çoğu
ETF/SPAC → 2021-2026 ölülerini sayamaz.

**Çözüm:** delist listesine gerek yok. `stock-list` ölüleri zaten içeriyor
(16/16 doğrulandı) ve fiyat geçmişleri tam olarak delist gününde bitiyor.
Havuz oradan kurulur, evren GÜNLÜK maskeyle belirlenir.

## Tasarım

### Evren (Point-in-Time, look-ahead'siz)

Havuz = `stock-list` − `etf-list` − şekil-dışı ticker (`^[A-Z]{1,5}$`) = **31.338**.

Günlük uygunluk maskesi — tamamen vektörel, for-loop yok:

| Şart | Değer |
|---|---|
| fiyat | `Close >= $10` |
| likidite | 20g `SMA(Close×Volume) >= $50M` |
| bütünlük | o gün işlem görmüş (Close, Volume NaN değil) |
| geçmiş | `>= 200` bar (SMA200 hesaplanabilir) |

**Maskenin tamamı `shift(1)`.** Bir günün uygunluğu yalnız önceki günlerin
verisiyle belirlenir — fiyat eşiği dahil (Qulla 15:45'te işlem yapıyor, o anda
günün kapanışı kesin değil). Look-ahead yapısal olarak imkânsız.

Doğum (IPO) ve ölüm (delist) ayrı bir mekanizma gerektirmez: hisse ölünce barı
kalmaz → "işlem görmüş" şartı düşer → maske eler.

### Kollar (etkileri AYIRMAK için)

Dolar-hacmi evreni yalnız yanlılığı düzeltmez, **evren tanımını da değiştirir**
(373 → binlerce). Prova koşusu bu etkinin devasa olduğunu gösterdi
(BAZ 166,3% → PIT-SAG 28,0%), yani tek koşuyla ölçülürse survivorship etkisi
evren değişiminin altında kaybolur.

| Kol | Evren | Ölçtüğü |
|---|---|---|
| **BAZ** | statik sp500_ndx (373), sabit cache | çıpa — `ag.EXPECTED` ile birebir |
| **BAZ-kontrol** | aynı havuz, **taze indirme + vektörel yol** | veri kaynağı/takvim farkı |
| **BAZ+ÖLÜ** | aynı havuz **+ o dönem ölen büyük isimler** | ← **ASIL CEVAP**: saf yanlılık |
| **PIT-SAG** | PIT dolar-hacmi evreni, yalnız yaşayanlar | evren tanımı değişiminin etkisi |
| **PIT-TAM** | PIT evreni, ölüler dahil | geniş evrende yanlılık |

**BAZ+ÖLÜ neden asıl cevap:** kullanıcının sorusu "Qulla-21 gerçekten koştuğu
evrende ne kadar şişmişti?" — evreni değiştirerek değil, yalnız eksik ölüleri
ekleyerek ölçülür. Eklenen ölüler havuzun likidite sınıfında olmalı (küçük
spekülatif çöp değil), bu yüzden eşik verisel: mevcut 373'lük havuzun tepe-ADV
dağılımının P25'i.

**BAZ+ÖLÜ, BAZ ile değil BAZ-kontrol ile kıyaslanır.** İkisi de taze indirmeden
ve 2020-05-01 takviminden kurulur; aralarındaki tek fark ölülerdir. Doğrudan
BAZ'a kıyaslamak, veri kaynağı farkını ölü etkisine yazmak olurdu.

### Pencere hizalaması (kıyaslanabilirliğin ön şartı)

`ag.MARKET` (sabit cache) **2026-07-01**'de bitiyor, taze PIT indirmesi
**2026-08-20**'de. `ag.WINS`'teki boş bitiş "takvimin sonuna kadar" demek →
PIT kollarına 35 işlem günü fazla verirdi ve fark evrenden mi takvimden mi
geldiği anlaşılmazdı. Boş bitişler açıkça `WIN_END = 2026-07-01`'e sabitlendi.

### Sabit tutulanlar (karışan değişken olmasın)

- **Motor**: `altguard_lab.GKX` (Aday 3). Evren tamamen `market["watchlist"]`
  üzerinden enjekte edilir; giriş/çıkış kuralları değişmez.
- **A200 piyasa freni**: her kolda aynı statik `breadth.pkl`. Yeni evrenden
  yeniden hesaplansaydı rejim freni de değişir, sonuç yorumlanamazdı.
- Takvim, sermaye, slot sayısı, boyutlandırma: aynı.

## Yol boyunca kapatılan iki gerçek açık

### 1. Delist çözümü (deneyi geçersiz kılardı)

Baz motor `if pd.isna(low) or pd.isna(high): continue` diyor. Tüm evren
yaşıyorken zararsızdı. Ölüler girince iki yönde birden bozuyor:

- **Hayalet slot**: SIVB Mart 2023'te ölür, pozisyon 2026'ya kadar slot işgal
  eder → PIT-TAM'a haksız nakit-sürüklemesi cezası ([[swing2-cashdrag-combo]]).
- **Geç çıkış**: satın alma da iflas da "pencere sonunda son fiyattan sat".

Eklenen kural **nedenseldir**: `DELIST_GAP=5` seans üst üste bar yoksa son
geçerli kapanıştan çıkılır. "Gelecekte bar var mı" bilgisi KULLANILMAZ.

İflas/satın alma ayrımı için FMP'de kullanılabilir veri yok
(`mergers-acquisitions` yalnız son 100 kayıt, arama 402). Bu yüzden ölçülebilir
bir fiyat imzası kullanılıyor — **satın alma primle biter, iflas çöküşle**:

    haircut = %100  eğer  252g zirvesinden düşüş <= -%60  VE  son 5 gün <= -%30
    haircut = %0    aksi hâlde (son fiyattan nakde çıkış)

**Bilinen 19 vakayla doğrulandı:**

| Grup | Sonuç |
|---|---|
| Satın almalar (ATVI, SGEN, ABMD, VMW, SPLK, XLNX, CERN, CTXS, ZNGA, MXIM, PBCT, TWTR, BKI) | **13/13 doğru** — hepsi anlaşma fiyatından nakit çıkış |
| SIVB (işlem $106'da durdu, hissedar $0 aldı) | **yakalandı** — sıfırlandı |
| FRC ($0,34), RAD ($0,25) | kural "nakit" diyor ama **ekonomik olarak doğru**: zaten sıfıra yakın işlem görmüşler, haircut gereksiz |

Yani haircut'ın gerçekten fark yarattığı tek desen **SIVB tipi halt-at-price**
(fiyat anlamlıyken işlem durur, hissedar sıfır alır) ve kural onu yakalıyor.
Yine de üç kol birden raporlanır: %0 / auto / %100.

**Ticker geri dönüşümü kontrol edildi:** BBBY, SBNY, AMTD bugüne kadar kesintisiz
seri veriyor — delist olmamışlar, OTC'de kuruşlara düşerek işlem görmeye devam
etmişler (BBBY $4,28 · SBNY $0,14 · AMTD $0,83). 45 gün+ boşluk YOK, yani iki
şirketin serisi birbirine yapıştırılmamış. Stopsuz sistemin böyle bir ismi %99
düşerken taşıması gerçek davranıştır, artefakt değil — ölçülmesi gereken şeyin
ta kendisi.

**Doğrulandı: BAZ kolunda no-op** — 5/5 pencerede `EXPECTED` birebir, delist=0.
Yani üç kolda da aynı motor koşuyor.

### 2. Veri kalitesi (sonuç-tarafsız olmak zorunda)

31 bin sembollük havuzda ters split ve düzeltilmemiş kurumsal işlem var
(`BBIG` 70, `ALFIQ` 38, `AFMDQ` 23 bozuk bar). Tek sahte ×10 sıçrama momentum
motorunda sahte kırılım + sahte kazanan üretir ([[swing2-glitch-guard]]).

**Reddedilen ölçüt:** "tek günde %40'tan fazla oynayanı at" → sembollerin
%42'sini vurur **ve iflasları siler**, yani survivorship bias'ı arka kapıdan
geri sokar. Tam da ölçmek istediğimiz şeyi silmiş oluruz.

**Kullanılan ölçüt (yönden bağımsız):** gidiş-dönüş sıçraması — fiyat bir gün
≥1,6× fırlayıp ertesi gün geri iniyorsa (ya da tersi), bu fiyat hareketi değil
bozuk bardır. Gerçek çöküş geri gelmez, gerçek ralli ertesi gün yarıya inmez.
Havuzun ~%4'ünü eler; iflas da satın alma da korunur. Süzgeçsiz varyant da
koşulur.

## Sadakat kapıları (fail-closed)

1. **Vektörel == orijinal**: `build_watchlist_fast`, `rs_universe.build_watchlist`
   ile 373 sembol × 1543 günde **birebir aynı küme**. ✅ 1543/1543
   (144,54s → 0,92s, **157×**). Bu vektörleştirme süs değil: 4000 sembolde
   orijinal saatler sürerdi.
2. **BAZ çıpası**: `ag.EXPECTED` ile 5/5 birebir. ✅
3. **Birim testler**: 18/18, içinde look-ahead'in yapısal kanıtı — geleceği
   değiştir, geçmiş maske bit-bit aynı kalır (`test_maske_gelecege_bakmaz`,
   `test_rs_matrix_gelecege_bakmaz`).
4. **İndirme**: hata oranı >%2 → durur. FMP 429 için uyarlanır hız sınırlayıcı
   (AIMD), checkpoint ile devam.

## Dosyalar

- `pit_universe.py` — havuz, hız sınırlayıcı, vektörel maske + RS, glitch süzgeci
- `pit_download.py` — checkpoint'li indirme
- `pit_lab.py` — üç kol + delist çözümü + adli tıp
- `test_pit_universe.py` — 18 test

## Canlı sisteme etkisi

**YOK.** Defter, state, `qulla_paper` okunmaz/yazılmaz. Yeni cache dosyaları
(`pit_pool.json`, `pit_frames.pkl`, `pit_etfs.pkl`) dışında hiçbir şeye
dokunulmaz. Motor dosyaları (`swing2_backtest.py`, `rs_universe.py`)
değiştirilmedi.

---

# SONUÇLAR (2026-08-21)

## Veri

31.338 sembol tarandı · **3.741 tutuldu** (26.912'si $50M eşiğini hiç görmediği
için anında budandı, 686 boş) · **0 hata** · 9 kez 429 (uyarlanır sınırlayıcı
emdi) · 121 dakika · 139 MB. Glitch süzgeci 166 sembol attı → **3.575 kullanıldı**
(yaşayan 2.772 · delist/satın alınmış 803). BAZ havuzu kapsamı **373/373**.

## Ana tablo (5y tam, 2021-05-01 → 2026-07-01)

| Kol | evren | ROI | MaxDD | Calmar | PF | işlem |
|---|---|---|---|---|---|---|
| BAZ (çıpa) | 373 | 166,3% | −19,6% | 8,48 | 3,67 | 482 |
| BAZ-kontrol | 371 | 201,5% | −19,6% | 10,30 | 3,96 | 510 |
| BAZ+ÖLÜ (gerçekçi) | 437 | 189,7% | −19,8% | 9,59 | 3,49 | 511 |
| BAZ+ÖLÜ (iflas ucu) | 437 | 122,3% | −22,8% | 5,37 | 2,11 | 497 |
| PIT-SAG | 1413 | 37,7% | −26,6% | 1,42 | 1,36 | 288 |
| PIT-TAM | 1619 | 21,9% | −29,8% | 0,73 | 1,22 | 289 |

## BAZ ≠ BAZ-kontrol: +35,2 puan — ısınma payı, ölü etkisi DEĞİL

Kontrol kolu tam da bunun için vardı. Fark **açıklandı ve doğrulandı**:

`ag.MARKET` cache'i 2020-05-11'de başlıyor → 2021-05-01'e kadar **246 bar**.
`HIGH52` 252 bar istiyor, `_qswing_entry_ok` HIGH52 NaN ise giriş vermiyor →
**BAZ, 5y penceresinin ilk 7 seansında hiç işlem açamıyor** (HIGH52 ilk geçerli
gün: 2021-05-10). PIT indirmesi 2020-05-01'de başladığı için 252 barı var.

Kanıt: 2023 ve sonrasında başlayan üç pencere **birebir aynı** (43,3 · 81,3 ·
57,4); yalnız 2021-05-01'de başlayan ikisi ayrışıyor.

→ Doğrudan BAZ'a kıyaslasaydık bu 35 puanı ölü etkisine yazacaktık. **Yanlılık
her zaman BAZ-kontrol ile ölçülür.**

Yan bulgu: `ag.EXPECTED`'in 5y rakamı, ilk ~7 günü yapısal olarak işlemsiz olan
bir pencerede ölçülmüş. Canlı sistemde sorun değil (tam geçmiş var), ama lab
çıpasının bilinmesi gereken bir özelliği.

## ASIL CEVAP: yanlılık gürültünün ALTINDA

Tek başlangıçta manşet **−11,8 puan** görünüyordu. Jitter bunu çürüttü:

| başlangıç | kontrol | +ölü | fark | iflas ucu |
|---|---|---|---|---|
| 2021-05-01 | 201,5% | 189,7% | **−11,8p** | −79,2p |
| 2021-05-11 | 118,9% | 203,2% | **+84,3p** | −28,2p |
| 2021-05-21 | 138,8% | 153,0% | **+14,2p** | −39,7p |
| 2021-06-01 | 158,3% | 163,7% | **+5,4p** | −61,0p |
| 2021-06-11 | 153,5% | 204,0% | **+50,5p** | −36,2p |

Ortalama **+28,5p** · aralık **−11,8 … +84,3p** · **5'te 4'ü POZİTİF**.

Başlangıcı 10 gün kaydırmak işareti çeviriyor ve büyüklüğü ~96 puan savuruyor.
Kontrolün kendisi de 118,9-201,5 arasında (82,6 puan) geziniyor. **Ölü isimleri
eklemenin etkisi, sistemin kendi yol-bağımlılığından küçük.** Rapor edilebilir
bir yanlılık büyüklüğü YOK.

Bu, [[swing2-yogunlasma-deneyi]] ve [[swing2-tahsis-deney]] deseninin üçüncü
tekrarı: tek başlangıçtaki manşet jitter'da buharlaşır.

## NEDEN: ölüler iflas etmedi, SATIN ALINDI

9 delist çıkışının **9'u da "nakit"** — auto sınıflandırıcı bir kez bile
sıfırlanma bulmadı:

| tarih | sembol | son fiyat | P&L |
|---|---|---|---|
| 2021-12-20 | KSU | $293,59 | −6,4% |
| 2023-10-16 | HZNP | $116,30 | +2,1% |
| 2023-12-11 | OSTK | $22,69 | −35,3% |
| 2024-03-25 | SPLK | $156,90 | +3,7% |
| 2025-04-09 | ITCI | $131,87 | +2,9% |
| 2025-10-09 | BYON | $11,75 | −0,1% |
| 2025-10-10 | VRNA | $106,79 | +9,8% |
| 2026-03-24 | CFLT | $30,99 | −21,1% |
| 2026-05-06 | ACLX | $115,07 | +7,9% |

**Ölü isimlerin net katkısı +$22.253 / toplam +$189.726 = kârın %11,7'si.**
İşlem gören 26 ölü sembolün çoğu kazandırdı (X, MRO, SKLZ, SPLK, BECN, GTLS,
ITCI, VRNA, ACLX); kaybettirenler OSTK −$2.495 ve CFLT −$1.845.

Sebep basit: 2021-2026'da S&P500/NDX'ten ayrılanlar ağırlıklı olarak **primli
satın almalarla** ayrıldı. Momentum sistemi için satın alma bir KAZANÇTIR —
yükselen bir isim primle nakde çevrilir. Yanlılığın beklenen yönü tersine döndü.

**Kuyruk riski yine de gerçek ama koşullu:** her delist tam kayıp sayılırsa
(iflas ucu) fark 5/5 negatif, ortalama **−49 puan**. Yani SIVB tipi bir
"fiyat anlamlıyken işlem durur, hissedar sıfır alır" olayı portföye girerse
bedeli büyük. Bu pencerede olmadı — ama sistemde bunu karşılayan bir mekanizma
da yok.

## ASIL KUYRUK BURADA DEĞİLDİ

PIT-TAM'ın en kötü 8 işleminin **hepsi "EOD"** — pencere sonunda hâlâ açık
pozisyonlar — ve **hiçbiri ölü değil**:

| sembol | tutuş | P&L |
|---|---|---|
| ERNA | 2021-05-03 → 2026-07-01 | **−100,0%** |
| LCID | 2021-11-16 → 2026-07-01 | −98,8% |
| ANVS | 2021-07-06 → 2026-07-01 | −98,1% |
| SPT | 2021-09-23 → 2026-07-01 | −94,5% |
| AVXL | 2021-06-28 → 2026-07-01 | −91,1% |
| BILL | 2021-11-05 → 2026-07-01 | −88,4% |
| QMCO | 2024-12-26 → 2026-07-01 | −83,8% |

BAZ evreninde bile aynı desen: PAYC 2021-10-14'ten 2026-07-01'e **−74,5%**.

Yani stopsuz sistemin ölçülmemiş kuyruğu **delist değil, yaşayan kaybedeni
yıllarca taşımak**. Bu aynı zamanda PIT-TAM'ın 5y penceresinde delist=0
olmasını açıklıyor: slotlar zombi pozisyonlarla dolu, portföy dönmüyor, hiçbir
ismi delist anında taşımıyor. [[swing2-cashdrag-combo]] ve
[[swing2-bekleyen-deney]] ile aynı mekanizma.

## EN BÜYÜK ETKİ: evren tanımı (−128,6 puan)

| | ROI |
|---|---|
| BAZ (sp500_ndx, 373) | 166,3% |
| PIT-SAG ($10/$50M taraması, günlük ort. 910 uygun) | **37,7%** |

Statik listeden saf likidite taramasına geçmek 5 yılda **−128,6 puan**.
MaxDD −19,6 → −26,6, Calmar 8,48 → 1,42.

**Bu, deneyin en pratik bulgusu:** Qulla-21'in kenarının önemli bir kısmı
evrenin KALİTESİNDEN geliyor. S&P500/NDX üyeliği kendi başına bir kalite
süzgeci (kârlı, kurumsal, oturmuş şirketler); $10 fiyat + $50M hacim eşiği bunu
taklit etmiyor — spekülatif orta/küçük ölçeği içeri alıyor ve stopsuz sistem
onları sıfıra kadar taşıyor.

## KARAR

**Değişiklik YOK.** Ne Point-in-Time dolar-hacmi evrenine geçilir (−128,6 puan),
ne de mevcut evren "düzeltilmiş" sayılır.

Kayda geçen üç şey:
1. Qulla-21'in geçmiş sonuçları **ölçülebilir biçimde şişkin değil** — ölü
   isimler eklendiğinde sonuç gürültü içinde kalıyor, üstelik 5'te 4'ü pozitif.
2. Sistemin gerçek kuyruk riski delistte değil, **stopsuz taşınan yaşayan
   kaybedende**. Bilinen dosya ([[swing2-splitstop-deney]]) bir kez daha teyit.
3. Evren kalitesi bir parametre değil, **kenarın kaynağı**. Evreni genişletme
   önerileri bu −128,6 puanı aşmak zorunda.

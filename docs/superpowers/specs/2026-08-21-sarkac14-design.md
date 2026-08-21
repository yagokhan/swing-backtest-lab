# 🔔 Sarkaç-14 — QQQ'nun RSI salınımıyla TQQQ al-sat (2026-08-21)

## Yöntem

Sinyal **QQQ**'dan, işlem **TQQQ**'da:

    RSI(QQQ, 14) <= 30  →  TQQQ AL
    RSI(QQQ, 14) >= 70  →  TQQQ SAT

Aradaki barlarda işlem yok. Pozisyon ya tam açık ya tamamen nakit; kaldıraç
TQQQ'nun kendi 3× yapısından gelir, ayrıca kaldıraç kullanılmaz.

Kaynak: BalintDavid "RSI Swing Indicator" (Pine v4, MPL-2.0). Göstergenin çizim
kısmı (HH/LH/HL/LL etiketleri, salınım çizgileri) alım-satımı etkilemediği için
taşınmadı; taşınan şey **durum makinesidir**.

### Pine durum makinesi (birebir korundu)

`laststate` son aşırılığı tutar (1=aşırı alım, 2=aşırı satım) ve yeni salınım
YALNIZ durum değişiminde üretilir:

    if (laststate == 2 and isOverbought)   → yeni tepe
    if (laststate == 1 and isOversold)     → yeni dip

Bu kontroller durum güncellenmeden ÖNCE çalışır, yani **önceki barın** durumuna
bakar → histerezis. Arka arkaya gelen aşırı-satım barları tekrar sinyal üretmez.
Alım-satıma çevirisi doğal alternans: al → sat → al → sat.

**İlk işlem farkı:** Pine'da `laststate` 0'dan başlar, katı okumada ilk aşırı
satım ALIM ÜRETMEZ. İkisi de kuruldu: `start_mode="pine"` (katı) / `"flat"`
(nakitken ilk aşırı satım da alır, varsayılan).

### Zamanlama ve maliyet

RSI kapanışta bilinir, işlem kapanışta yapılır (Qulla-21'in 15:45 konvansiyonu).
Gelecek bar kullanılmaz. Maliyet: $1/işlem + giriş 8bps / çıkış 8bps.

### RSI doğruluğu

TradingView `ta.rsi` Wilder yumuşatması kullanır ve `ta.rma`'yı ilk n değerin
SMA'sıyla tohumlar; `swing2_backtest.rsi()` ise saf `ewm` (tohum yok). Bu lab TV
yolunu uygular (`rsi_tv`). Üç yönlü doğrulandı: elle Wilder hesabıyla **birebir
(0,0000)**, mevcut motor RSI'ıyla 2010 sonrası **maks fark 0,00000000**, aralık
0-100.

Yol boyunca bir hata bulundu ve düzeltildi: `rma()` baştaki NaN'ı atlamıyordu →
`close.diff()`'in ilk elemanı NaN olduğu için 14 değişim yerine 13'ünün
ortalamasını alıp tohumu bir bar erken yerleştiriyordu. Sonuçlara etkisi yok
(yakınsama nedeniyle) ama düzeltildi; test `test_rsi_ilk_n_bar_nan` bekçisi.

## SONUÇLAR (2010-02-11 → 2026-08-20, TQQQ'nun tüm ömrü)

|  | ROI | CAGR | MaxDD | **CAGR/DD** | Sharpe | işlem | piyasada |
|---|---|---|---|---|---|---|---|
| 🔔 Sarkaç-14 | +3.196,5% | 23,6% | −74,9% | **0,31** | 0,70 | 17 | %30 |
| TQQQ al-tut | +32.458,1% | 41,9% | −81,8% | **0,51** | 0,88 | 1 | %100 |
| QQQ al-tut | +1.526,5% | 18,4% | −35,6% | **0,52** | 0,92 | 1 | %100 |

**Kıyas CAGR/DD sütunundan yapılır.** ROI/MaxDD çok yıllı bileşikte yanıltıcıdır
(ROI kümülatif, MaxDD tek olay) — 16 yılda ROI/DD "42,65" gibi anlamsız bir sayı
üretir.

**Yöntem her iki kıyası da risk-ayarlı olarak KAYBEDİYOR** (0,31 vs 0,51/0,52),
üstelik Sharpe'ta da (0,70 vs 0,88/0,92). Ham getiride QQQ'yu geçiyor ama bunu
iki katı çukurla yapıyor.

### Dönemler — dördünde de TQQQ al-tut'un altında

| dönem | Sarkaç | TQQQ al-tut | QQQ al-tut | Sarkaç DD |
|---|---|---|---|---|
| 2010-2015 | +509,6% | +999,4% | +155,9% | −34,8% |
| 2016-2019 | +226,8% | +382,6% | +94,0% | −50,1% |
| **2020-2022** | **−52,6%** | −23,9% | +23,1% | −74,9% |
| 2023-bugün | +124,2% | +732,3% | +168,6% | −42,2% |

2020-2022 kritik: "aşırı alımda sat" kuralının işe yaraması gereken tek dönemde
yöntem al-tut'tan **daha kötü** yaptı.

### Kuyruk: tek işlem

2022-01-21'de RSI 26,6'da alındı, RSI 70'e ancak **2023-02-02'de** değdi —
**259 bar, −%52,6, −$163.000**. Toplam net kâr $319.665, kazançların toplamı
$483.769 → bu tek işlem kazançların **%34'ünü** götürdü.

17 işlemin 15'i kazançlı (%88 isabet). Yüksek isabet + felaket kuyruğu: stop
olmadığı için aşırı-satımda alıp ayı piyasasının tamamını taşıyor.

### Parametre duyarlılığı — kararsız

12 kombinasyonda CAGR **%0,0 ile %24,7** arasında savruluyor. `(21,25,75)` ve
`(21,20,80)` **hiç işlem üretmiyor**. En iyi CAGR/DD `(14,65,35)` ile 0,37 —
yine al-tut'un 0,51'inin altında. 17 işlemlik örnekte tek parametre seti kanıt
değildir.

## Dashboard

`backtest.html`'e **yöntem seçici** eklendi (👑 Qulla-21 / 🔔 Sarkaç-14).
Sarkaç seçilince evren alanları gizlenir, RSI parametreleri (uzunluk / aşırı alım
/ aşırı satım / başlangıç kuralı) açılır. İstek `POST /api/sarkac` →
`sarkac_lab.run_api()`.

Yanıt sözleşmesi Qulla-21 ile **aynı** (config/metrics/equity/monthly/trades) —
render kodu ortak. Üç fark: kıyas çizgisi SPY değil **TQQQ al-tut**, risk ölçütü
**CAGR/DD**, çıkış dağılımı yerine sinyal/maruziyet özeti.

## Dosyalar

- `sarkac_lab.py` — RSI (TV-birebir), Pine durum makinesi, motor, rapor, API
- `test_sarkac_lab.py` — 17 test (look-ahead kanıtı dahil)
- `server.py` — `/api/sarkac` rotası
- `backtest.html` — yöntem seçici + Sarkaç render'ı
- çıktı: `swing2_out/sarkac_results.json`

## Canlı sisteme etkisi

**YOK.** Qulla-21 defteri/state'i/motoru değişmedi; Sarkaç ayrı dosyada, kendi
verisini çekiyor, kendi cache'ini kullanıyor. Dashboard'da yalnız yeni bir
seçenek.

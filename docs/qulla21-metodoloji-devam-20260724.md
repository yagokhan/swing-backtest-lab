# Qulla-21 metodoloji bulguları ve devam notu

Tarih: 2026-07-24

## Amaç

Bu not, Qulla-21'i yapısal/operasyonel değil, **daha kârlı hale getirme yöntemi** açısından incelemek için oluşturuldu. Canlı kural bu çalışma sırasında değiştirilmedi.

## Ana bulgu

Mevcut deney raporunda zararların %94,3'ünün işlem +2R'ye ulaşmadan oluştuğu görülüyor. Bu nedenle ana kaldıraç A-leg stopunu değiştirmek değil; giriş kalitesi, giriş zamanlaması ve pozisyon riskinin rejime göre ayarlanmasıdır. Stop/timeout varyantları uzun trend kuyruklarını kestiği için çoğunlukla bazdan kötü sonuç verdi.

## Mevcut deneylerden sayısal özet

| Varyant | Ortalama ROI | Ortalama PF | Ortalama DD | Karar |
|---|---:|---:|---:|---|
| Qulla canlı baz | %55,8 | 1,42 | -%16,9 | Referans |
| ATR full 2.5 | %81,5 | 2,28 | -%15,6 | Umut verici, doğrulama gerekli |
| ATR full 3.0 | %80,5 | 2,50 | -%15,4 | Umut verici, doğrulama gerekli |
| ATR 3.25 + 63g breakout | %115,8 | 3,98 | -%14,7 | Yüksek overfit riski |

Bu rakamlar mevcut/aynı veri evrenindeki deneylerden gelir; tek başına canlı kural değişikliği gerekçesi değildir.

## Öncelikli deney sırası

1. Breakout hacmi, kapanış konumu ve ATR'ye göre aşırı uzamayı giriş filtresi olarak test et.
2. Aynı gün kapanış dolumu ile sonraki açılış dolumunu; kayma ve komisyonla karşılaştır.
3. A200/SPY rejimini ikili kapı yerine %50/%75/%100 risk çarpanı olarak test et.
4. %40/%60, %50/%50, %60/%40 split ve 8EMA/21EMA runner kombinasyonlarını 5 pencerede karşılaştır.
5. RS top-N, skor eşiği ve sektör/korelasyon yoğunlaşmasını önceden tanımlı grid ile test et.

## Kabul kriteri

Bir aday yalnızca 5 pencerenin en az 4'ünde bazdan iyi, ayı döneminde bozulmamış, komşu parametrelerde de çalışan, maliyet/kayma sonrası avantajını koruyan ve yeni forward dönemde doğrulanan bir sonuçsa dikkate alınacak.

## Çalıştırma durumu

2026-07-24'te yeni Faz-B bataryası başlatıldı; FMP veri kaynağı cevap vermediği için güvenli biçimde durdu. Eksik veriyle sonuç üretilmedi. Yeni tmux oturumunda önce veri erişimi doğrulanmalı, ardından:

```bash
cd /home/gokhan/claude-workspace/qulla21-fundamental-lab
python3 exp_swing2.py phaseB
python3 exp_swing2.py phaseC
python3 exp_swing2.py phaseD
```

Sonuç CSV'leri `/home/gokhan/swing2_out/exp_*_results.csv` altına yazılır. Canlı Qulla-21 kuralı, bağımsız doğrulama tamamlanmadan değiştirilmemelidir.

## Güncelleme (2026-08-20)

Bu nottan sonra yapılan çalışmaların özeti (ayrıntı: `/adaylar` sayfası):

- **Deney 10–12 (2026-07-31):** atıf teşhisi (+2R-öncesi pay %94,3 → **%96,3**'e
  netleşti), ters-boyutlandırma ve bekleyen-tahliye bataryaları. Üçünde de **aday
  çıkmadı**; boyutlandırma, tahsis ve atıf dosyaları kapandı. Giyotin-2'nin +200
  manşetinin 5 yılda 4 olaya dayandığı görüldü (statü düşürüldü).
- **Beklenti karnesi (2026-08-16):** canlı ilk 56 gün, 124 taze-başlangıçlı aynı-konfig
  koşuya karşı yargılandı → **normal varyans** (ROI P55–P63; pencerelerin %63'ünde
  alpha ≤ 0 zaten olağan). Tek kuyruk bulgu: **MaxDD −%18,4 = P99** — izlemede.
  Gölge replay: Aday 3'e geçiş eski yönteme göre **+$292 önde** (pişmanlık yok).
- Sonuç: bu nottaki "kabul kriteri" hâlâ yürürlükte; canlı kural **değişmedi**.

# 👑 Qulla-21 — Kağıt Portföy ve Gerçek Defter (basit açıklama)

Bu doküman, canlı kağıt-trade (paper trade) sisteminin **nasıl çalıştığını** ve
2026-06-26'da yapılan **gerçek defter (ledger)** mimarisini sade dille anlatır.

> Eğitim/araştırma amaçlıdır. Yatırım tavsiyesi değildir. Gerçek para kullanılmaz.

---

## Yöntem nedir? (Qulla-21)

Qullamaggie tarzı momentum kırılımı. Her akşam (15:45 ET / 22:45 TR) otomatik çalışır:

| Aşama | Ne yapar |
|------|----------|
| **1. Veri** | ~373 büyük ABD hissesinin (S&P 500 + Nasdaq 100) fiyatını alır. Göstergeler için 5 yıllık geçmiş kullanır. |
| **2. En güçlüler** | Son 60 günde piyasadan (SPY) en çok ayrışan **50 hisse** = günün izleme listesi (RS top-50). |
| **3. Rejim** | SPY 200 günlük ortalamanın **üstünde mi?** Altındaysa o gün **yeni alım yok**. |
| **4. Sinyal** | İzleme listesinde **63 günün zirvesini kıran** + 52H'ye yakın + trendi yukarı hisseler aday. |
| **5. Alım** | Boş yer varsa en güçlüler alınır; taban tahsis her yeni pozisyon için özsermayenin **%7,5'i**. +2R bacağı bitmiş runner slotu boşaltır; nakit yoksa yeni alım yapılmaz. |
| **6. Satış (split)** | Pozisyon ikiye bölünür: **%60 +2R hedefte** satılır, **%40 21-EMA altına kapanana kadar** tutulur (runner). |

Canlı seçim ayrıca iki Aday 3 kuralı kullanır: kalabalık günde kalite+hareket
karışımıyla sıralama ve `SPY>SMA200` kapısına ek olarak havuzun en az %50'sinin
kendi SMA200'ü üzerinde olması (`A200≥%50`).

Para: sanal **$10.000** ile başlar, bileşik büyür.

---

## Gerçek defter (2026-06-26)

**Eski sorun:** Sistem her çalıştığında portföyü baştan hesaplıyordu. Borsa verisi
geriye dönük değişince (split/temettü düzeltmesi) **geçmiş yeniden yazılıyor**, hatta
canlı açılmış bir pozisyon sonradan kaybolabiliyordu. Bu, paper trade için uygun değildi.

**Çözüm:** Kalıcı **defter** (`~/.swing_paper_qulla_ledger.json`) = tek doğruluk kaynağı.

- İlk kez → backtest ile başlangıçtan bugüne **bir kez** doldurulur, sonra **dondurulur**.
- Sonraki her gün → defter motora yüklenir, **yalnız yeni gün** işlenir (`bt._step`).
- Bir kez işlenen gün **kilitlenir**: veri sonradan değişse bile geçmiş **değişmez**,
  açık pozisyon **gerçekten satılana kadar düşmez**.
- Her commit atomiktir ve önceki kilitli gün `.bak.YYYY-MM-DD` olarak saklanır.
  Ana defter kaybolmuş ama yedek varsa sistem sessizce sıfırdan başlamayı reddeder.
- Yeni giriş, açık pozisyon ve yeni/replay çıkış fiyatları quote endpoint'iyle çapraz
  kontrol edilir; `%25` üstü ölçek sapmasında yayın ve commit durur.

Sonuç: K/Z artık **sadece** gerçek alım/satım ve fiyat hareketiyle değişir — veri
revizyonları geçmişi bozamaz.

---

## Artımlı veri deposu

5 yıllık veri **her gün baştan indirilmez**. Ham fiyatlar `~/.swing_daily_store.pkl`
dosyasında birikir:

1. Depoyu aç → 2. yalnız **son günden sonraki yeni barları** indir → 3. ekle, kaydet →
4. göstergeleri depodan **taze hesapla**.

Ekstra koruma: bir hissede ani sıçrama (bölünme) görülürse o hisse tek seferlik tam
yenilenir; haftada bir tam yenileme güvenlik ağı vardır.

---

## Çıktılar

- **Telegram**: her akşam alım/satım + portföy durumu (sahip + aboneler).
- **Dashboard** (web): açık pozisyonlar, anlık K/Z, günlük K/Z, grafikler.
- **Sistem Sağlığı** (`/sistem-sagligi`): veri/defter uyumu, açık zayıflıklar,
  uygulanan korumalar ve bootstrap–forward sonuç ayrımı.
- **Komutlar**: `/portfolio`, `/lastscan`.

## İlgili dosyalar

- `swing2_backtest.py` — backtest motoru (`_step`, `build_market_from_frames`, `attach_watchlist`).
- `qulla_paper.py` — defter + artımlı veri deposu + günlük ilerletme (`run_qulla`, `commit_ledger`, `load_market_incremental`).
- `live_scan_telegram.py` — akşam cron'u; defteri yalnız gerçek gönderimde ilerletir.

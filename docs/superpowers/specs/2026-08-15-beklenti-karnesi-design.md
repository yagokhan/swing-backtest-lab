# Beklenti Karnesi + Gölge — Tasarım

**Tarih:** 2026-08-15 · **Durum:** Onaylandı (kullanıcı, yaklaşım B)
**Soru:** Canlı Qulla-21 (Aday 3) kağıt-trade penceresi (2026-05-27 → 2026-08-14, 56 işlem günü:
ROI +%2,2 · SPY +%3,4 · alpha −1,2pp · MaxDD −%18,4) **normal varyans mı, yapısal sapma mı?**

## Karar kuralı (kullanıcı onaylı)

Bileşik karne; esas ölçüt **ROI yüzdeliği**:
- Canlı pencere ROI'si taze-başlangıç dağılımında **P10 üstü → "normal varyans"** (değişiklik önerilmez).
- **P10 altı → "yapısal şüphe"** → derinleşme ayrı bir karar/spec (bu spec'in kapsamı dışı).
- Alpha ve MaxDD yüzdelikleri + forward kesit + gölge kıyası: yardımcı kanıt.

## Bileşenler

### §1 Taze-başlangıç dağılımı (ana dağılım)
- Kayan dilim yanıltır: eğri ortasından kesilen pencere dolu defterle başlar; canlı pencere boş
  defter + taze $10k ile başladı. Ana dağılım bu yüzden **taze-başlangıçlı koşulardan** kurulur.
- 5y veri içinde **her 10 işlem gününde bir** başlangıç (~120 koşu; başlangıçlar ≥2021-07,
  SMA200+RS ısınması için). Her koşu: boş defter, $10k, **tam canlı konfig**
  (`qulla_paper.DengeBacktester`: denge sıralama + A200 freni + combo `free_runner_slots` +
  60/40 split + %7,5 poz + 20 slot), tam 56 işlem günü.
- Her koşudan: ROI, aynı-pencere SPY getirisi → alpha, pencere-içi MaxDD → üç dağılım.
- Kayan-dilim dağılımı tek 5y koşusundan **yan not** olarak ayrıca verilir (sürekli-yatırım versiyonu).
- Veri: yalnız mevcut depo (`~/.swing_daily_store.pkl`, 08-14'e güncel). **İndirme yok**;
  `qp._load_store()` → `s.build_market_from_frames` → **`s.attach_watchlist` zorunlu**
  (bilinen RS-tuzağı: unutulursa top-50 kapısı kapanır, sonuç tamamen yanlış olur).

### §2 Karne + forward kesit
- Canlı üçlü (+%2,2 / −1,2pp / −%18,4) üç dağılıma yerleştirilir (yüzdelik + histogram özeti).
- Forward satırı (seçim-yanlılığı kontrolü): **07-06 → 08-14** gerçek defter eğrisinden ROI ve
  aynı dönem SPY (Aday 3 kararı 07-05'te verildi; sonrası saf out-of-sample).

### §3 Gölge replay ("Aday 3'e geçmeseydik?")
- `~/.swing_paper_qulla_ledger.json.bak.20260705-aday3` → `swing2_out/beklenti/` altına **kopya**.
- Eski-baz motorla (`s.Swing2Backtester`; combo + 60/40, denge sıralama ve A200 freni YOK)
  07-06 → 08-14 gün gün ileri oynatılır; `_fix_split_scale` aynen uygulanır.
- Çıktı: gölge son equity vs canlı $10.224,77 + gün gün iki eğri.

### §4 Temmuz ayrıştırması
- Defter eğrisindeki Temmuz −%9,3 üç parçaya: aynı dönem SPY · 6 derin kırmızının
  (ENPH/GLW/WDC/INTC/LRCX/TER) mark-to-market katkısı · kalan defter. Tek tablo.

### §5 Doğruluk sigortaları (fail-closed)
1. **Parite koşusu:** staggered başlangıçlardan biri kasıtlı 2026-05-27 → ROI defterle ~birebir
   olmalı (bilinen tek-bootstrap ≡ artımlı eşdeğerliği). Tutmazsa dağılım YAYINLANMAZ; önce fark
   teşhis edilir. (Bilinen küçük sapma kaynağı: FMP veri revizyonları — eşik: ±0,5 puan ROI.)
   **GÜNCELLEME (2026-08-15, uygulama sırasında):** kapı düştü (−2,14 puan) ve teşhis kod hatası
   DEĞİL veri-revizyonu kayması gösterdi (08-13 TAM depo yenilemesi; eğriler 07-06'ya dek birebir,
   40 girişin 37'si özdeş, fark yalnız Ağustos kalabalık-gün sıralama flip'leri, MaxDD birebir).
   Kapı v2 = YAPISAL: giriş-seti örtüşmesi ≥%90 VE 07-06 öncesi eğri izlemesi <%0,3 (fail-closed
   kalır). ROI kayması silinmez → karnede **çift yerleştirme**: hem defter ROI'si (+2,25) hem
   aynı-motor replay ROI'si yüzdelikleriyle raporlanır; kayma bandı bulgu olarak yazılır.
2. **Gölge ön-kontrol:** yedeğin son equity'si 07-05 kayıtlarıyla doğrulanır, sonra replay başlar.
3. Koşu sayısı azaltılırsa (süre vb.) açıkça loglanır — sessiz kısıtlama yok.
4. Tüm iş **salt-okur**: canlı ledger/state/store'a ve `load_market_incremental`'a dokunulmaz.

## Çıktılar
- `beklenti_lab.py` (ev dizini, `*_lab.py` geleneği) — tek dosya, `--dagilim` / `--golge` /
  `--temmuz` / `--karne` alt komutları; ara sonuçlar `swing2_out/beklenti/*.json` (yeniden
  koşmadan karne derlenebilir).
- Chat'te bileşik karne (onaylanan format) + KARAR satırı.
- Bellek: `swing2-beklenti-karnesi` (sonuçla birlikte).
- `/adaylar` yayını YOK (yaklaşım C seçilmedi; istenirse sonra).

## Kapsam dışı
- Canlı konfig değişikliği, yeni çıkış/tahsis deneyi, defter müdahalesi.
- P10-altı çıkarsa derinleşme deneylerinin tasarımı (ayrı brainstorm).

## Riskler
- **Süre:** ~120 × 56g koşu; market bir kez yüklenir, koşu başına saniyeler beklenir (~20-60 dk).
  Aşarsa örnekleme 15 güne seyreltilir (loglanır).
- **Örtüşen pencereler:** komşu koşular ilişkili → yüzdelik betimseldir, iid güven aralığı değildir;
  karnede açıkça söylenir.
- **In-sample gölgesi:** 5y tarih Aday 3'ün seçildiği veriyi içerir → dağılım hafif iyimser
  olabilir; forward kesit tam da bu yüzden karnede ayrı satırdır.

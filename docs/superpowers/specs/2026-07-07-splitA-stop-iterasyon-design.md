# Split A-bacağı (+2R hedef) için stop/timeout iterasyonu + /adaylar raporu

**Tarih:** 2026-07-07 · **Durum:** kullanıcı onaylı tasarım ("başla")

## Arka plan ve amaç

Canlı Qulla-21 · Aday 3 sisteminde her pozisyon 60/40 bölünür:
- **A bacağı (%60):** kural `target` (+2R limit). `_split_leg_exit`'te tek tetik
  `high ≥ giriş + 2R` (`swing2_backtest.py:1409`). **Aşağı yönde hiçbir çıkışı yok** —
  stop yok, timeout yok. Hisse girişten sonra çökerse bacak süresiz elde kalır
  (sınırsız zarar + slot/sermaye işgali; canlı örnek: TER −%24 iki günde).
- **B bacağı (%40):** `ema21` — kapanış<21-EMA'da çıkar (fiili aşağı-yön çıkışı var, kapsam DIŞI).

Grafiklerdeki "Ref. stop" çizgisi (girişteki plan stopu) yalnız gösterimdir; motor uygulamaz
(`_manage_split`: "Ortak felaket stopu YOK").

**Amaç:** A bacağına farklı stop/timeout korumaları takıp 5-pencere bataryasında mevcut
sistemle kıyaslamak; sonucu /adaylar sayfasına basit-dil raporu olarak eklemek.

**Çift taraflı hipotez:** stop yalnız kuyruk zararını kesmez; slot-darboğaz bulgusuna göre
(sistem günlerin ~%75'inde 20/20 dolu) stoplanan A bacağı slotu erken boşaltır
(`free_runner_slots` A bacağı çıkınca devreye girer) → sermaye yeni sinyale döner.
Stop hem MaxDD'yi hem ROI'yi iyileştirebilir — ya da kazananları erken kesip bozabilir. Ölçülecek.

## Kapsam DIŞI

- Canlıya alma / `qulla_paper.py` / defter / motor (`swing2_backtest.py`) değişikliği YOK.
- B bacağı kuralına dokunulmaz. Karar kullanıcıya aittir; bu iş yalnız deney + rapor üretir.

## Deney tasarımı

**Baz konfig:** Aday 3 canlı konfigi = `gen_adaylar_curves.py` cfg'si
(qswing 63g giriş, split 60/40 target2.0/ema21, combo %7.5 + free_runner_slots,
RS top-50 sp500_ndx, 20 slot, bileşik) + blend10 sıralama + A200≥%50 VE-freni (KX blend varyantı).

**Varyantlar (A bacağına eklenen koruma):**

| Anahtar | Kural |
|---|---|
| `none` (baz) | mevcut davranış — koruma yok |
| `ref` | girişteki plan stopu: `max(LOW10, giriş − 1.5×ATR0)` (pos.stop) |
| `atr1.0` / `atr2.0` / `atr3.0` | giriş − k×ATR0 sabit stop (ref ≈1.5×ATR'nin dar/geniş komşuları) |
| `t10` / `t21` / `t42` / `t63` | +2R, N işlem barı içinde gelmezse kapanışta market çıkış |
| `ema21` | A bacağı da kapanış<EMA21'de çıkar (hangisi önce: +2R ya da EMA21) |
| 2. dalga: kombolar | en iyi stop × en iyi timeout, VEYA mantığı (hangisi önce tetiklerse), 2-4 adet. "En iyi" = risk-ayarlı: 5 pencere bütününde ROI'yi korurken MaxDD'yi en çok iyileştiren (Aday 3 seçim geleneği); seçim raporda gerekçelenir |

**Pencereler:** batarya 5'lisi (`gen_adaylar_curves.WINS`): 5y tam · ayı 21-23 · topar 23-25 ·
son 2y · son 1y. Veri: sabit cache `swing2_cache/market_5y_152dab0ec647.pkl` +
`swing2_cache/breadth.pkl` (A200). Pencere seçme yanlılığı yok: TÜM varyantlar tüm pencerelerde.

**Stop semantiği (motor v7/atr_regime konvansiyonunun birebir kopyası, `swing2_backtest.py:1210-1216`):**
- Gün-içi dokunuş: `Low ≤ stop` → dolum = `Open` (gap: `Open < stop` ve `gap_fills`) yoksa stop
  fiyatı; slippage `_stop_slip`; etiket `A:STOP` (atr/ref) ayrımlı.
- **Aynı-bar kötümserliği:** stop kontrolü hedef kontrolünden ÖNCE — bar hem stopa hem hedefe
  dokunursa stop kazanır (v7 ile aynı sıra; iyimser yanlılık yok).
- Timeout: girişten ≥N işlem barı geçti ve A bacağı açık → kapanışta market çıkış
  (`close`, slip `_stop_slip`), etiket `A:T{N}`. Bar sayacı = pozisyonun yönetildiği bar sayısı
  (giriş barı yönetilmez — `_step` sırası: önce `_manage`, sonra `_open`; motor konvansiyonu).
- `ema21` varyantı: mevcut `ema21` kural koduyla aynı (kapanış teyitli, market).
- Stoplanan A bacağı → pozisyon runner-only → `free_runner_slots` gereği slot boşalır
  (motorda zaten böyle; deney bunu değiştirmez, kullanır).

**Sadakat kanıtı (rapor ön şartı):** `none` koşusu Aday 3 batarya sonuçlarını 5 pencerede
ROI+işlem sayısıyla **birebir** vermeli: +166.3/482 · +21.3/187 · +43.3/273 · +81.3/302 ·
+57.4/215. Tutmazsa deney durur, rapor yazılmaz (harness hatası aranır).

**Metrikler (varyant × pencere):** ROI · MaxDD · PF · Win% · işlem sayısı; kuyruk metrikleri:
en kötü A-bacağı çıkış %'si, A çıkışlarının ref-stop-altı payı, A-STOP/T tetiklenme sayısı;
kullanım: medyan yatırım oranı (slot geri dönüşüm etkisi görünür olsun).

## Uygulama

**Scratchpad deney betiği** (yaklaşım A — motor değişikliği YOK):
- `slot_darbogaz.py` / `gen_adaylar_curves.py` deseni: `KX` (blend+A200) kopyası +
  `_split_leg_exit` override'ı. Override yalnız `rule == "target"` bacağına stop/timeout
  ön-kontrolü ekler; diğer kurallar `super()`'e düşer.
- Bacak sözlüğüne deney alanları (`stop_px`, `bars`) betikte eklenir; motor sınıfları değişmez.
- Çıktı: scratchpad'e ham JSON (varyant × pencere metrikleri + finalist eğrileri) —
  rapor bu JSON'dan üretilir, koşular tekrarlanabilir.
- Tahmini yük: ~10 varyant × 5 pencere ≈ 50-75 koşu (kombolarla), 10-20 dk, tek makine.

## Rapor: /adaylar yeni bölümü

`dashboard_static/adaylar.html`'e statik bölüm **"🛡️ +2R bacağına stop koysak mı?"**
(slot bölümleri deseni; yerleşim: slot bölümlerinden sonra):
1. Basit-dil giriş: sorun (stopsuz bacak, TER örneği) + ne denendi.
2. 5-pencere ROI/MaxDD/PF tablosu (varyant satırları, baz vurgulu; en iyi hücreler işaretli).
3. 2-3 finalist + bazın özsermaye eğrisi, İKİ pencerede (5y tam + son 1y; inline boyutu
   ~40KB'ta tutmak için) — veri HTML içine gömülü (inline `<script>`);
   `paper_dashboard.py`'ye ve `adaylar_curves.js`'e DOKUNULMAZ → restart gerekmez.
4. Dürüst notlar: aynı-bar kötümser varsayımı, gap dolumu, slippage, "geçmiş ≠ gelecek",
   kuyruk metrikleri.
5. Sonuç kutusu: bulgu özeti + "karar rafta — canlı değişmedi" ibaresi.

Statik dosya diskten servis edilir (`/adaylar` route'u dosyayı her istekte okur) — dashboard
restart'ı GEREKMEZ. (Restart gerekirse tuzak notu: pkill YASAK; pgrep+PID kill + setsid.)

## Riskler / notlar

- Deney betiği KX kopyası olduğundan motor davranış değişikliklerinden etkilenmez ama
  motor güncellenirse kopya bayatlar — betik başına "sadakat kanıtı zorunlu" notu düşülür.
- ATR0 girişte sabitlenir (nedensel); `atr_regime`'deki gibi giriş barı ATR'si kullanılır.
- adaylar.html elle düzenlenir (statik); mevcut bölümler bozulmamalı — düzenleme sonrası
  tarayıcı kontrolü yerine en azından HTML yapı doğrulaması yapılır.
- Repo (swing-backtest-lab) senkronu: adaylar.html değişikliği iş sonunda commit'lenir
  (07-06 değişiklikleri gibi bekletilmez).

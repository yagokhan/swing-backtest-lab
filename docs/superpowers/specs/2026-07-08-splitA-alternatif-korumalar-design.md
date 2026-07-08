# splitA alternatif korumalar — giyotin · RS çöküşü · hacim kırılımı (2026-07-08)

## Amaç

Dünkü 🛡️ deneyi ([2026-07-07-splitA-stop-iterasyon](2026-07-07-splitA-stop-iterasyon-design.md))
klasik korumaların (stop/timeout/EMA21) hepsinin bazı kaybettirdiğini gösterdi; karar
"stopsuz devam" oldu. Kullanıcı bugün üç **fiyat-düşüşü-dışı** alternatif önerdi; sayısal
değerler bana bırakıldı ("sen dene, sonuçlar güzelse iterasyon da yap"):

1. **Giyotin / slot rotasyonu:** zarardaki pozisyon fiyat düştü diye satılmaz; ANCAK
   20/20 doluyken dışarıdan qscore ≥ Q "yıldız" sinyal gelirse, en kötü zararda pozisyon
   zorla satılır, yeri yıldıza verilir.
2. **RS çöküşü:** hissenin kendi düşüşüne değil SPY'ye göre performansına bak; pozisyondayken
   göreli güç çökerse (ör. 21 günde SPY'nin %15 gerisi) sat.
3. **Hacim-teyitli kırılım:** 50g ort. hacmin k katı devasa hacimle SMA50 kırılırsa sat
   (kurumsal satış); normal hacimli sıradan −%5 düşüşlere dokunma.

## Değişmez kurallar (dünkü deneyle aynı)

- Motor (`swing2_backtest.py`) ve canlı sistem DEĞİŞMEZ; her şey lab dosyasında override.
- Sabit cache `swing2_cache/market_5y_152dab0ec647.pkl` + `breadth.pkl`; 5-pencere bataryası.
- SADAKAT ZORUNLU: tüm tetikler kapalıyken batarya, Aday 3 blend `EXPECTED` ile 5/5 birebir
  (ROI+N). Tutmazsa koşu durur.
- Skor kriteri: 5 pencere ortalaması (Δroi + DD-iyileşmesi) — `score_variant` aynı.

## Mimari (Yaklaşım A — kullanıcı onayladı)

Yeni bağımsız dosya `/home/gokhan/altguard_lab.py` (splitstop_lab.py iskeletinin kopyası).
Tek sınıf `GKX(s.Swing2Backtester)` = gen_adaylar_curves.KX blend yolunun kopyası + üç tetik:

- **Giyotin** → `_step` override'ında: `_manage` sonrası, rejim açıkken adaylar HER ZAMAN
  taranır (motor doluyken taramıyordu; tetik kapalıyken bu fark davranışı değiştirmez).
  Slotlar doluysa ve qscore ≥ Q aday varsa: kurban = zararda (Close < entry) VE ≥ 5 işlem
  günü taşınmış pozisyonlar arasından `pnl` (en çok ekside %) veya `age` (en çok su-altı
  günü) kuralıyla seçilir; `_close(sym, date, close, "GIL", stop_slip)` ile TÜM pozisyon
  kapanıştan satılır; yıldız aynı gün normal `_open` ile girer. Yıldız başına 1 kurban;
  satış+mevcut nakit `_size(date)`'i karşılamayacaksa giyotin YAPILMAZ (boşa kurban önleme).
- **RS çöküşü** → tetik: `(hisse RET21 − SPY RET21) ≤ −X` (yüzde puan). Kapsam `A`:
  `_split_leg_exit` içinde target bacağına, +2R'den SONRA değerlendirilir (gün-içi limit
  önce); kapsam `tüm`: `_manage_split` başında tüm pozisyon kapanıştan (`RS21` etiketi).
- **Hacim kırılımı** → tetik: `Close < SMA50` VE `Volume ≥ k × VOLSMA50(önceki 50g)`.
  Kapsam/öncelik RS ile aynı (`VOLK` etiketi).

Veri: `load_data` df'lere `RET21G` (21-bar % getiri) ve `VOLR50`
(Volume / rolling(50).mean().shift(1)) kolonlarını ekler; SPY RET21 ayrı seri. Kolon
eklemek motor davranışını değiştirmez (motor bilinmeyen kolonu okumaz) — sadakat koşusu
bunu ayrıca kanıtlar.

## Dalga-1 gridi (12 varyant + baz)

| Grup | Varyantlar |
|---|---|
| Giyotin | `gil-pnl85` `gil-pnl90` `gil-age85` `gil-age90` |
| RS çöküşü | `rs10-A` `rs10-tum` `rs15-A` `rs15-tum` |
| Hacim | `vol2.5-A` `vol2.5-tum` `vol3.5-A` `vol3.5-tum` |

(k=2.5/3.5 seçildi; k=4 5 yılda çok nadir tetiklenebilir — dalga-2'de gerekirse.)

## Dalga-2 (iterasyon — sonuca bağlı)

Dalga-1'de bazı geçen veya yaklaşan grup varsa: eşik taraması genişler (Q=80, X=20,
k=3/4, pencere 10/42) ve/veya en iyi iki fikrin kombosu koşulur. Hiçbiri yaklaşmazsa
dalga-2 açılmaz, rapor "denendi, geçemedi" belgesi olur.

## Doğrulama

1. `--selftest`: market verisiz sentetik testler — tetik semantiği, +2R önceliği,
   kapsam A/tüm farkı, giyotin kurban seçimi (pnl/age), min-yaş ve nakit-yeterlilik
   koşulları, kârdaki pozisyona dokunmama.
2. `--fidelity`: tetikler kapalı → 5/5 EXPECTED birebir.
3. Koşu-içi assertler: GIL kurbanı satış anında zarardaydı + slotlar doluydu; her koruma
   varyantında tetik sayacı > 0.

## Rapor (/adaylar)

`ALTAB:BEGIN/END` işaretçili yeni bölüm: "♻️ Stopsuz bacağa alternatif korumalar (2026-07-08)"
— 🎯 BLEG bölümünden sonra, "Karar öncesi tartılan noktalar" çapasından önce upsert
(dünkü desenle aynı, idempotent). İçerik: soru+kurulum blockquote'u, dönem×varyant ana
tablosu (getiri/çukur/PF/işlem/parada kalma/en kötü tek çıkış/tetik sayısı), 5y + son-1y
eğrileri (baz + en iyi 2 finalist + SPY, lwc inline), dürüstlük notu, sonuç kutusu.
Çıktı JSON: `swing2_out/altguard_results.json`. docs HTML+PDF snapshot yenilenir;
lab dosyası + rapor repoya (`swing-backtest-lab`) commit edilir.

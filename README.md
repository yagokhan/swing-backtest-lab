# Swing Backtest Lab

Momentum/breakout **swing trading backtest motoru** + **canlı kağıt-trade sistemi
(👑 Qulla-21)** + deney arşivi. FMP (Financial Modeling Prep) günlük verisi,
Türkçe web arayüzleri, Telegram yayını. Portföy takip uygulamasından **bağımsız**,
kendi başına çalışır.

> Eğitim/araştırma amaçlıdır. Yatırım tavsiyesi değildir. Geçmiş performans gelecek getiriyi garanti etmez. Kağıt-trade tarafında gerçek para kullanılmaz.

---

## Ne içerir

### Backtest motoru + arayüz

- **`swing2_backtest.py`** — çoklu-hisse, günlük-bar portföy backtest motoru. Tüm trade mantığı + FMP veri hattı burada. İki **giriş** modu:
  - `swing2` — 8-katman skor (24p) + kill-switch (Weinstein Aşama analizi, VCP, momentum, R/R…).
  - `qswing_breakout` — Qullamaggie tarzı kırılım: rejim açık + Aşama 2 + N-gün tepe kırılımı + 52H yakınlık + SPY'ı geçen momentum.
  - **Çıkış** modları: ATR-trail şampiyonu · Qullamaggie N-gün MA trail · 8-EMA stop + TP-grid (RR/RSI/ATR-climax/hibrit).
- **`qswing/`** — Qullamaggie tarzı tek-hisse anlık analiz + tarama; FMP'den çekip koyu temalı Türkçe HTML rapor üretir (Aşama 2 skoru + 5-kapı pre-flight çeklist → AL/İZLE/KAÇIN).
- **`backtest.html`** — bağımsız "Swing Backtest Lab" arayüzü (Chart.js equity grafiği, işlemler, aylık tablo, grid). Harici bağımlılık: yalnız Chart.js CDN.
- **`server.py`** — minimal API + statik sunucu (`/api/backtest`, `/api/qswing`, `/api/qswing/scan`).
- **`calibrate_fmp.py`** — şampiyon parametre kalibrasyonu (2y+5y ızgara).
- **`qswing_grid.py`** — qswing kırılım eşik ızgarası (kırılım periyodu × VDU × RS × çıkış).
- **`rs_universe.py`** — sistematik evren: S&P 500 + Nasdaq 100 (~373 sembol) → günlük RS top-50 izleme listesi (seçim-yanlılığı gidermek için).

### Canlı kağıt-trade sistemi (👑 Qulla-21)

Kırılım stratejisinin **canlı, defter-tabanlı** kağıt-trade uygulaması — sanal $10.000,
her akşam 15:45 ET'de cron ile çalışır, Telegram'a yayınlar. Sade anlatım:
[`docs/qulla21-defter.md`](docs/qulla21-defter.md).

- **`qulla_paper.py`** — kalıcı **gerçek defter** (ledger; geçmiş kilitli, atomik commit + otomatik yedek), artımlı veri deposu, günlük ilerletme (`run_qulla`, `commit_ledger`).
- **`live_scan_telegram.py`** — akşam cron'u: veri → tarama → doğrulama kapıları → defter commit → Telegram yayını. Bar gecikmesinde tekrar dener, sessiz atlamaz.
- **`paper_trader.py`** — durum/abone/lastscan yardımcıları + FMP quote katmanı.
- **`paper_dashboard.py`** — salt-okur web dashboard (portföy, equity, sağlık; `/adaylar`, `/sistem-sagligi`, `/yeni-deneyler` sayfaları `dashboard_static/`'ten).
- **`telegram_command_bot.py`** — `/portfolio`, `/lastscan` komutları.
- **`paper_keepalive.sh`** — @reboot + 5dk watchdog: bot/dashboard/backtest sunucusu ayakta kalır.

### Deney arşivi (laboratuvarlar)

Canlı kuralı değiştirmeden çalışan, jitter/komşuluk testli deney araçları; sonuçlar
`dashboard_static/adaylar.html` sayfasında (karar günlüğü + dürüstlük notlarıyla):

- **`beklenti_lab.py`** — beklenti karnesi: canlı pencere, 124 taze-başlangıçlı aynı-konfig koşuya karşı (dağılım + gölge replay + ay ayrıştırma).
- **`splitstop_lab.py` · `altguard_lab.py`/`altguard_jitter.py` · `karkilit_lab.py`** — stop/koruma varyantları (hepsi bazdan kötü çıktı; stopsuzluk dersinin kaynağı).
- **`bleg_lab.py`/`bleg_report.py`** — runner (B bacağı) anatomisi.
- **`tahsis_lab.py`** — slot/tahsis kuralları (Giyotin-2, VIX şalteri).
- **`ml_*_lab.py` + `ml_backfill.py` + `ml_shadow_report.py`** — sahte-kırılım ML gölge hattı (walk-forward AUC≈0.47 → kestirim gücü yok; sayfada uyarıyla).
- **`exp_swing2*.py` + `exp_analyze.py` + `gen_*_report.py`** — parametre bataryaları ve rapor üreticileri.

### Dokümantasyon + testler

- **`docs/qulla21-defter.md`** — yöntem + gerçek defter mimarisi (sade dille, güncel tutulur).
- **`docs/qulla21-yontem-llm.md`** — **LLM tartışma dokümanı:** yöntemin kendi başına yeterli, tam-parametreli spesifikasyonu + deneysel kanon (elenen fikirler) + açık sorular. Başka bir LLM'e yapıştırıp yöntemi tartışmak için.
- **`docs/qulla21-metodoloji-devam-20260724.md`** — metodoloji bulguları + devam planı (tarihli eklerle).
- **`test_glitch_guard.py` · `test_stale_guard.py` · `test_operational_safety.py` · `test_beklenti_lab.py`** — veri-glitch doğrulama kapısı, bar-gecikme davranışı, operasyonel güvenlik ve karne yardımcıları (pytest).

## Kurulum

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env        # FMP_API_KEY'i içine yaz  (veya env / ~/.portfolio_keys.json)
```

FMP anahtarı çözüm sırası: `FMP_API_KEY` env → `.env` → `~/.portfolio_keys.json`.
Ücretli FMP planı önerilir (ücretsiz plan küçük hisseleri ve QQQ'yu kapatır).

## Çalıştırma

```bash
python3 server.py                 # → http://localhost:8053/
# PORT=8060 python3 server.py     # farklı port
```

Tarayıcıda **`http://localhost:8053/`** → Backtest Lab açılır.

### API (curl)

```bash
# backtest
curl -s -X POST localhost:8053/api/backtest -H 'Content-Type: application/json' \
  -d '{"preset":"default","period":"2y","entry_mode":"qswing","exit_strategy":"champion"}'

# qswing tek-hisse rapor (HTML)
curl -s 'localhost:8053/api/qswing?ticker=NNE' -o nne.html

# qswing küme tarama (HTML, net duruşa sıralı)
curl -s 'localhost:8053/api/qswing/scan?preset=swing2' -o scan.html
```

### Komut satırı (sunucusuz)

```bash
python3 -m qswing NNE AAPL TSLA          # qswing rapor + index
python3 calibrate_fmp.py                 # şampiyon kalibrasyon
python3 qswing_grid.py                   # qswing eşik ızgarası
python3 -c "import swing2_backtest as s; print(s.run_backtest_api({'preset':'mega','period':'2y','entry_mode':'qswing'})['metrics'])"
```

## Canlı kağıt-trade (özet)

Kural seti (⭐ "Aday 3", 2026-07-06'dan beri): RS top-50 izleme listesi · **63 gün**
tepe kırılımı · rejim `SPY>SMA200` **+** havuz genişliği `A200≥%50` · en fazla
**20 slot**, taban tahsis **%7,5**/poz (+2R bacağı bitmiş runner slot açar) ·
split çıkış **%60 @ +2R** limit + **%40 runner** (21-EMA altına kapanışta) ·
$10.000 bileşik. Ayrıntı ve gerekçeler: [`docs/qulla21-defter.md`](docs/qulla21-defter.md).

- **Zamanlama:** hafta içi 22:45/23:45 TR (≈15:45 ET) cron → `live_scan_telegram.py --et-window`; kalibrasyon "15:45 girişi ≈ kapanış" gösterdi.
- **Defter:** `~/.swing_paper_qulla_ledger.json` tek doğruluk kaynağı; geçmiş kilitli, her commit atomik + yedekli. Veri revizyonları geçmişi değiştiremez.
- **Doğrulama kapıları:** giriş/açık/replay-çıkış fiyatları bağımsız quote ile çapraz kontrol (fail-closed); bar gecikmesinde 4×120sn tekrar + Telegram uyarısı.
- **Dashboard:** `python3 paper_dashboard.py` → portföy/equity/sağlık + `/adaylar` (deney arşivi ve karne).
- **Testler:** `python3 -m pytest test_glitch_guard.py test_stale_guard.py test_operational_safety.py test_beklenti_lab.py`

Durum (2026-08-20): canlı pencere 2026-05-27'den beri işliyor; 2026-08-16 beklenti
karnesi kararı **normal varyans** — kurallar değişmedi (tek izleme kalemi: MaxDD P99).

## Backtest parametreleri (özet)

| Alan | Açıklama |
|------|----------|
| `preset` | `default` (~95) · `mega` (20) · `tech` (18) — veya `symbols:[...]` |
| `period` / `start_date`+`end_date` | 1y/2y/5y/10y veya el ile aralık |
| `entry_mode` | `swing2` · `qswing` |
| `exit_strategy` | `champion` · `ma_trail` · `rr_based` · `momentum` · `atr_climax` · `hybrid` |
| `min_score`, `rr_target`, `atr_stop_mult`, `max_positions` | giriş/risk eşikleri |
| `run_grid` | parametre grid-search |

## qswing — Giriş & Çıkış (detaylı)

qswing kırılım stratejisi, qswing'in skorlama mantığını swing2 portföy motoruna **giriş sinyali** olarak bağlar: `entry_mode='qswing_breakout'`. Aşağıdaki tüm kurallar her gün, her sembol için **nedensel** (yalnız o güne kadarki bar) uygulanır.

### GİRİŞ — Qullamaggie kırılım

Her bar, sırayla **(1) ortak ön-filtreler** sonra **(2) kırılım kapısı**:

**1) Ön-filtreler (rejim + Aşama 2 trend)** — `run()` döngüsünde, hepsi geçmeli:
- **Rejim açık:** `SPY > SMA200`. Kapalıysa o gün hiç yeni alım yok.
- **Trend dizilimi:** `Fiyat > SMA20` **ve** `> SMA50` **ve** `> SMA200` (fiyat tüm ortalamaların üstünde).
- **Eğim:** `SMA200` eğimi pozitif (`SLOPE200 > 0`, `slope_window=20` bar üzerinden).

**2) Kırılım kapısı** — `_qswing_entry_ok()`:
- **Kırılım:** `Close > önceki qswing_breakout_lb günün en yükseği` (`HIGH_PRIOR_40 = High.rolling(40).max().shift(1)` → nedensel, bugünkü bar hariç). Yeni alana çıkış.
- **52H yakınlık:** `Close ≥ qswing_near_high × 52-hafta-zirvesi` (0.75 → zirvenin %25 içinde). Liderleri seçer.
- **Hacim kuruması (ops.):** `qswing_vdu_max < 9` ise `VDU = ort5(Volume)/ort50(Volume) ≤ tavan`. **Varsayılan 9.0 = KAPALI** (ızgara: VDU şartı getiriyi düşürüyor — kırılım barında hacim genelde *patlar*).
- **Görece güç (RS):** `rs = RET60 − SPY_RET60`; `RET60 > 0` **ve** `rs ≥ qswing_rs_min` (0). 60 günde hem pozitif hem SPY'ı geçen.
- Kapıyı geçen adaylar **RS'e göre sıralanır** (en güçlü momentum önce); boş slotlara `max_positions`'a kadar alınır.

**Trade planı (giriş/stop/hedef)** — `compute_trade_plan()`:
- **Giriş fiyatı** = kırılım barının kapanışı (`Close`). Gerçek dolum = `Close × (1 + entry_slippage_bps/10000)` → **+8 bps**.
- **Stop** = son 10 günün en düşüğü (`LOW10`, `pivot_lookback=10`); ancak `Close − atr_stop_mult×ATR(14)` (1.5×ATR) tabanından daha aşağıdaysa o tabana çekilir (aşırı geniş stopu sınırlar).
- **Risk** = Giriş − Stop. **İlk hedef** = `Giriş + Risk × rr_target` (2.0 → **2R**).
- **Pozisyon büyüklüğü** = (bileşikse) güncel sermaye × `max_position_pct` (%20); `max_positions=5`; komisyon `$1/bacak`.

| Parametre | Varsayılan | Anlamı |
|-----------|-----------|--------|
| `entry_mode` | `qswing_breakout` | giriş motoru |
| `qswing_breakout_lb` | **40** | kaç günün tepesi aşılınca kırılım (FMP ızgara şampiyonu) |
| `qswing_near_high` | 0.75 | 52H zirveye yakınlık (≥%75) |
| `qswing_vdu_max` | 9.0 | VDU tavanı (≥9 = kapalı) |
| `qswing_rs_min` | 0.0 | min görece güç (RET60 − SPY_RET60) |
| `atr_stop_mult` | 1.5 | ATR stop tabanı |
| `rr_target` | 2.0 | ilk hedef (R cinsinden) |
| `pivot_lookback` | 10 | LOW10 / stop penceresi |
| `slope_window` | 20 | SMA200 eğim penceresi |
| `entry_slippage_bps` | 8 | giriş kayması |
| `max_positions` / `max_position_pct` | 5 / %20 | eşzamanlı poz / poz başı pay |

### ÇIKIŞ — Qullamaggie 10-gün MA trail (`exit_mode='ma_trail'`)

Her gün, her açık pozisyon için (giriş günü hariç) **sırayla** `_manage()`:

**(a) İlk koruma stopu** (`ma_keep_initial_stop=True`) — *felaket-zemini.*
Gün-içi `Low ≤ ilk stop` (planın LOW10/ATR stopu) ise pozisyon **market emriyle** kapanır (`STOP`); gap'te açılıştan dolar. Kırılım hemen geri dönerse korur.

**(b) Kısmi kâr** (`partial_tp=True`) — *runner modeli.*
`High ≥ Giriş + Risk × partial_rr` (2.0 → **+2R**) olunca pozisyonun `partial_pct`'i (**%50**) **limit emriyle** satılır (`PARTIAL`). Kalan %50 = "runner".

**(c) 10-gün MA trail** — *asıl çıkış.*
`SMA8` kolonu = `sma(Close, ma_trail_len)` = **10-gün SMA** (`ma_trail_type='sma'`).
- `ma_confirm_close=True` (varsayılan): fiyat günü **10-gün MA'nın ALTINDA kapatınca** çık (kapanışta, `MA8`). Gün-içi fitilleri yok sayar — Qullamaggie'nin "kapanış teyidi" kuralı.
- `ma_confirm_close=False` olsaydı: gün-içi MA'ya **değince** MA fiyatından çıkardı (daha erken/gürültülü).

Kalan runner, fiyat 10-gün ortalamanın altına kapanana dek tutulur → trend sürdükçe koşar. Çıkış kayması `stop_slippage_bps` (15 bps, market).

| Parametre | Varsayılan | Anlamı |
|-----------|-----------|--------|
| `exit_mode` | `ma_trail` | çıkış motoru |
| `ma_trail_len` | **10** | MA periyodu (Qullamaggie 10-gün) |
| `ma_trail_type` | `sma` | SMA (EMA değil) |
| `ma_confirm_close` | True | MA altına **kapanış** teyidi (gün-içi fitil değil) |
| `ma_keep_initial_stop` | True | ilk ATR/LOW10 stopu felaket-zemini olarak kalır |
| `partial_tp` / `partial_pct` / `partial_rr` | True / 0.5 / 2.0 | %50 kısmi @ +2R |
| `stop_slippage_bps` | 15 | çıkış (market) kayması |

**İşlem etiketleri:** `STOP` (ilk stop) · `PARTIAL` (%50 @2R) · `MA8` (10-gün MA altı kapanış) · `TRAIL`/`TP` (diğer modlarda).

> FMP ızgara sonucu (tam ~95 hisse evreni): qswing kırılım (lb=40) + ATR-trail şampiyon çıkış → 2y **+148.8% / DD −10.0%** (Win %58, PF 2.09), 5y **+149.2% / DD −24.1%**. 10-gün MA trail çıkış benzer (5y +119% / −17%). In-sample optimize; canlıda daha mütevazı beklenmeli.

## Pozisyon boyutlandırma

İki mod var (`sizing_mode`). Boyutlandırma **giriş yöntemine (swing2/qswing) bağlı değildir** — ikisi de aynı planı kullanır; risk-bazlıda farklılaşan tek şey **çıkış moduna göre stop referansıdır**.

### 1) Sabit tahsis (`fixed`, varsayılan)
Her pozisyon = sermaye × `max_position_pct`.
```
poz_$ = (compounding ? güncel_sermaye : başlangıç_sermaye) × max_position_pct
hisse = (poz_$ − komisyon) / dolum
```
Varsayılan: $100k · %20/poz · maks 5 poz → poz başına ≈ $20k, 5 dolunca %100 yatırımda. Equal-weight; **işlem başına dolar-riski stop mesafesine göre değişir** (geniş stop = daha çok risk).

### 2) Risk-bazlı (`risk`)
Her işlem sermayenin sabit bir %'sini riske eder (`risk_per_trade_pct`). Lot, stop mesafesine göre ayarlanır:
```
risk_$ = sermaye × (risk_per_trade_pct / 100)        # örn. $100k × %1 = $1.000
hisse  = risk_$ / (dolum − ilk_stop)                  # lot başına risk ile böl
poz_$  = hisse × dolum   (poz tavanı: sermaye × max_position_pct ile kırpılır)
```

**İlk stop referansı çıkış moduna göre değişir** (giriş yöntemi değiştirmez):

| Çıkış | İlk stop (risk referansı) |
|-------|---------------------------|
| Şampiyon (ATR-trail) · MA-trail | `compute_trade_plan` stopu = **LOW10**, `kapanış − 1.5×ATR` tabanlı |
| 8-EMA modları (RR/RSI/Climax/Hibrit) | **giriş barındaki 8-EMA** (gerçek stop) |

Yani **risk %'si tek bir sayıdır**, yöntem başına farklı belirlenmez; değişen, o yüzdenin kaç lot aldığıdır (stop mesafesi). Dar stop → büyük pozisyon, geniş stop → küçük pozisyon; her işlem stop'a takılırsa **aynı doları** kaybeder.

**Örnek** (sermaye $100k, risk %1 → $1.000, giriş $50):
- Şampiyon, plan stop $46 → risk/lot $4 → 250 lot = **$12.500**
- RR (8-EMA), 8-EMA $48 → risk/lot $2 → 500 lot = **$25.000** (poz tavanıyla sınırlanır)
- Geniş stoplu işlem, stop $40 → risk/lot $10 → 100 lot = **$5.000**

**Koruyucular:** poz tavanı (`max_position_pct`) çok dar stoplu işlemi sınırlar · nakit yetmezse atlanır · `giriş − stop ≤ 0` ise işlem açılmaz.

| Parametre | Varsayılan | Anlamı |
|-----------|-----------|--------|
| `sizing_mode` | `fixed` | `fixed` (tahsis) · `risk` (risk-bazlı) |
| `risk_per_trade_pct` | 1.0 | risk modunda işlem başına riske edilen sermaye % |
| `max_position_pct` | 0.20 | sabit: poz payı · risk: poz tavanı |
| `max_positions` | 5 | eşzamanlı açık poz |
| `initial_capital` | 100000 | başlangıç sermaye |

Etki (örnek, mega 2y qswing): Sabit ROI +21.7%/DD −10.6% · Risk %1 ROI +21.1%/DD **−8.7%** · Risk %0.5 ROI +7.0%/DD −8.2% — risk düştükçe pozisyonlar küçülür, getiri ve drawdown birlikte azalır.

## Notlar

- Varsayılan fiyat kaynağı **FMP** (`price_source='fmp'`); `'yfinance'` fallback mevcut.
- FMP split-ayarlı/temettü-ayarsızdır; sonuçlar yfinance'e göre hafif kayabilir.
- Sonuçlar in-sample optimize edilmiştir; canlıda daha mütevazı getiri beklenmeli.

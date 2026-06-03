# Swing Backtest Lab

Momentum/breakout **swing trading backtest motoru** + tek dosya web arayüzü.
İki giriş stratejisi, çoklu çıkış modu, FMP (Financial Modeling Prep) günlük verisi.
Portföy takip uygulamasından **bağımsız**, kendi başına çalışır.

> Eğitim/araştırma amaçlıdır. Yatırım tavsiyesi değildir. Geçmiş performans gelecek getiriyi garanti etmez.

---

## Ne içerir

- **`swing2_backtest.py`** — çoklu-hisse, günlük-bar portföy backtest motoru. Tüm trade mantığı + FMP veri hattı burada. İki **giriş** modu:
  - `swing2` — 8-katman skor (24p) + kill-switch (Weinstein Aşama analizi, VCP, momentum, R/R…).
  - `qswing_breakout` — Qullamaggie tarzı kırılım: rejim açık + Aşama 2 + N-gün tepe kırılımı + 52H yakınlık + SPY'ı geçen momentum.
  - **Çıkış** modları: ATR-trail şampiyonu · Qullamaggie N-gün MA trail · 8-EMA stop + TP-grid (RR/RSI/ATR-climax/hibrit).
- **`qswing/`** — Qullamaggie tarzı tek-hisse anlık analiz + tarama; FMP'den çekip koyu temalı Türkçe HTML rapor üretir (Aşama 2 skoru + 5-kapı pre-flight çeklist → AL/İZLE/KAÇIN).
- **`backtest.html`** — bağımsız "Swing Backtest Lab" arayüzü (Chart.js equity grafiği, işlemler, aylık tablo, grid). Harici bağımlılık: yalnız Chart.js CDN.
- **`server.py`** — minimal API + statik sunucu (`/api/backtest`, `/api/qswing`, `/api/qswing/scan`).
- **`calibrate_fmp.py`** — şampiyon parametre kalibrasyonu (2y+5y ızgara).
- **`qswing_grid.py`** — qswing kırılım eşik ızgarası (kırılım periyodu × VDU × RS × çıkış).

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

## Notlar

- Varsayılan fiyat kaynağı **FMP** (`price_source='fmp'`); `'yfinance'` fallback mevcut.
- FMP split-ayarlı/temettü-ayarsızdır; sonuçlar yfinance'e göre hafif kayabilir.
- Sonuçlar in-sample optimize edilmiştir; canlıda daha mütevazı getiri beklenmeli.

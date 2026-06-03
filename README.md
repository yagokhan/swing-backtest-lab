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

## Notlar

- Varsayılan fiyat kaynağı **FMP** (`price_source='fmp'`); `'yfinance'` fallback mevcut.
- FMP split-ayarlı/temettü-ayarsızdır; sonuçlar yfinance'e göre hafif kayabilir.
- Sonuçlar in-sample optimize edilmiştir; canlıda daha mütevazı getiri beklenmeli.

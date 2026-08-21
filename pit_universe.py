"""pit_universe.py — Point-in-Time evren: survivorship bias (hayatta kalma yanılgısı) giderme.

SORUN
-----
Qulla-21 statik bir sp500_ndx listesi (373 sembol) kullanıyor. Bu liste BUGÜNÜN
üyelerinden oluşuyor; 2021-2026 arasında batan/satın alınan şirketler (SIVB, FRC,
ATVI, SGEN, TWTR, VMW, SPLK, XLNX...) evrende hiç yok. Backtest onları hiç
alamıyor → hiç kaybetmiyor. Stopsuz bir sistemde bu, ölçülmemiş bir kuyruk riski.

FMP PLAN GERÇEĞİ (2026-08-21'de ölçüldü, varsayım değil)
--------------------------------------------------------
  /api/v3/delisted-companies          → 403 (v3 bu planda tamamen kapalı)
  /stable/delisted-companies?page=0   → OK, 100 kayıt
  /stable/delisted-companies?page>=1  → 402 Payment Required  ← SAYFALAMA PAYWALL
  /stable/historical-sp500-constituent→ 402 Payment Required  ← PIT ÜYELİK YOK
  /stable/stock-list                  → OK, 38.756 sembol
  /stable/actively-trading-list       → OK, 26.247 sembol
  /stable/historical-price-eod/full   → OK, ÖLÜ TICKERLAR DAHİL

Yani delisted-companies uç noktası 2021-2026 ölülerini SAYAMAZ (yalnız son ~3
haftayı görüyor). Ama buna ihtiyaç da yok: stock-list ölü tickerları ZATEN
içeriyor (SIVB/FRC/ATVI/.../MXIM → 16/16 doğrulandı) ve fiyat geçmişleri tam
olarak delist gününde bitiyor. Havuzu stock-list'ten kurup evreni GÜNLÜK
maskeyle belirlemek hem paywall'ı aşıyor hem de yapısı gereği look-ahead'siz:
ölü hissenin ölüm gününden sonra barı yoktur → maske onu kendiliğinden eler.
Doğum (IPO) tarafı da aynı mekanizmayla halloluyor.

LOOK-AHEAD GÜVENCELERİ
----------------------
1. Maskenin TAMAMI shift(1): bir günün uygunluğu YALNIZ önceki günlerin
   barlarıyla belirlenir. Fiyat eşiği de dahil (Qulla girişi 15:45'te yapıyor;
   o anda günün kapanışı henüz kesin değil).
2. "Hiçbir gün eşiği geçmeyen sembolü havuzdan at" budaması look-ahead DEĞİL:
   attığı sembol hiçbir günün maskesine zaten giremezdi. Sonuç matematiksel
   olarak tüm havuzu taşımakla birebir aynı; sadece RAM tasarrufu.
3. RS skoru rs_universe.rs_score ile BİREBİR aynı semantik (bkz. rs_fast).

SADAKAT KAPISI
--------------
build_watchlist_fast(), mevcut rs_universe.build_watchlist() ile aynı havuzda
GÜN GÜN BİREBİR aynı sonucu vermek zorundadır. Tutmazsa deney geçersizdir.
  python3 pit_universe.py --fidelity

Canlı sisteme (qulla_paper / defter / state) DOKUNMAZ. Salt okuma + yeni cache.
"""
from __future__ import annotations

import json
import os
import pickle
import re
import sys
import time
import urllib.parse as _up
import urllib.request as _ur
import concurrent.futures as _cf

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/gokhan")

BASE = "https://financialmodelingprep.com/stable"
CACHE_DIR = "/home/gokhan/swing2_cache"
POOL_JSON = f"{CACHE_DIR}/pit_pool.json"
FRAMES_PKL = f"{CACHE_DIR}/pit_frames.pkl"

# Point-in-Time evren eşikleri (kullanıcı spesifikasyonu)
MIN_PRICE = 10.0
MIN_DOLLAR_VOL = 50_000_000.0
ADV_WINDOW = 20
MIN_HISTORY = 200

# Şekil filtresi: saf ABD adi hisse tickerı. Nokta/tire = yabancı borsa, warrant,
# unit, preferred. Bunlar Qulla evrenine ait değil.
_CLEAN_TICKER = re.compile(r"^[A-Z]{1,5}$")


# =========================================================================
# 1) FMP ERİŞİMİ — fail-closed
# =========================================================================
def _key(explicit=None):
    k = explicit or os.environ.get("FMP_API_KEY")
    if k:
        return k
    p = os.path.expanduser("~/.portfolio_keys.json")
    if os.path.exists(p):
        try:
            return json.load(open(p)).get("FMP_API_KEY")
        except Exception:
            return None
    return None


class FMPError(RuntimeError):
    """FMP kopması. Sessizce yutulmaz — çağıran ya yakalar ya durur."""


def _get(path, params=None, key=None, timeout=60, tries=3, backoff=1.5):
    """Tek FMP çağrısı. Kalıcı hata → FMPError (fail-closed: boş liste DÖNMEZ,
    çünkü boş liste 'delist olan yok' diye sessizce yanlış yorumlanır)."""
    q = dict(params or {})
    q["apikey"] = key or _key()
    if not q["apikey"]:
        raise FMPError("FMP_API_KEY yok (~/.portfolio_keys.json veya env)")
    url = f"{BASE}/{path}?" + _up.urlencode(q)
    last = None
    for i in range(tries):
        try:
            req = _ur.Request(url, headers={"User-Agent": "swing2/1.0"})
            with _ur.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            code = getattr(e, "code", None)
            if code in (401, 402, 403):      # yetki/paywall → tekrar denemek anlamsız
                raise FMPError(f"{path}: HTTP {code} (plan kapsamı dışı)") from e
            time.sleep(backoff ** i)
    raise FMPError(f"{path}: {type(last).__name__}: {last}")


def fetch_stock_list(key=None):
    """Yaşayan + ÖLÜ tüm semboller (38k+). Havuzun temeli."""
    d = _get("stock-list", key=key)
    if not isinstance(d, list) or len(d) < 10_000:
        raise FMPError(f"stock-list beklenmedik boyut: {len(d) if isinstance(d,list) else type(d)}")
    return d


def fetch_etf_list(key=None):
    d = _get("etf-list", key=key)
    if not isinstance(d, list) or len(d) < 1_000:
        raise FMPError(f"etf-list beklenmedik boyut: {len(d) if isinstance(d,list) else type(d)}")
    return d


def fetch_actively_trading(key=None):
    d = _get("actively-trading-list", key=key)
    if not isinstance(d, list) or len(d) < 10_000:
        raise FMPError("actively-trading-list beklenmedik boyut")
    return d


def fetch_delisted_recent(key=None):
    """SADECE page=0 (100 kayıt). page>=1 bu planda 402.

    Havuz için GEREKLİ DEĞİL (stock-list ölüleri zaten içeriyor); yalnızca
    teşhis/raporlama amaçlı: son delistlerin evrende doğru davrandığını
    doğrulamak için. Kopması havuz kurmayı engellemez."""
    try:
        d = _get("delisted-companies", {"page": 0}, key=key)
        return d if isinstance(d, list) else []
    except FMPError as e:
        print(f"  ⚠️ delisted-companies alınamadı ({e}) — havuz etkilenmez", flush=True)
        return []


def fetch_screener_meta(key=None, limit=5000):
    """Yaşayan likit isimler için sektör/endüstri etiketi (teşhis + raporlama)."""
    try:
        return _get("company-screener",
                    {"exchange": "NASDAQ,NYSE,AMEX", "isEtf": "false", "isFund": "false",
                     "priceMoreThan": 5, "limit": limit}, key=key)
    except FMPError as e:
        print(f"  ⚠️ screener alınamadı ({e}) — etiketsiz devam", flush=True)
        return []


# =========================================================================
# 2) HAVUZ KURULUMU
# =========================================================================
def build_symbol_pool(key=None, verbose=True):
    """'Bir zamanlar var olmuş' ABD adi-hisse havuzu.

    stock-list (yaşayan ∪ ölü) − etf-list − şekil-dışı tickerlar.
    ETF'ler çıkarılır (SPY/QQQ/XLK likidite eşiğini kolayca geçer ama hisse
    momentum evrenine ait değil). Fon/mutual fund'lar dolar-hacmi maskesinde
    zaten elenir; yine de şekil filtresi çoğunu keser."""
    sl = fetch_stock_list(key)
    etf = fetch_etf_list(key)
    all_syms = {x["symbol"] for x in sl if x.get("symbol")}
    etf_syms = {x["symbol"] for x in etf if x.get("symbol")}
    names = {x["symbol"]: (x.get("companyName") or "") for x in sl if x.get("symbol")}

    pool = sorted(s for s in (all_syms - etf_syms) if _CLEAN_TICKER.match(s))

    if verbose:
        try:
            act = {x["symbol"] for x in fetch_actively_trading(key)}
            alive = len([s for s in pool if s in act])
            print(f"havuz: {len(pool)} sembol  (yaşayan {alive} · artık işlem görmeyen {len(pool)-alive})",
                  flush=True)
        except FMPError:
            print(f"havuz: {len(pool)} sembol", flush=True)
    return pool, names


# =========================================================================
# 3) İNDİRME — hız sınırlı, yığınlı, anında budayan (RAM dostu)
# =========================================================================
# =========================================================================
# 3a) UYARLANIR HIZ SINIRLAYICI
# FMP planı 429 (Too Many Requests) döndürüyor ve Retry-After başlığı YOK
# (2026-08-21'de ölçüldü: 8 worker sürdürülen yükte %15 429). Limit belgesiz
# olduğu için tahmin etmek yerine ÖLÇEREK bulunur: 429 görünce hız düşer,
# temiz gidince yavaşça artar (AIMD — TCP tıkanıklık denetimiyle aynı fikir).
# =========================================================================
class RateLimiter:
    """Token-bucket + AIMD. Thread-safe."""

    def __init__(self, rpm=240.0, rpm_min=120.0, rpm_max=290.0):
        import threading
        self.rpm = float(rpm); self.rpm_min = float(rpm_min); self.rpm_max = float(rpm_max)
        self._lock = threading.Lock()
        self._next = time.time()
        self.hits_429 = 0
        self._ok_streak = 0

    def acquire(self):
        """Bir sonraki isteğe izin verilen ana kadar bekle."""
        with self._lock:
            now = time.time()
            gap = 60.0 / self.rpm
            start = max(now, self._next)
            self._next = start + gap
        d = start - time.time()
        if d > 0:
            time.sleep(d)

    def penalize(self):
        """429 → çarpımsal azaltma + kısa fren."""
        with self._lock:
            self.hits_429 += 1
            self._ok_streak = 0
            self.rpm = max(self.rpm_min, self.rpm * 0.85)
            self._next = max(self._next, time.time() + 2.0)

    def reward(self):
        """Uzun temiz seri → toplamsal artış."""
        with self._lock:
            self._ok_streak += 1
            if self._ok_streak >= 60:
                self._ok_streak = 0
                self.rpm = min(self.rpm_max, self.rpm + 20.0)


_EOD = "https://financialmodelingprep.com/stable/historical-price-eod/full"
_COLS = ["Open", "High", "Low", "Close", "Volume"]


def _peak_adv(close, vol, window=ADV_WINDOW):
    """Serinin GÖRDÜĞÜ EN YÜKSEK N-günlük ortalama dolar hacmi."""
    if len(close) < window:
        return 0.0
    dv = close * vol
    return float(pd.Series(dv).rolling(window, min_periods=window).mean().max() or 0.0)


def _download_one(sym, key, start, end, timeout=40, tries=4, keep_floor=0.0, limiter=None):
    """Tek sembol → OHLCV DataFrame | None.

    keep_floor > 0 ise: hiçbir zaman bu dolar-hacmine ulaşmamış sembol ANINDA
    atılır (None döner) — çağıran onu hiç biriktirmez. Bu bir look-ahead
    değildir: atılan sembol hiçbir günün maskesini zaten geçemezdi."""
    q = {"symbol": sym, "from": start, "to": end, "apikey": key}
    url = _EOD + "?" + _up.urlencode(q)
    for i in range(tries):
        if limiter is not None:
            limiter.acquire()
        try:
            req = _ur.Request(url, headers={"User-Agent": "swing2/1.0"})
            with _ur.urlopen(req, timeout=timeout) as r:
                raw = json.loads(r.read().decode("utf-8"))
            if limiter is not None:
                limiter.reward()
            break
        except Exception as e:
            code = getattr(e, "code", None)
            if code in (401, 402, 403):
                return ("PAYWALL", None)
            if code == 429:
                if limiter is not None:
                    limiter.penalize()
                time.sleep(1.5 * (i + 1))          # 429: sabırlı bekle, pes etme
                continue
            if i == tries - 1:
                return ("ERR", None)
            time.sleep(0.6 * (i + 1))
    else:
        return ("ERR", None)

    if not isinstance(raw, list) or not raw:
        return ("EMPTY", None)

    # TOPLU ayrıştırma. Satır-satır numpy ataması Python seviyesinde çok yavaştır ve
    # GIL'i uzun süre tutar → 8 thread'de kardeş isteklerin soketleri zaman aşımına
    # düşer (ölçüldü: %17,8 sahte "hata"). Sütun listesi + tek seferde dönüşüm bunu bitirir.
    try:
        dates = pd.to_datetime([b["date"] for b in raw]).values
        arr = np.array([[b.get("open"), b.get("high"), b.get("low"),
                         b.get("close"), b.get("volume")] for b in raw], dtype=np.float64)
    except Exception:
        return ("BADROW", None)
    arr[:, 4] = np.nan_to_num(arr[:, 4], nan=0.0)          # hacim eksikse 0
    order = np.argsort(dates, kind="stable")
    dates, arr = dates[order], arr[order].astype(np.float32)

    if keep_floor > 0.0:
        if _peak_adv(arr[:, 3].astype(np.float64), arr[:, 4].astype(np.float64)) < keep_floor:
            return ("THIN", None)          # anında at — RAM'e girmez

    df = pd.DataFrame(arr, index=pd.DatetimeIndex(dates), columns=_COLS)
    return ("OK", df)


def download_pool(symbols, start, end, key=None, workers=6, batch=500,
                  pause=0.0, keep_floor=MIN_DOLLAR_VOL, verbose=True,
                  rpm=300.0, limiter=None):
    """Havuzu yığınlar hâlinde indir; eşiği hiç görmemiş sembolleri anında ele.

    Yığın + pause = kaba hız sınırı (FMP tarafında ani yük yaratmamak için).
    Dönen: (frames dict, istatistik dict)."""
    key = key or _key()
    if not key:
        raise FMPError("FMP_API_KEY yok")
    frames = {}
    stat = {"OK": 0, "EMPTY": 0, "ERR": 0, "THIN": 0, "PAYWALL": 0, "BADROW": 0}
    failed = []
    limiter = limiter or RateLimiter(rpm=rpm)
    t0 = time.time()
    for b0 in range(0, len(symbols), batch):
        chunk = symbols[b0:b0 + batch]
        chunk_failed = []
        with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_download_one, s, key, start, end, keep_floor=keep_floor,
                              limiter=limiter): s for s in chunk}
            for f in _cf.as_completed(futs):
                s = futs[f]
                try:
                    tag, df = f.result()
                except Exception:
                    tag, df = "ERR", None
                stat[tag] = stat.get(tag, 0) + 1
                if df is not None:
                    frames[s] = df
                elif tag == "ERR":
                    chunk_failed.append(s)
        if stat["PAYWALL"] > 20:
            raise FMPError(f"PAYWALL {stat['PAYWALL']} kez — plan limiti aşıldı, indirme durdu")
        failed.extend(f for f in chunk_failed)
        done = b0 + len(chunk)
        if verbose:
            el = time.time() - t0
            print(f"  {done}/{len(symbols)}  tutulan={len(frames)}  "
                  f"ince={stat['THIN']} boş={stat['EMPTY']} hata={len(failed)}  "
                  f"{el/60:.0f}dk  (~{done/max(el,1e-9)*60:.0f}/dk · rpm={limiter.rpm:.0f} · "
                  f"429={limiter.hits_429})", flush=True)
        time.sleep(pause)

    # --- İKİNCİ ŞANS: hata alanları tek tek, yavaş ve sabırlı yeniden dene.
    # Aksi hâlde tek bir geçici ağ dalgalanması saatlerce süren indirmeyi çöpe atar.
    if failed:
        if verbose:
            print(f"  ikinci şans: {len(failed)} sembol (2 worker, sabırlı)", flush=True)
        still = []
        with _cf.ThreadPoolExecutor(max_workers=2) as ex:
            futs = {ex.submit(_download_one, s, key, start, end, timeout=60, tries=4,
                              keep_floor=keep_floor, limiter=limiter): s for s in failed}
            for f in _cf.as_completed(futs):
                s = futs[f]
                try:
                    tag, df = f.result()
                except Exception:
                    tag, df = "ERR", None
                if df is not None:
                    frames[s] = df; stat["OK"] += 1; stat["ERR"] -= 1
                elif tag == "ERR":
                    still.append(s)
                else:
                    stat[tag] = stat.get(tag, 0) + 1; stat["ERR"] -= 1
        failed = still
        if verbose:
            print(f"  ikinci şans sonrası kalan hata: {len(failed)}", flush=True)

    stat["ERR"] = len(failed)
    stat["rpm_final"] = round(limiter.rpm, 1)
    stat["hits_429"] = limiter.hits_429
    stat["failed_symbols"] = failed[:200]
    err_rate = len(failed) / max(1, len(symbols))
    if err_rate > 0.02:                                  # fail-closed
        raise FMPError(f"hata oranı %{100*err_rate:.1f} (>%2) — veri güvenilmez, durduruldu")
    return frames, stat


# =========================================================================
# 4) VEKTÖREL POINT-IN-TIME MASKE  (for-loop YOK)
# =========================================================================
def to_panel(frames, calendar):
    """{sym: OHLCV df} → geniş float32 matrisler (index=takvim, columns=semboller).

    Dict-of-DataFrame yerine geniş matris: 4000 sembol × 1400 gün için pandas
    nesne yükü olmadan ~22 MB/matris. Fill YOK — olmayan bar NaN kalır."""
    syms = sorted(frames)
    cal = pd.DatetimeIndex(calendar)
    # Sütun sütun atama (df[s] = ...) pandas'ta her seferinde yeniden tahsis eder →
    # 4000 sütunda O(n²). Sözlükte toplayıp TEK seferde kurmak bunu O(n) yapar.
    c_cols, v_cols = {}, {}
    for s in syms:
        d = frames[s]
        d = d[~d.index.duplicated(keep="last")]
        c_cols[s] = d["Close"].reindex(cal).to_numpy(dtype=np.float32)
        v_cols[s] = d["Volume"].reindex(cal).to_numpy(dtype=np.float32)
    close = pd.DataFrame(c_cols, index=cal, columns=syms, copy=False)
    vol = pd.DataFrame(v_cols, index=cal, columns=syms, copy=False)
    return close, vol


def pit_mask(close, volume, min_price=MIN_PRICE, min_dollar_vol=MIN_DOLLAR_VOL,
             adv_window=ADV_WINDOW, min_history=MIN_HISTORY, causal_shift=1):
    """Günlük Point-in-Time uygunluk maskesi — tamamen vektörel.

    Şartlar (hepsi aynı anda):
      • fiyat      : Close >= min_price
      • likidite   : Close*Volume'ün adv_window-günlük SMA'sı >= min_dollar_vol
      • bütünlük   : o gün işlem görmüş (Close ve Volume NaN değil)
      • geçmiş     : en az min_history bar (SMA200 hesaplanabilir olmalı)

    causal_shift=1 → maskenin TAMAMI bir gün geriden. Bir günün uygunluğu
    yalnız ÖNCEKİ günlerin verisiyle belirlenir; fiyat eşiği dahil. Bu, gelecek
    sızıntısını yapısal olarak imkânsız kılar."""
    traded = close.notna() & volume.notna()
    dollar_vol = close.astype(np.float64) * volume.astype(np.float64)
    adv = dollar_vol.rolling(adv_window, min_periods=adv_window).mean()
    bars = traded.cumsum()

    m = (close >= min_price) & (adv >= min_dollar_vol) & (bars >= min_history) & traded
    if not causal_shift:
        return m
    return m.shift(causal_shift).astype(object).where(lambda x: x.notna(), False).astype(bool)


# =========================================================================
# 5) VEKTÖREL RS + İZLEME LİSTESİ  —  rs_universe ile BİREBİR
# =========================================================================
def rs_matrix(close, weights=(0.2, 0.4, 0.4), skip=5, windows=(21, 63, 126)):
    """rs_universe.rs_score()'un tüm (tarih × sembol) matrisi — tek seferde.

    Orijinal semantiği birebir korur:
      prior = closes[index < asof].dropna();  end = len(prior)-1-skip
      score = Σ wᵢ · (prior[end]/prior[end-winᵢ] − 1)

    Vektörleştirme: sembolün KENDİ (dropna'lı) serisinde f = Σ wᵢ(p/p.shift(winᵢ)−1)
    hesaplanır, g = f.shift(skip) alınır; sonra takvime reindex + shift(1) + ffill
    ile "d'den KESİNLİKLE önceki son bar" değeri okunur. Böylece tarih başına
    yeniden dilimleme (orijinalin O(gün×sembol) dilimi) ortadan kalkar.

    NOT (orijinalden devralınan davranış): ölmüş bir sembol son skorunu SONSUZA
    KADAR taşır (orijinal de taşır — prior hep dolu). Tek başına kullanılırsa
    ölü hisse listeye girebilir. Bu yüzden üretimde kapı olarak pit_mask()
    kullanılır: 'o gün işlem görmüş' şartı ölüyü kesin olarak eler."""
    cal = close.index
    need = max(windows) + skip + 1
    nan_col = np.full(len(cal), np.nan)
    cols = {}
    for s in close.columns:                      # sözlükte topla, tek seferde kur (O(n))
        p = close[s].dropna().astype(np.float64)
        if len(p) < need:
            cols[s] = nan_col
            continue
        f = None
        for w, win in zip(weights, windows):
            term = w * (p / p.shift(win) - 1.0)
            f = term if f is None else f + term
        g = f.shift(skip)
        cols[s] = g.reindex(cal).shift(1).ffill().to_numpy(dtype=np.float64)
    return pd.DataFrame(cols, index=cal, columns=close.columns, copy=False)


def legacy_dv_gate(close, volume, dollar_vol_floor, vol_window=21):
    """rs_universe.build_watchlist()'in likidite kapısının BİREBİR vektörel eşi.

      prior = df[df.index < date]                     (dropna YOK — takvim satırı)
      if len(prior) < vol_window: ele
      dv = (prior.Close*prior.Volume).tail(vol_window).mean()   (NaN atlar)
      geçer  <=>  dv >= floor

    Yalnız sadakat testi için. Üretimde pit_mask() kullanılır (bkz. ölü-sembol notu)."""
    if not dollar_vol_floor or dollar_vol_floor <= 0:
        return pd.DataFrame(True, index=close.index, columns=close.columns)
    dv = close.astype(np.float64) * volume.astype(np.float64)
    roll = dv.rolling(vol_window, min_periods=1).mean().shift(1)
    gate = roll >= dollar_vol_floor
    gate.iloc[:vol_window] = False                    # len(prior) < vol_window
    return gate.fillna(False)


def build_watchlist_fast(rs, gate, n=50):
    """{tarih: {sembol,...}} — kapıyı geçenler arasında RS top-n.

    Eşitlik bozma orijinalle aynı: ranked.sort(reverse=True) demek (skor, sembol)
    ikilisinde skor eşitse sembol adı BÜYÜKTEN küçüğe demektir. Sütunlar isme göre
    tersten sıralanıp kararlı (stable) argsort kullanılarak bu birebir taklit edilir."""
    cols = sorted(rs.columns, reverse=True)           # eşitlikte büyük isim önce
    R = rs[cols].to_numpy(dtype=np.float64, copy=True)
    G = gate[cols].to_numpy(dtype=bool, copy=False)
    R[~G] = np.nan                                    # kapıdan geçemeyen yarışa girmez
    valid = ~np.isnan(R)
    R_sort = np.where(valid, -R, np.inf)              # NaN'lar en sona
    idx = np.argsort(R_sort, axis=1, kind="stable")[:, :n]

    colarr = np.array(cols, dtype=object)
    out = {}
    for i, date in enumerate(rs.index):
        row = idx[i]
        row = row[valid[i, row]]                      # n'den az geçerli olabilir
        out[date] = set(colarr[row])
    return out


# =========================================================================
# 6) SADAKAT KAPISI — vektörel == orijinal, gün gün
# =========================================================================
def fidelity(market=None, cfg=None, verbose=True):
    """build_watchlist_fast, rs_universe.build_watchlist ile BİREBİR mi?
    Mevcut 373 sembollük canlı havuzda, 1300+ günün her birinde küme eşitliği."""
    import rs_universe as ru
    if market is None:
        import altguard_lab as ag
        ag.load_data()
        market, cfg = ag.MARKET, ag.base_cfg()

    pool = [s for s in (cfg.rs_pool or cfg.universe) if s in market["data"]]
    cal = pd.DatetimeIndex(market["calendar"])
    data = {s: market["data"][s] for s in pool}

    t0 = time.time()
    # DİKKAT: rs_universe.build_watchlist artık VEKTÖREL yola gidiyor (2026-08-21).
    # Bu kapının anlamlı kalması için referans AÇIKÇA eski uygulamadır.
    ref = ru.build_watchlist_slow(data, cal, n=cfg.rs_n, weights=cfg.rs_weights,
                             skip=cfg.rs_skip, windows=cfg.rs_windows,
                             dollar_vol_floor=cfg.rs_dollar_vol_floor)
    t_ref = time.time() - t0

    t0 = time.time()
    close = pd.DataFrame({s: data[s]["Close"].reindex(cal) for s in pool}, index=cal)
    vol = pd.DataFrame({s: data[s]["Volume"].reindex(cal) for s in pool}, index=cal)
    rs = rs_matrix(close, weights=cfg.rs_weights, skip=cfg.rs_skip, windows=cfg.rs_windows)
    gate = legacy_dv_gate(close, vol, cfg.rs_dollar_vol_floor)
    fast = build_watchlist_fast(rs, gate, n=cfg.rs_n)
    t_fast = time.time() - t0

    bad = [d for d in cal if ref.get(d, set()) != fast.get(d, set())]
    if verbose:
        print(f"havuz {len(pool)} sembol · {len(cal)} gün")
        print(f"  orijinal : {t_ref:7.2f}s")
        print(f"  vektörel : {t_fast:7.2f}s   ({t_ref/max(t_fast,1e-9):.0f}× hızlı)")
        if bad:
            print(f"  ❌ SADAKAT KIRIK — {len(bad)} gün farklı. İlk 3:")
            for d in bad[:3]:
                r, f = ref.get(d, set()), fast.get(d, set())
                print(f"     {d.date()}  yalnız-orijinal={sorted(r-f)[:6]}  yalnız-vektörel={sorted(f-r)[:6]}")
        else:
            print(f"  ✅ SADAKAT TAM — {len(cal)}/{len(cal)} gün birebir aynı")
    return (len(bad) == 0), bad


# =========================================================================
# 7) VERİ KALİTESİ — glitch teşhisi (SONUÇ-TARAFSIZ olmak zorunda)
# =========================================================================
# 31 bin sembollük havuz, 373 temiz büyük-hisse evreninden farklı: ters split,
# düzeltilmemiş kurumsal işlem ve OTC çöpü var. Tek sahte ×10 sıçrama momentum
# motorunda sahte bir kırılım + sahte bir kazanan üretip tüm sonucu domine
# edebilir.
#
# TUZAK: "tek günde %40'tan fazla oynayanı at" demek SONUÇ-YANLI olurdu —
# iflaslar çöker, onları atmak survivorship bias'ı arka kapıdan geri sokar.
# Tam da ölçmek istediğimiz şeyi silmiş oluruz.
#
# Bu yüzden ölçüt YÖNDEN BAĞIMSIZ ve tamamen mekanik: GİDİŞ-DÖNÜŞ sıçraması.
# Fiyat bir gün ≥1.6× fırlayıp ertesi gün geri iniyorsa (ya da tersi), bu bir
# fiyat hareketi değil, bozuk bir bardır. Gerçek çöküş geri gelmez; gerçek ralli
# ertesi gün yarıya inmez. Böylece iflas da satın alma da korunur.
def glitch_report(frames, up=1.6, down=0.625):
    """{sym: gidiş-dönüş sıçrama sayısı} (yalnız > 0 olanlar)."""
    out = {}
    for sym, df in frames.items():
        c = df["Close"].astype(np.float64)
        r = (c / c.shift(1)).to_numpy()
        if len(r) < 3:
            continue
        a, b = r[1:-1], r[2:]
        n = int(np.sum((a >= up) & (b <= down)) + np.sum((a <= down) & (b >= up)))
        if n:
            out[sym] = n
    return out


def drop_glitchy(frames, max_roundtrip=1, up=1.6, down=0.625, verbose=True):
    """Gidiş-dönüş sıçraması max_roundtrip'i AŞAN sembolleri havuzdan çıkar.

    Ölçüt yönden bağımsız olduğu için hayatta kalma yanılgısını geri getirmez;
    ölçtüğü tek şey serinin mekanik tutarlılığıdır."""
    g = glitch_report(frames, up=up, down=down)
    bad = {s for s, n in g.items() if n > max_roundtrip}
    if verbose:
        top = sorted(g.items(), key=lambda kv: -kv[1])[:10]
        print(f"  glitch: {len(g)} sembolde gidiş-dönüş var · {len(bad)} sembol atıldı "
              f"(> {max_roundtrip}) · en kötüler {top}", flush=True)
    return {k: v for k, v in frames.items() if k not in bad}, bad, g

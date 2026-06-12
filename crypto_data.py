# -*- coding: utf-8 -*-
"""crypto_data — Binance spot günlük OHLCV + evren seçimi (kripto backtest veri katmanı).

Kaynak: Binance public klines (anahtar GEREKMEZ). Önce coğrafi-kısıtsız market-data
aynası (data-api.binance.vision), hata olursa api.binance.com'a düşer.

Sözleşme `fetch_daily_fmp` ile birebir: fetch_daily_binance(symbols, dl_start, dl_end)
→ {sym: OHLCV DataFrame (artan, tz-naive günlük indeks) | None}. Günlük bar UTC 00:00
açılışlıdır; OLUŞMAKTA OLAN (kapanmamış) bar HER ZAMAN atılır → önbellek idempotent.

Evren: top-N USDT spot çifti; stablecoin/kaldıraçlı(UP-DOWN-BULL-BEAR)/wrapped hariç.
Sıralama 24s hacim yerine 30g MEDYAN quote-hacim (gürültüye dayanıklı). Tekrarlanabilirlik
için liste crypto_universe_pinned.json'a sabitlenir (commit edilir).

CLI:
  python3 crypto_data.py refresh-universe --top 75 [--min-history 400] [--out PATH]
  python3 crypto_data.py check BTCUSDT [--date 2024-01-01]
"""
from __future__ import annotations
import os
import json
import time
import argparse
import concurrent.futures as _cf
from typing import Dict, List, Optional

import requests
import pandas as pd

BINANCE_BASE = "https://data-api.binance.vision/api/v3"   # coğrafi-kısıtsız ayna
BINANCE_FALLBACK = "https://api.binance.com/api/v3"

OHLCV = ["Open", "High", "Low", "Close", "Volume"]

# --- Evren dışı bırakılanlar -------------------------------------------------
STABLE_BASES = {"USDC", "FDUSD", "TUSD", "DAI", "BUSD", "USDP", "PYUSD", "GUSD",
                "EUR", "EURI", "AEUR", "USTC", "USDE", "USD1", "USDS", "RLUSD",
                "XUSD", "USDT"}
WRAPPED_BASES = {"WBTC", "WBETH", "WETH", "CBETH", "STETH", "WSTETH", "BETH",
                 "BNSOL", "RETH"}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")   # yalnız len(base)>=5 iken (JUP'u koruma)

DEFAULT_PIN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "crypto_universe_pinned.json")


def _is_leveraged(base: str) -> bool:
    """BTCUP/ETHDOWN gibi BLVT adları; JUP gibi kısa adlar yanlış elenmesin."""
    return len(base) >= 5 and base.endswith(LEVERAGED_SUFFIXES)


# =========================================================================
# HTTP (retry + ayna→ana site düşüşü)
# =========================================================================
def _get_json(path: str, params: Optional[dict] = None, timeout: float = 15,
              tries: int = 3):
    """GET BASE+path; 429/418'de Retry-After kadar bekle; ayna hata verirse
    api.binance.com'a düş. Tüm denemeler biterse exception fırlatır."""
    last = None
    for base in (BINANCE_BASE, BINANCE_FALLBACK):
        for _ in range(tries):
            try:
                r = requests.get(base + path, params=params or {}, timeout=timeout,
                                 headers={"User-Agent": "swing2-crypto/1.0"})
                if r.status_code in (429, 418):           # ağırlık limiti / ban
                    time.sleep(float(r.headers.get("Retry-After", 10)))
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last = e
                time.sleep(0.4)
    raise last if last else RuntimeError(f"GET {path} başarısız")


# =========================================================================
# KLINES (sayfalı indirme; oluşan bar atılır)
# =========================================================================
def fetch_klines_binance(symbol: str, interval: str = "1d",
                         start_ms: Optional[int] = None,
                         end_ms: Optional[int] = None,
                         limit: int = 1000) -> Optional[pd.DataFrame]:
    """Sayfalı /klines → OHLCV DataFrame (artan, tz-naive günlük indeks) | None.
    KRİTİK: closeTime şu andan ileride olan (kapanmamış) bar HER ZAMAN atılır.
    Ek kolon QuoteVolume (alan 7) evren sıralamasında kullanılır."""
    rows: List[list] = []
    cur = start_ms
    while True:
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        if cur is not None:
            params["startTime"] = int(cur)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        try:
            batch = _get_json("/klines", params)
        except Exception:
            return None
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < limit:
            break
        cur = batch[-1][0] + 1                         # son openTime + 1ms
    if not rows:
        return None
    now_ms = int(time.time() * 1000)
    rows = [b for b in rows if b[6] < now_ms]          # oluşan barı at
    if not rows:
        return None
    df = pd.DataFrame({
        "date": pd.to_datetime([b[0] for b in rows], unit="ms").normalize(),
        "Open": [float(b[1]) for b in rows], "High": [float(b[2]) for b in rows],
        "Low": [float(b[3]) for b in rows], "Close": [float(b[4]) for b in rows],
        "Volume": [float(b[5]) for b in rows],
        "QuoteVolume": [float(b[7]) for b in rows],
    }).set_index("date").sort_index()
    return df[~df.index.duplicated(keep="last")]


# =========================================================================
# DİSK ÖNBELLEK (sembol başına CSV; yalnız KAPANMIŞ barlar → idempotent)
# =========================================================================
def _ms(ts: pd.Timestamp) -> int:
    return int(pd.Timestamp(ts).value // 10**6)


def _cache_paths(cache_dir: str, symbol: str):
    safe = symbol.upper().replace("/", "_")
    return (os.path.join(cache_dir, f"{safe}_1d.csv"),
            os.path.join(cache_dir, f"{safe}_1d.meta.json"))


def _read_cache(path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(path):
        return None
    try:
        d = pd.read_csv(path, parse_dates=["date"], index_col="date")
        return d if len(d) else None
    except Exception:
        return None


def _write_cache(path: str, meta_path: str, df: pd.DataFrame, fetched_from: str):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path, index_label="date")
        with open(meta_path, "w") as f:
            json.dump({"fetched_from": fetched_from}, f)
    except Exception:
        pass


def _fetch_one_cached(symbol: str, dl_start: Optional[str], dl_end: Optional[str],
                      cache_dir: str) -> Optional[pd.DataFrame]:
    """Önbellekli tek sembol. Önbellek istenen başlangıcı kapsıyorsa yalnız KUYRUK
    çekilir (max+1g→); kapsamıyorsa tam indirme. meta.fetched_from, geç listelenen
    coinlerde (ilk bar > dl_start) gereksiz tam-indirme tekrarını önler."""
    path, meta_path = _cache_paths(cache_dir, symbol)
    cached = _read_cache(path)
    start_ts = pd.Timestamp(dl_start) if dl_start else None
    covered = False
    if cached is not None and start_ts is not None:
        covered = cached.index.min() <= start_ts
        if not covered and os.path.exists(meta_path):   # geç listelenen coin?
            try:
                ff = json.load(open(meta_path)).get("fetched_from", "9999")
                covered = pd.Timestamp(ff) <= start_ts
            except Exception:
                pass
    if cached is not None and covered:
        tail_start = cached.index.max() + pd.Timedelta(days=1)
        tail = fetch_klines_binance(symbol, start_ms=_ms(tail_start))
        if tail is not None and len(tail):
            cached = pd.concat([cached, tail]).sort_index()
            cached = cached[~cached.index.duplicated(keep="last")]
            old_ff = json.load(open(meta_path)).get("fetched_from") if os.path.exists(meta_path) else None
            _write_cache(path, meta_path, cached, old_ff or str(cached.index.min().date()))
        df = cached
    else:
        df = fetch_klines_binance(symbol, start_ms=_ms(start_ts) if start_ts is not None else None)
        if df is None:
            return None
        _write_cache(path, meta_path, df, dl_start or str(df.index.min().date()))
    if df is None or not len(df):
        return None
    out = df.loc[(df.index >= start_ts) if start_ts is not None else slice(None)]
    if isinstance(out, pd.DataFrame) and dl_end:
        out = out[out.index <= pd.Timestamp(dl_end)]
    return out[OHLCV].astype(float) if len(out) else None


def fetch_daily_binance(symbols: List[str], dl_start: Optional[str],
                        dl_end: Optional[str], workers: int = 6,
                        cache_dir: str = "swing2_cache/binance",
                        ) -> Dict[str, Optional[pd.DataFrame]]:
    """Tüm sembolleri eşzamanlı indir → {sym: OHLCV DataFrame | None}.
    fetch_daily_fmp sözleşmesinin aynısı: toplam bütçe aşılırsa kalanlar None."""
    frames: Dict[str, Optional[pd.DataFrame]] = {s: None for s in symbols}
    ex = _cf.ThreadPoolExecutor(max_workers=workers)
    fut = {ex.submit(_fetch_one_cached, s, dl_start, dl_end, cache_dir): s
           for s in symbols}
    budget = 45 + 1.2 * len(symbols)
    try:
        for f in _cf.as_completed(fut, timeout=budget):
            s = fut[f]
            try:
                frames[s] = f.result()
            except Exception:
                frames[s] = None
    except _cf.TimeoutError:
        miss = [s for s, v in frames.items() if v is None]
        print(f"⚠️ Binance indirme bütçesi ({budget:.0f}s) aşıldı — eksik: "
              f"{', '.join(miss[:12])}" + (" ..." if len(miss) > 12 else ""), flush=True)
    ex.shutdown(wait=False, cancel_futures=True)
    return frames


# =========================================================================
# EVREN SEÇİMİ (top-N USDT; 30g medyan quote-hacim sıralı)
# =========================================================================
def build_universe(top_n: int = 75, quote: str = "USDT",
                   min_history_bars: int = 400, candidates: int = 180) -> dict:
    """1) exchangeInfo: TRADING + spot + quote eşleşen çiftler
       2) stablecoin / wrapped / kaldıraçlı dışla
       3) 24s quote-hacme göre ilk `candidates` aday
       4) aday başına son `min_history_bars` günlük bar (1 istek) → kısa geçmiş elenir;
          metrik = son 30 barın MEDYAN quote-hacmi (24s sayıdan kararlı)
       5) metriğe göre yeniden sırala → top_n"""
    info = _get_json("/exchangeInfo")
    excluded = {"stable": [], "wrapped": [], "leveraged": []}
    eligible = {}
    for s in info.get("symbols", []):
        if (s.get("status") != "TRADING" or s.get("quoteAsset") != quote
                or not s.get("isSpotTradingAllowed", False)):
            continue
        base, sym = s["baseAsset"], s["symbol"]
        if base in STABLE_BASES:
            excluded["stable"].append(sym); continue
        if base in WRAPPED_BASES:
            excluded["wrapped"].append(sym); continue
        if _is_leveraged(base):
            excluded["leveraged"].append(sym); continue
        eligible[sym] = base

    tick = _get_json("/ticker/24hr")
    vol24 = {t["symbol"]: float(t.get("quoteVolume") or 0)
             for t in tick if t["symbol"] in eligible}
    cand = sorted(vol24, key=vol24.get, reverse=True)[:candidates]

    print(f"Aday: {len(cand)} sembol · geçmiş kontrolü ({min_history_bars} bar) ...",
          flush=True)
    scored = []
    def _score(sym):
        df = fetch_klines_binance(sym, limit=min(max(min_history_bars, 30) + 5, 1000))
        if df is None or len(df) < min_history_bars:
            return None
        return (sym, float(df["QuoteVolume"].tail(30).median()))
    ex = _cf.ThreadPoolExecutor(max_workers=6)
    for r in ex.map(_score, cand):
        if r is not None:
            scored.append(r)
    ex.shutdown()
    scored.sort(key=lambda x: x[1], reverse=True)
    symbols = [s for s, _ in scored[:top_n]]

    return {"symbols": symbols,
            "excluded": excluded,
            "meta": {"generated_utc": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M"),
                     "quote": quote, "top_n": top_n,
                     "min_history_bars": min_history_bars,
                     "ranking": "median 30d quoteVolume",
                     "candidates_checked": len(cand),
                     "passed_history": len(scored)}}


def save_pinned_universe(result: dict, path: str = DEFAULT_PIN) -> None:
    with open(path, "w") as f:
        json.dump({**result["meta"], "excluded": result["excluded"],
                   "symbols": result["symbols"]}, f, indent=1, ensure_ascii=False)
    print(f"Evren yazıldı: {path} · {len(result['symbols'])} sembol")


def load_pinned_universe(path: str = DEFAULT_PIN) -> tuple:
    """Commit edilmiş JSON'dan sembol listesi (ağ erişimi YOK)."""
    with open(path) as f:
        return tuple(json.load(f)["symbols"])


# =========================================================================
# CLI
# =========================================================================
def _cmd_refresh(args):
    res = build_universe(top_n=args.top, min_history_bars=args.min_history)
    save_pinned_universe(res, args.out)
    syms = res["symbols"]
    assert "BTCUSDT" in syms and "ETHUSDT" in syms, "BTC/ETH evrende yok?!"
    print(f"İlk 10: {', '.join(syms[:10])}")
    print(f"Elenen: stable={len(res['excluded']['stable'])} · "
          f"wrapped={len(res['excluded']['wrapped'])} · "
          f"leveraged={len(res['excluded']['leveraged'])}")


def _cmd_check(args):
    df = fetch_klines_binance(args.symbol)
    if df is None:
        raise SystemExit(f"{args.symbol}: veri alınamadı")
    print(f"{args.symbol}: {len(df)} bar · {df.index[0].date()} → {df.index[-1].date()}")
    print(df.head(3).to_string(), "\n...\n", df.tail(3).to_string(), sep="")
    gaps = int((df.index.to_series().diff().dropna() != pd.Timedelta(days=1)).sum())
    last_closed = df.index[-1] < pd.Timestamp.now("UTC").tz_localize(None).normalize()
    ohlc_ok = bool(((df[["Open", "High", "Low", "Close"]] > 0).all().all())
                   and (df["High"] >= df["Low"]).all())
    print(f"İnvaryantlar: boşluk={gaps} · son bar kapanmış={last_closed} · OHLC sağlıklı={ohlc_ok}")
    if args.date:
        ts = pd.Timestamp(args.date)
        if ts in df.index:
            print(f"{args.date}: {df.loc[ts, OHLCV].to_dict()}")
        else:
            print(f"{args.date}: bar yok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Binance kripto veri katmanı")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh-universe", help="top-N evreni yeniden oluştur ve sabitle")
    r.add_argument("--top", type=int, default=75)
    r.add_argument("--min-history", type=int, default=400)
    r.add_argument("--out", default=DEFAULT_PIN)
    r.set_defaults(fn=_cmd_refresh)
    c = sub.add_parser("check", help="tek sembol veri doğrulama")
    c.add_argument("symbol")
    c.add_argument("--date", default=None)
    c.set_defaults(fn=_cmd_check)
    a = ap.parse_args()
    a.fn(a)

# -*- coding: utf-8 -*-
"""qswing — Financial Modeling Prep (STABLE API) veri çekme + disk önbellek (async httpx).

Not: 2025-08 sonrası FMP anahtarları yalnız /stable endpoint'lerini destekler (v3 legacy).
Ücretsiz plan sembol kümesini kısıtlar: büyük/likit hisseler + SPY açık; bazı ETF'ler
(QQQ) ve küçük hisseler 402 döndürür. QQQ alınamazsa rejim SPY'a göre değerlendirilir.
"""
from __future__ import annotations
import os
import json
import asyncio
from typing import Dict, List, Optional

import httpx

BASE = "https://financialmodelingprep.com/stable"
MAX_BARS = 250


class FetchError(Exception):
    pass


def _cache_path(cache_dir: str, ticker: str, slug: str, date: str) -> str:
    safe = ticker.upper().replace("/", "_")
    return os.path.join(cache_dir, f"{safe}_{slug}_{date}.json")


def _read_cache(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _write_cache(path: str, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


async def _get(client: httpx.AsyncClient, path: str, params: Dict, cache_path: str):
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached
    r = await client.get(BASE + path, params=params, timeout=30.0)
    if r.status_code >= 400:
        msg = ""
        try:
            msg = r.json().get("Error Message", "")[:80]
        except Exception:
            pass
        raise FetchError(f"HTTP {r.status_code} · {path}" + (f" — {msg}" if msg else ""))
    data = r.json()
    if data == [] or data is None:
        raise FetchError(f"Boş yanıt · {path}")
    _write_cache(cache_path, data)
    return data


def _hist_ascending(raw) -> List[Dict]:
    """STABLE eod (düz liste, en yeni-ilk) → en eski-ilk, son MAX_BARS bar."""
    if isinstance(raw, dict):           # eski v3 biçimi (önbellekte kalmışsa)
        raw = raw.get("historical", [])
    bars = [{"date": b["date"], "open": b.get("open"), "high": b.get("high"),
             "low": b.get("low"), "close": b.get("close"),
             "volume": b.get("volume") or 0} for b in (raw or [])]
    bars.sort(key=lambda b: b["date"])  # artan
    return bars[-MAX_BARS:]


async def _safe_history(client, ticker, api_key, cache_dir, date) -> Optional[List[Dict]]:
    """Yardımcı semboller (SPY/QQQ): hata/402 olursa None (üst katman karar verir)."""
    try:
        cp = _cache_path(cache_dir, ticker, "hist", date)
        raw = await _get(client, "/historical-price-eod/full",
                         {"symbol": ticker, "apikey": api_key}, cp)
        bars = _hist_ascending(raw)
        return bars or None
    except Exception:
        return None


async def prime_indices(api_key: str, cache_dir: str, date: str) -> None:
    """SPY & QQQ geçmişini bir kez çekip önbelleğe yaz (tarama öncesi; sonra
    her sembolün fetch_all'ı bunları diskten okur → tek HTTP, yarış yok)."""
    os.makedirs(cache_dir, exist_ok=True)
    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            _safe_history(client, "SPY", api_key, cache_dir, date),
            _safe_history(client, "QQQ", api_key, cache_dir, date),
        )


async def fetch_all(ticker: str, api_key: str, cache_dir: str, date: str) -> Dict:
    """Ticker + SPY + QQQ verisini eşzamanlı çek (STABLE)."""
    os.makedirs(cache_dir, exist_ok=True)
    tk = ticker.upper()
    async with httpx.AsyncClient() as client:
        quote_t = _get(client, "/quote", {"symbol": tk, "apikey": api_key},
                       _cache_path(cache_dir, tk, "quote", date))
        hist_t = _get(client, "/historical-price-eod/full",
                      {"symbol": tk, "apikey": api_key},
                      _cache_path(cache_dir, tk, "hist", date))
        prof_t = _get(client, "/profile", {"symbol": tk, "apikey": api_key},
                      _cache_path(cache_dir, tk, "profile", date))
        inc_t = _get(client, "/income-statement",
                     {"symbol": tk, "period": "quarter", "limit": 4, "apikey": api_key},
                     _cache_path(cache_dir, tk, "income", date))
        earn_t = _get(client, "/earnings", {"symbol": tk, "apikey": api_key},
                      _cache_path(cache_dir, tk, "earn", date))

        results = await asyncio.gather(quote_t, hist_t, prof_t, inc_t, earn_t,
                                       return_exceptions=True)
        quote, hist, prof, inc, earn = results
        # zorunlu: quote + hist (OHLCV). Bunlar 402 ise sembol bu planda kapalı.
        for nm, v in (("quote", quote), ("historical", hist)):
            if isinstance(v, Exception):
                raise FetchError(f"{tk} {nm}: {v}")
        # profile / income / earnings opsiyonel
        prof = prof if not isinstance(prof, Exception) else {}
        inc = inc if not isinstance(inc, Exception) else []
        earn = earn if not isinstance(earn, Exception) else []

        spy_bars, qqq_bars = await asyncio.gather(
            _safe_history(client, "SPY", api_key, cache_dir, date),
            _safe_history(client, "QQQ", api_key, cache_dir, date),
        )

    quote0 = quote[0] if isinstance(quote, list) and quote else (quote or {})
    prof0 = prof[0] if isinstance(prof, list) and prof else (prof or {})
    return {
        "ticker": tk,
        "quote": quote0,
        "bars": _hist_ascending(hist),
        "profile": prof0,
        "income": inc if isinstance(inc, list) else [],
        "earnings": earn if isinstance(earn, list) else [],
        "spy_bars": spy_bars,   # None olabilir
        "qqq_bars": qqq_bars,   # None olabilir (QQQ free planda 402)
    }

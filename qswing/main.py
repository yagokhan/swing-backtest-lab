# -*- coding: utf-8 -*-
"""qswing — CLI giriş noktası (argparse). Qullamaggie tarzı momentum/kırılım taraması."""
from __future__ import annotations
import os
import sys
import json
import asyncio
import argparse
import datetime as dt
from typing import Optional, Dict, List

from . import fetcher, calculator as calc, scorer, renderer


# ----------------------------------------------------------------------------- anahtar
def _load_dotenv(path: str = ".env"):
    if os.path.exists(path):
        try:
            for line in open(path):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass


def resolve_api_key(cli_key: Optional[str]) -> Optional[str]:
    if cli_key:
        return cli_key
    _load_dotenv()
    if os.environ.get("FMP_API_KEY"):
        return os.environ["FMP_API_KEY"]
    kp = os.path.expanduser("~/.portfolio_keys.json")
    if os.path.exists(kp):
        try:
            k = json.load(open(kp))
            return k.get("FMP_API_KEY") or k.get("FMP") or k.get("fmp")
        except Exception:
            return None
    return None


# ----------------------------------------------------------------------------- temel veriler
def fundamentals(income: List[Dict], earnings: List[Dict], quote: Dict,
                 asof: str) -> Dict:
    q = income[:4] if income else []
    rev = sum(_f(x.get("revenue")) for x in q)
    eps = sum(_f(x.get("eps")) for x in q)
    is_pre_rev = (len(q) > 0 and rev == 0)
    # sonraki bilanço: asof'tan sonraki en yakın tarih
    nexte = None
    cands = []
    for e in (earnings or []):
        d = str(e.get("date", ""))[:10]
        if d and d >= asof:
            cands.append(d)
    if cands:
        nexte = min(cands)
    elif quote.get("earningsAnnouncement"):
        ea = str(quote["earningsAnnouncement"])[:10]
        if ea >= asof:
            nexte = ea
    return {"revenue_ttm_m": rev / 1e6 if rev else 0.0, "eps_ttm": eps,
            "is_pre_revenue": is_pre_rev, "has_income": len(q) > 0,
            "next_earnings": nexte}


# ----------------------------------------------------------------------------- kilit seviyeler
def key_levels(bars: List[Dict], m: Dict) -> Dict:
    price = m["price"]
    res, sup = [], []
    if m.get("year_high"):
        res.append({"label": "52 Hafta Zirve", "value": m["year_high"]})
    if len(bars) >= 20:
        hi20 = max(float(b["high"]) for b in bars[-20:])
        lo20 = min(float(b["low"]) for b in bars[-20:])
        if hi20 > price:
            res.append({"label": "20 gün tepe", "value": hi20})
        if lo20 < price:
            sup.append({"label": "20 gün dip", "value": lo20})
    for lbl, key in (("EMA10", "ema10"), ("EMA20", "ema20"), ("SMA50", "sma50")):
        v = m.get(key)
        if v and v < price:
            sup.append({"label": lbl, "value": v})
    if m.get("year_low"):
        sup.append({"label": "52 Hafta Dip", "value": m["year_low"]})
    res = sorted(res, key=lambda r: r["value"])
    sup = sorted(sup, key=lambda r: r["value"], reverse=True)
    return {"resistance": res, "support": sup}


# ----------------------------------------------------------------------------- bağlam
def build_context(data: Dict, asof: str) -> Dict:
    quote = data["quote"]
    bars = data["bars"]
    spy_bars = data["spy_bars"]
    qqq_bars = data["qqq_bars"]
    spy_ok = bool(spy_bars)
    qqq_ok = bool(qqq_bars)
    year = int(asof[:4])

    # 52H yüksek/düşük: quote yoksa profile 'range' ("18.93-60.87") yedeği
    if quote.get("yearHigh") is None and data["profile"].get("range"):
        try:
            lo, hi = data["profile"]["range"].split("-")
            quote.setdefault("yearLow", float(lo)); quote.setdefault("yearHigh", float(hi))
        except Exception:
            pass

    m = calc.compute_metrics(bars, spy_bars or [], quote, year)
    stage = scorer.stage2_score(m)
    spy_reg = calc.regime_for(spy_bars) if spy_bars else {"healthy": False, "above50": False, "above200": False, "price": None, "sma50": None, "sma200": None}
    qqq_reg = calc.regime_for(qqq_bars) if qqq_bars else {"healthy": False, "above50": False, "above200": False, "price": None, "sma50": None, "sma200": None}
    gts = scorer.gates(m, spy_reg, qqq_reg, stage, spy_ok=spy_ok, qqq_ok=qqq_ok)
    vd = scorer.verdict(gts)
    fund = fundamentals(data["income"], data["earnings"], quote, asof)
    levels = key_levels(bars, m)

    prof = data["profile"]
    company = prof.get("companyName") or quote.get("name") or data["ticker"]
    exchange = prof.get("exchangeShortName") or quote.get("exchange") or "—"
    sector = prof.get("sector") or "—"

    # metrik tablosu satırları: (ad, değer-str, eşik, durum-pill)
    rows = _metric_rows(m)

    return {
        "ticker": data["ticker"], "date": asof,
        "company": company, "exchange": exchange, "sector": sector,
        "price": m["price"],
        "change_pct": _f(quote.get("changePercentage") or quote.get("changesPercentage")),
        "m": m, "stage": stage, "gates": gts, "verdict": vd,
        "spy_reg": spy_reg, "qqq_reg": qqq_reg, "spy_ok": spy_ok,
        "fund": fund, "levels": levels, "rows": rows,
        "gate_order": [
            ("regime", "1 · Piyasa Rejimi"),
            ("leadership", "2 · Liderlik (Görece Güç)"),
            ("stage2", "3 · Aşama 2 Trend"),
            ("tight", "4 · Sıkı Kurulum"),
            ("entry", "5 · Giriş & Risk"),
        ],
        "generated": asof,
        "source": "Financial Modeling Prep",
    }


def _pill(ok: Optional[bool], yes="✓", no="✗", neutral="nötr"):
    if ok is True:
        return {"cls": "green", "txt": yes}
    if ok is False:
        return {"cls": "red", "txt": no}
    return {"cls": "blue", "txt": neutral}


def _metric_rows(m: Dict) -> List[Dict]:
    R = renderer
    rows = [
        ("Fiyat", R.trnum(m["price"]), "—", _pill(None)),
        ("RSI(14)", R.trnum(m["rsi14"], 1), "40–70 sağlıklı",
         _pill(m["rsi14"] is not None and 40 <= m["rsi14"] <= 80)),
        ("ADR%", R.trpct(m["adr_pct"]), "≥%3 ideal",
         _pill(m["adr_pct"] is not None and m["adr_pct"] >= 3)),
        ("VDU (hacim kuruması)", R.trpct(m["vdu_ratio"]), "≤%70",
         _pill(m["vdu_ratio"] is not None and m["vdu_ratio"] <= 70)),
        ("Dolar hacmi (20g)", R.trmoney_m(m["dollar_vol_20d"]), "≥$20M likit",
         _pill(m["dollar_vol_20d"] is not None and m["dollar_vol_20d"] >= 20)),
        ("Getiri 1a", R.trsignedpct(m["ret_1m"]), "≤%15 sıkı",
         _pill(m["ret_1m"] is not None and m["ret_1m"] <= 15)),
        ("Getiri 3a", R.trsignedpct(m["ret_3m"]), "pozitif",
         _pill(m["ret_3m"] is not None and m["ret_3m"] > 0)),
        ("Getiri 6a", R.trsignedpct(m["ret_6m"]), "pozitif",
         _pill(m["ret_6m"] is not None and m["ret_6m"] > 0)),
        ("Getiri YTD", R.trsignedpct(m["ret_ytd"]), "—", _pill(None)),
        ("RS 3a (vs SPY)", R.trsignedpct(m["rs_3m"]), ">0 lider",
         _pill(m["rs_3m"] is not None and m["rs_3m"] > 0)),
        ("RS 6a (vs SPY)", R.trsignedpct(m["rs_6m"]), ">0 lider",
         _pill(m["rs_6m"] is not None and m["rs_6m"] > 0)),
        ("RS çizgisi 50g zirve", "Evet" if m["rs_line_50d_high"] else "Hayır", "Evet",
         _pill(m["rs_line_50d_high"])),
        ("52H zirveye uzaklık", R.trsignedpct(m["pct_from_high"]), "≥−%25",
         _pill(m["pct_from_high"] is not None and m["pct_from_high"] >= -25)),
        ("52H dipten yükseliş", R.trsignedpct(m["pct_from_low"]), "—", _pill(None)),
        ("SMA50 uzaması (ADR)", R.trnum(m["extension_adr"], 1), "≤7",
         _pill(m["extension_adr"] is not None and m["extension_adr"] <= 7)),
        ("SMA200" + (" (yaklaşık)" if m["sma200_approx"] else ""),
         R.trnum(m["sma200"]), "fiyat üstte",
         _pill(m["price_above_sma200"])),
    ]
    return [{"name": n, "value": v, "thr": t, "pill": p} for n, v, t, p in rows]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------------------- tek hisse
def _friendly_fetch_error(ticker: str, e: Exception) -> str:
    s = str(e)
    if "402" in s:
        return (f"'{ticker}' bu FMP planında kapalı (HTTP 402) — plan kapsamı dışı sembol.")
    if "403" in s:
        return (f"'{ticker}' erişilemez (HTTP 403) — anahtar legacy v3 için olabilir.")
    if "Boş yanıt" in s:
        return (f"'{ticker}' bulunamadı — sembol geçersiz ya da veri yok.")
    return f"'{ticker}' verisi çekilemedi — {e}"


def analyze_one(ticker: str, api_key: str, cache: str, asof: str, out: str) -> Dict:
    """Tek sembol: çek → metrik → skor → render. Sonuç/özet dict döndürür (hata yutulur)."""
    try:
        data = asyncio.run(fetcher.fetch_all(ticker, api_key, cache, asof))
    except fetcher.FetchError as e:
        return {"ticker": ticker.upper(), "ok": False, "error": _friendly_fetch_error(ticker.upper(), e)}
    except Exception as e:  # noqa
        return {"ticker": ticker.upper(), "ok": False, "error": f"beklenmeyen — {type(e).__name__}: {e}"}

    if len(data["bars"]) < 30:
        return {"ticker": ticker.upper(), "ok": False,
                "error": f"yetersiz fiyat verisi ({len(data['bars'])} bar)"}

    ctx = build_context(data, asof)
    path = renderer.render(ctx, out)
    summary = _summary_from_ctx(ctx, link=os.path.basename(path))
    return {"ticker": ctx["ticker"], "ok": True, "path": path,
            "spy_ok": ctx["spy_ok"], "n_bars": len(data["bars"]), "summary": summary}


def _summary_from_ctx(ctx: Dict, link: str) -> Dict:
    """Index satırı için özet (hem CLI dosya-linki hem sunucu canlı-linki ile)."""
    m, v = ctx["m"], ctx["verdict"]
    return {
        "ticker": ctx["ticker"], "company": ctx["company"],
        "price": ctx["price"], "change_pct": ctx["change_pct"],
        "verdict": v, "stage": ctx["stage"]["score"],
        "rs_3m": m["rs_3m"], "vdu": m["vdu_ratio"], "adr": m["adr_pct"],
        "pct_from_high": m["pct_from_high"], "rs50h": m["rs_line_50d_high"],
        "tight": ctx["gates"]["tight"]["status"],
        "entry": ctx["gates"]["entry"]["status"],
        "pre_rev": ctx["fund"]["is_pre_revenue"],
        "file": link,
    }


# ----------------------------------------------------------------------------- tarama (screener)
async def _scan_async(tickers, api_key, cache, asof, conc):
    await fetcher.prime_indices(api_key, cache, asof)   # SPY/QQQ önbelleğe
    sem = asyncio.Semaphore(conc)

    async def one(t):
        async with sem:
            try:
                return (t, await fetcher.fetch_all(t, api_key, cache, asof), None)
            except Exception as e:  # noqa
                return (t, None, e)

    return await asyncio.gather(*[one(t) for t in tickers])


def scan_index_html(tickers, asof: str = None, api_key: str = None, cache: str = None,
                    conc: int = 6, link_base: str = "/api/qswing?ticker=") -> str:
    """Bir sembol evrenini eşzamanlı tara → net duruşa göre sıralı index HTML (string).
    Her satır `link_base+SEMBOL`'e (canlı rapor endpoint'i) linklenir."""
    asof = asof or dt.date.today().isoformat()
    api_key = api_key or resolve_api_key(None)
    if not api_key:
        raise RuntimeError("FMP API anahtarı yok.")
    cache = cache or _DEFAULT_CACHE
    seen, uniq = set(), []
    for t in tickers:
        u = str(t).upper().strip()
        if u and u not in seen:
            seen.add(u); uniq.append(u)
    if not uniq:
        raise RuntimeError("Taranacak sembol yok.")

    raw = asyncio.run(_scan_async(uniq, api_key, cache, asof, conc))
    summaries, failed = [], []
    for t, data, err in raw:
        T = t.upper()
        if err is not None:
            failed.append({"ticker": T, "error": _friendly_fetch_error(T, err)})
            continue
        if not data or len(data["bars"]) < 30:
            failed.append({"ticker": T, "error": "yetersiz fiyat verisi"})
            continue
        try:
            ctx = build_context(data, asof)
            summaries.append(_summary_from_ctx(ctx, link=link_base + T))
        except Exception as e:  # noqa
            failed.append({"ticker": T, "error": f"hesap hatası: {e}"})
    return renderer.render_index_to_string(summaries, asof, failed=failed)


# ----------------------------------------------------------------------------- sunucu/inline
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CACHE = os.path.join(os.path.dirname(_PKG_DIR), "cache")


def generate_report_html(ticker: str, asof: str = None, api_key: str = None,
                         cache: str = None) -> str:
    """Tek sembol için rapor HTML'ini string döndür (serve.py / inline kullanım).
    Anahtar verilmezse resolve_api_key ile çözülür. Hata olursa istisna yükselir."""
    asof = asof or dt.date.today().isoformat()
    api_key = api_key or resolve_api_key(None)
    if not api_key:
        raise RuntimeError("FMP API anahtarı yok (FMP_API_KEY / ~/.portfolio_keys.json).")
    cache = cache or _DEFAULT_CACHE
    data = asyncio.run(fetcher.fetch_all(ticker, api_key, cache, asof))
    if len(data["bars"]) < 30:
        raise RuntimeError(f"yetersiz fiyat verisi ({len(data['bars'])} bar)")
    ctx = build_context(data, asof)
    return renderer.render_to_string(ctx)


# ----------------------------------------------------------------------------- CLI
def run(argv=None):
    ap = argparse.ArgumentParser(prog="qswing",
                                 description="Qullamaggie tarzı swing analizi → Türkçe HTML rapor.")
    ap.add_argument("tickers", nargs="+", help="Bir veya çok hisse sembolü (örn. NNE AAPL TSLA)")
    ap.add_argument("--api-key", default=None, help="FMP API anahtarı (yoksa env FMP_API_KEY / ~/.portfolio_keys.json)")
    ap.add_argument("--out", default="./reports/", help="Çıktı klasörü (varsayılan ./reports/)")
    ap.add_argument("--cache", default="./cache/", help="Önbellek klasörü (varsayılan ./cache/)")
    ap.add_argument("--date", default=None, help="Analiz tarihi YYYY-MM-DD (varsayılan bugün)")
    ap.add_argument("--open", action="store_true", help="Üretince tarayıcıda aç (çoklu ise index)")
    args = ap.parse_args(argv)

    asof = args.date or dt.date.today().isoformat()
    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print("HATA: FMP API anahtarı bulunamadı. --api-key ile verin veya "
              "FMP_API_KEY ortam değişkenini / ~/.portfolio_keys.json içine ekleyin.",
              file=sys.stderr)
        return 1

    # sembolleri normalize et + tekilleştir (sıra korunur)
    seen, tickers = set(), []
    for t in args.tickers:
        u = t.upper().strip()
        if u and u not in seen:
            seen.add(u); tickers.append(u)

    results = [analyze_one(t, api_key, args.cache, asof, args.out) for t in tickers]

    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    for r in ok:
        s = r["summary"]; v = s["verdict"]
        print(f"✓ {r['ticker']:6s} {v['emoji']} {v['label']:5s} · Aşama {s['stage']}/5 · "
              f"{r['n_bars']} bar → {r['path']}")
    for r in bad:
        print(f"✗ {r['ticker']:6s} — {r['error']}", file=sys.stderr)

    open_path = ok[0]["path"] if ok else None
    if len(tickers) > 1 and ok:
        idx = renderer.render_index([r["summary"] for r in ok], args.out, asof,
                                    failed=[{"ticker": r["ticker"], "error": r["error"]} for r in bad])
        print(f"\n📑 Index: {idx}  ({len(ok)} rapor"
              + (f", {len(bad)} hata" if bad else "") + ")")
        open_path = idx

    if args.open and open_path:
        try:
            import webbrowser
            webbrowser.open("file://" + os.path.abspath(open_path))
        except Exception:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())

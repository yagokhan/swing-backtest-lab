#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 ML ÖZELLİK LABORATUVARI — "günlük barın dışı" 3 hipotez ailesi (feature ablation).

ml_backfill boru hattına DOKUNMAZ; gölge günlüğünü (etiketli 4.4k aday-gün) okur,
yeni özellik ailelerini vectorize hesaplar ve AYNI purged walk-forward tezgâhında
aile aile test eder (ablation). Sonuç: terminale tablo + model_meta.json["feature_lab"].

Aileler:
  H1 VCP/taban   : base_depth_pct (63g tepe-dip derinliği, kırılım GÜNÜ HARİÇ),
                   consolidation_days (63g zirvesinin %5 bandında ardışık gün),
                   volume_dryup_count (son 15 günde hacim<0.5×SMA50 sayısı) — hepsi shift(1)
  H2 Sektör RS   : sector_rs_20 (hisse 20g getirisi − sektör ETF 20g getirisi, yüzde puan;
                   oran yerine fark: payda sıfıra yaklaşınca oran patlar). Eşleme: motor
                   SECTOR_MAP (95, el yapımı; SMH/IGV inceliğiyle ÖNCELİKLİ) + FMP profile
                   sektörü → SPDR ETF (kalan ~230 sembol; ~/.swing_ml/sector_map.json cache)
  H3 Katalizör   : days_since_earnings (son bilançodan bu yana gün),
                   earnings_gap_pct (bilanço tepki barının açılış boşluğu %; BMO/AMC
                   bilinmediğinden rapor günü ile ertesi bar'dan |gap|'i büyük olan —
                   YALNIZ asof'tan eski barlar → lookahead yok).
                   Kaynak: FMP /stable/earnings (~/.swing_ml/earnings_cache.json cache)

Kullanım: python3 ml_feature_lab.py [--refresh]  (--refresh = cache'leri yeniden çek)
"""
import argparse
import bisect
import concurrent.futures as cf
import json
import os
import pickle
from collections import OrderedDict
from datetime import date, datetime
from urllib.request import urlopen

import numpy as np
import pandas as pd

import ml_backfill as bf
import ml_shadow_report as m
import qulla_paper as qp
import swing2_backtest as s

SECTOR_CACHE = os.path.join(m.ML_DIR, "sector_map.json")
EARN_CACHE   = os.path.join(m.ML_DIR, "earnings_cache.json")
ETF_CACHE    = os.path.join(m.ML_DIR, "etf_extra.pkl")

FMP_SECTOR_TO_ETF = {
    "Technology": "XLK", "Communication Services": "XLC",
    "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP",
    "Energy": "XLE", "Financial Services": "XLF", "Healthcare": "XLV",
    "Industrials": "XLI", "Basic Materials": "XLB",
    "Real Estate": "XLRE", "Utilities": "XLU",
}

F_VCP = ["base_depth_pct", "consolidation_days", "volume_dryup_count"]
F_SEC = ["sector_rs_20"]
F_CAT = ["days_since_earnings", "earnings_gap_pct"]
F_I2H = ["first_2h_vol_ratio", "first_2h_close_strength"]
INTRA_CACHE = os.path.join(m.ML_DIR, "intraday_2h_cache.json")
# H5: günün 1h bar YAPISI (7 bar; sinyal/etiket zaten tamamlanmış günlük bara dayalı →
# tam-gün saatlik ayrıştırma aynı bilgi kümesinin incesi, lookahead değil)
F_H5 = ["pm_vol_share", "ret_pm_pct", "high_hour_pos", "close_vs_vwap_pct",
        "hold_above_break", "trend_efficiency"]
INTRA1H_CACHE = os.path.join(m.ML_DIR, "intraday_1h_cache.json")


def _fmp(path, sym, key, tries=3, **params):
    """FMP çağrısı — rate-limit'e karşı bekleyerek tekrar dener (burst'te 429 yiyor)."""
    import time
    from urllib.parse import urlencode
    q = urlencode({"symbol": sym, "apikey": key, **params})
    for i in range(tries):
        try:
            with urlopen(f"https://financialmodelingprep.com/stable/{path}?{q}", timeout=25) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def _threaded_fetch(symbols, fn, workers=6, tag=""):
    out = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, t): t for t in symbols}
        for f in cf.as_completed(futs):
            t = futs[f]
            try:
                out[t] = f.result()
            except Exception:
                out[t] = None
    bad = sum(1 for v in out.values() if v is None)
    if bad:
        print(f"  ⚠️ {tag}: {bad}/{len(symbols)} sembol çekilemedi (NaN kalır)")
    return out


# ------------------------------------------------------------ H2: sektör haritası
def build_sector_map(symbols, refresh=False):
    """Motor SECTOR_MAP öncelikli; kalanlar FMP profile sektörü → SPDR ETF (disk cache)."""
    cache = {}
    if not refresh and os.path.exists(SECTOR_CACHE):
        cache = json.load(open(SECTOR_CACHE))
    smap = {t: s.SECTOR_MAP[t] for t in symbols if t in s.SECTOR_MAP}
    missing = [t for t in symbols if t not in smap and t not in cache]
    if missing:
        key = s._fmp_key()
        print(f"• FMP profile: {len(missing)} sembol için sektör çekiliyor…", flush=True)
        got = _threaded_fetch(missing, lambda t: _fmp("profile", t, key), tag="profile")
        for t, d in got.items():
            sec = (d[0].get("sector") or "") if d else ""
            cache[t] = FMP_SECTOR_TO_ETF.get(sec, "")
        os.makedirs(m.ML_DIR, exist_ok=True)
        json.dump(cache, open(SECTOR_CACHE, "w"), ensure_ascii=False, indent=0)
    smap.update({t: e for t, e in cache.items() if e and t in symbols and t not in smap})
    return smap


def etf_closes(needed_etfs, frames, refresh=False):
    """Depoda olmayan ETF'leri (XLB/XLRE/XLU) bir kez FMP'den çek, pkl cache'le."""
    out = {e: frames[e]["Close"] for e in needed_etfs if e in frames}
    miss = [e for e in needed_etfs if e not in out]
    if miss:
        extra = {}
        if not refresh and os.path.exists(ETF_CACHE):
            extra = pickle.load(open(ETF_CACHE, "rb"))
        todo = [e for e in miss if e not in extra]
        if todo:
            print(f"• Depoda olmayan ETF'ler FMP'den çekiliyor: {todo}", flush=True)
            got = s.fetch_daily_fmp(todo, s._fmp_key(), "2019-06-01", date.today().isoformat())
            extra.update({e: df for e, df in got.items() if df is not None and len(df)})
            pickle.dump(extra, open(ETF_CACHE, "wb"))
        out.update({e: df["Close"] for e, df in extra.items() if e in miss})
    return out


# ------------------------------------------------------------ H3: bilanço tarihleri
def build_earnings(symbols, refresh=False):
    """{sym: sıralı bilanço tarih listesi} — FMP /stable/earnings, disk cache."""
    cache = {}
    if not refresh and os.path.exists(EARN_CACHE):
        cache = json.load(open(EARN_CACHE))
    # boş liste = muhtemel eski BAŞARISIZ çekim (zehirli cache) → yeniden dene
    missing = [t for t in symbols if not cache.get(t)]
    if missing:
        key = s._fmp_key()
        print(f"• FMP earnings: {len(missing)} sembol çekiliyor (yavaş, retry'lı)…", flush=True)
        got = _threaded_fetch(missing, lambda t: _fmp("earnings", t, key), workers=3, tag="earnings")
        for t, d in got.items():
            if d is not None:                 # başarısızı CACHE'LEME → sonraki koşu tekrar dener
                cache[t] = sorted({x["date"] for x in d if x.get("date")})
        os.makedirs(m.ML_DIR, exist_ok=True)
        json.dump(cache, open(EARN_CACHE, "w"), indent=0)
    return {t: cache.get(t, []) for t in symbols}


# ------------------------------------------------------------ özellik hesapları
def vcp_series(f):
    """H1 — hepsi kırılım gününü DIŞLAR (shift 1): taban karakteri girişten öncedir."""
    hi63 = f["High"].rolling(63).max()
    base_depth = ((hi63 - f["Low"].rolling(63).min()) / hi63 * 100).shift(1)
    near = f["Close"] >= 0.95 * hi63                       # zirvenin %5 bandı
    consec = near.astype(int).groupby((~near).cumsum()).cumsum()
    dry = ((f["Volume"] < 0.5 * f["Volume"].rolling(50).mean())
           .astype(float).rolling(15).sum().shift(1))
    return pd.DataFrame({"base_depth_pct": base_depth,
                         "consolidation_days": consec.shift(1),
                         "volume_dryup_count": dry})


def sector_rs_series(f, etf_close):
    """H2 — 20g getiri farkı (yüzde puan); ETF kapanışı hisse takvimine hizalanır."""
    e = etf_close.reindex(f.index).ffill()
    return ((f["Close"] / f["Close"].shift(20) - 1) - (e / e.shift(20) - 1)) * 100


def earn_features(f, edates, asof):
    """H3 — (days_since, gap_pct). Tepki barı adayları: rapor günü barı ve ERTESİ bar
    (BMO/AMC belirsiz) → |gap| büyük olan; YALNIZ asof ve öncesi barlar (lookahead yok)."""
    if not edates:
        return np.nan, np.nan
    a = asof.strftime("%Y-%m-%d")
    i = bisect.bisect_right(edates, a) - 1
    if i < 0:
        return np.nan, np.nan
    ed = pd.Timestamp(edates[i])
    days = (asof - ed).days
    idx = f.index
    j = idx.searchsorted(ed)
    gaps = []
    for k in (j, j + 1):
        if 0 < k < len(idx) and idx[k] <= asof:
            pc, op = f["Close"].iloc[k - 1], f["Open"].iloc[k]
            if pc and pc == pc and op == op:
                gaps.append((op / pc - 1) * 100)
    return days, (max(gaps, key=abs) if gaps else np.nan)


def enrich(df, frames, refresh=False):
    """Gölge günlüğü DataFrame'ine 3 yeni aileyi ekle (sembol başına tek vectorize geçiş)."""
    syms = sorted(df["symbol"].unique())
    smap = build_sector_map(syms, refresh)
    n_map = df["symbol"].isin(smap).mean()
    etfc = etf_closes(sorted(set(smap.values())), frames, refresh)
    earns = build_earnings(syms, refresh)
    n_earn = np.mean([bool(earns.get(t)) for t in df["symbol"]])
    print(f"• kapsam: sektör %{n_map*100:.0f} · bilanço %{n_earn*100:.0f} (satır bazında)", flush=True)

    rows = []
    for sym, g in df.groupby("symbol"):
        f = frames.get(sym)
        if f is None:
            continue
        vcp = vcp_series(f)
        sec = sector_rs_series(f, etfc[smap[sym]]) if smap.get(sym) in etfc else None
        ed = earns.get(sym) or []
        for r in g.itertuples():
            ts = r.asof_ts
            d = {"i": r.Index}
            if ts in vcp.index:
                d.update(vcp.loc[ts].to_dict())
            d["sector_rs_20"] = float(sec.loc[ts]) if (sec is not None and ts in sec.index) else np.nan
            d["days_since_earnings"], d["earnings_gap_pct"] = earn_features(f, ed, ts)
            rows.append(d)
    ex = pd.DataFrame(rows).set_index("i")
    return df.join(ex, how="inner")


# ------------------------------------------------------------ H4: intraday 2h (lite)
def fetch_intraday_2h(pairs, refresh=False):
    """T=0 (kırılım günü) seansın İLK 2 SAATİ — YALNIZ aday-günler için (lite; 5y dökümü değil).
    FMP'de native 2h yok → günün 1hour barları çekilir, 09:30+10:30 birleştirilir.
    Batch: sembol×AY tek istek (ay ≈160 bar, gözlenen istek tavanının çok altında);
    eşzamanlılık ThreadPool (kod tabanının deseni) workers=3 + retry (burst-429 dersi).
    Cache: {sym: {date: bar|None}} — istek BAŞARILI ama gün boşsa None yazılır (tekrar
    sorulmaz); istek HATASI hiç yazılmaz → sonraki koşu yeniden dener (zehirli-cache dersi)."""
    cache = {}
    if not refresh and os.path.exists(INTRA_CACHE):
        cache = json.load(open(INTRA_CACHE))
    need = [(t, d) for t, d in pairs if d not in cache.get(t, {})]
    if not need:
        return cache
    groups = {}
    for t, d in need:
        groups.setdefault((t, d[:7]), []).append(d)
    key = s._fmp_key()
    print(f"• FMP 1hour: {len(need)} aday-gün → {len(groups)} sembol×ay isteği…", flush=True)

    def one(item):
        (sym, _mon), dates = item
        raw = _fmp("historical-chart/1hour", sym, key, **{"from": min(dates), "to": max(dates)})
        by_day = {}
        for b in raw or []:
            by_day.setdefault(b["date"][:10], []).append(b)
        out = {}
        for day in dates:
            bars = sorted(by_day.get(day, []), key=lambda b: b["date"])
            f2 = [b for b in bars if b["date"][11:16] < "11:30"]     # 09:30 + 10:30 barları
            if not f2:
                out[day] = None
                continue
            out[day] = {"o": f2[0]["open"], "h": max(b["high"] for b in f2),
                        "l": min(b["low"] for b in f2), "c": f2[-1]["close"],
                        "v2h": sum(b.get("volume") or 0 for b in f2),
                        "vday": sum(b.get("volume") or 0 for b in bars),
                        "nbars": len(bars)}
        return sym, out

    done = 0
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(one, it): it for it in groups.items()}
        for f in cf.as_completed(futs):
            try:
                sym, out = f.result()
                cache.setdefault(sym, {}).update(out)
            except Exception:
                pass                                   # hatalı grup → sonraki koşu dener
            done += 1
            if done % 200 == 0:
                json.dump(cache, open(INTRA_CACHE, "w"), indent=0)   # ara kayıt
                print(f"  {done}/{len(groups)} grup…", flush=True)
    os.makedirs(m.ML_DIR, exist_ok=True)
    json.dump(cache, open(INTRA_CACHE, "w"), indent=0)
    return cache


def intraday_lite(df, refresh=False):
    """H4 lite özellikleri df'e ekle:
    first_2h_vol_ratio     = ilk 2h hacmi / gün toplam hacmi (aynı kaynak → tutarlı oran)
    first_2h_close_strength= (C−L)/(H−L) ilk-2h barında, 0–1 (1 = tepeden kapanış).
    İkisi de 11:30'da bilinir < 15:45 sinyal anı → lookahead yok."""
    cache = fetch_intraday_2h(set(zip(df["symbol"], df["asof"])), refresh)
    vr, cs = [], []
    for r in df.itertuples():
        b = (cache.get(r.symbol) or {}).get(r.asof)
        if not b or not b.get("vday"):
            vr.append(np.nan); cs.append(np.nan); continue
        vr.append(b["v2h"] / b["vday"])
        rng = b["h"] - b["l"]
        cs.append((b["c"] - b["l"]) / rng if rng and rng > 0 else np.nan)
    df["first_2h_vol_ratio"] = vr
    df["first_2h_close_strength"] = cs
    return df


# ------------------------------------------------------------ H5: 1h bar yapısı
def fetch_intraday_1h(pairs, refresh=False):
    """T=0 gününün HAM 1h barları (kompakt [hh:mm,o,h,l,c,v] listesi) — 2h cache'in
    aksine tüm barlar saklanır ki saatlik yapı özellikleri türetilebilsin.
    Aynı batch/cache disiplinİ: sembol×ay istek, workers=3+retry, ara kayıt,
    başarılı-boş gün [] cache'lenir, istek HATASI cache'lenmez."""
    cache = {}
    if not refresh and os.path.exists(INTRA1H_CACHE):
        cache = json.load(open(INTRA1H_CACHE))
    need = [(t, d) for t, d in pairs if d not in cache.get(t, {})]
    if not need:
        return cache
    groups = {}
    for t, d in need:
        groups.setdefault((t, d[:7]), []).append(d)
    key = s._fmp_key()
    print(f"• FMP 1hour (ham): {len(need)} aday-gün → {len(groups)} sembol×ay isteği…", flush=True)

    def one(item):
        (sym, _mon), dates = item
        raw = _fmp("historical-chart/1hour", sym, key, **{"from": min(dates), "to": max(dates)})
        by_day = {}
        for b in raw or []:
            by_day.setdefault(b["date"][:10], []).append(b)
        out = {}
        for day in dates:
            bars = sorted(by_day.get(day, []), key=lambda b: b["date"])
            out[day] = [[b["date"][11:16], b["open"], b["high"], b["low"],
                         b["close"], b.get("volume") or 0] for b in bars]
        return sym, out

    done = 0
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(one, it): it for it in groups.items()}
        for f in cf.as_completed(futs):
            try:
                sym, out = f.result()
                cache.setdefault(sym, {}).update(out)
            except Exception:
                pass
            done += 1
            if done % 200 == 0:
                json.dump(cache, open(INTRA1H_CACHE, "w"), indent=0)
                print(f"  {done}/{len(groups)} grup…", flush=True)
    os.makedirs(m.ML_DIR, exist_ok=True)
    json.dump(cache, open(INTRA1H_CACHE, "w"), indent=0)
    return cache


def hourly_struct(df, frames, refresh=False):
    """H5 özellikleri (günün 1h barlarından):
    pm_vol_share      : son 3 barın (13:30+) hacmi / gün hacmi (kapanışa hacim ivmesi)
    ret_pm_pct        : 11:30-kapanışından gün kapanışına % (öğleden sonra devamlılık)
    high_hour_pos     : gün zirvesini yapan barın konumu 0(açılış)–1(kapanış)
    close_vs_vwap_pct : kapanışın gün-içi VWAP'ine mesafesi % (tipik fiyat×hacim)
    hold_above_break  : saatlik kapanışların 63g kırılım seviyesi ÜSTÜNDE kalan oranı
    trend_efficiency  : |net hareket| / saatlik |hareket|ler toplamı (temiz trend=1, testere→0)"""
    cache = fetch_intraday_1h(set(zip(df["symbol"], df["asof"])), refresh)
    h63c = {}
    out = {k: [] for k in F_H5}
    for r in df.itertuples():
        bars = (cache.get(r.symbol) or {}).get(r.asof)
        if r.symbol not in h63c:
            f = frames.get(r.symbol)
            h63c[r.symbol] = (f["High"].rolling(63).max().shift(1)
                              if f is not None else None)
        vals = dict.fromkeys(F_H5, np.nan)
        if bars and len(bars) >= 4:
            o = np.array([b[1] for b in bars], float); h = np.array([b[2] for b in bars], float)
            l = np.array([b[3] for b in bars], float); c = np.array([b[4] for b in bars], float)
            v = np.array([b[5] for b in bars], float)
            vt = v.sum()
            if vt > 0:
                vals["pm_vol_share"] = float(v[3:].sum() / vt)
                vwap = float((((h + l + c) / 3) * v).sum() / vt)
                vals["close_vs_vwap_pct"] = float((c[-1] / vwap - 1) * 100)
            if c[1]:                                     # c[1] = 10:30 barının kapanışı = 11:30
                vals["ret_pm_pct"] = float((c[-1] / c[1] - 1) * 100)
            vals["high_hour_pos"] = float(np.argmax(h) / max(1, len(h) - 1))
            moves = np.abs(np.diff(np.concatenate([[o[0]], c])))
            sm = moves.sum()
            vals["trend_efficiency"] = float(abs(c[-1] - o[0]) / sm) if sm > 0 else np.nan
            hs = h63c.get(r.symbol)
            if hs is not None:
                brk = hs.asof(r.asof_ts) if hasattr(hs, "asof") else None
                if brk == brk and brk:
                    vals["hold_above_break"] = float((c > brk).mean())
        for k in F_H5:
            out[k].append(vals[k])
    for k in F_H5:
        df[k] = out[k]
    return df


# ------------------------------------------------------------ ablation tezgâhı
def ablation(df, extra_fams=None):
    fams = OrderedDict([
        ("baz (günlük bar)", m.FEATURES),
        ("H1 vcp/taban", F_VCP),
        ("H2 sektör RS", F_SEC),
        ("H3 katalizör", F_CAT),
        ("yeni 3 aile", F_VCP + F_SEC + F_CAT),
        ("HEPSİ (baz+yeni)", m.FEATURES + F_VCP + F_SEC + F_CAT),
    ])
    if extra_fams:
        fams.update(extra_fams)
    from xgboost import XGBClassifier
    results, importances = OrderedDict(), {}
    cuts = bf.FOLD_CUTS
    for name, feats in fams.items():
        aucs, imps = [], []
        for i, cut in enumerate(cuts):
            c = pd.Timestamp(cut)
            e = pd.Timestamp(cuts[i + 1]) if i + 1 < len(cuts) else pd.Timestamp("2099-01-01")
            tr = df[df["asof_ts"] < c - pd.Timedelta(days=bf.PURGE_DAYS)]
            te = df[(df["asof_ts"] >= c) & (df["asof_ts"] < e)]
            if len(tr) < 200 or len(te) < 50:
                continue
            mod = XGBClassifier(**bf.XGB_PARAMS)
            mod.fit(tr[feats].astype(float), tr["label"].astype(int))
            p = mod.predict_proba(te[feats].astype(float))[:, 1]
            aucs.append(bf._auc(te["label"].astype(int).values, p))
            imps.append(mod.feature_importances_)
        results[name] = {"features": feats, "auc_folds": [round(a, 3) for a in aucs],
                         "auc_ort": round(float(np.mean(aucs)), 3)}
        if imps:
            mean_imp = np.mean(imps, axis=0)
            importances[name] = {k: round(float(v), 4)
                                 for k, v in sorted(zip(feats, mean_imp), key=lambda x: -x[1])}
    return results, importances


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="sektör/bilanço cache'lerini yeniden çek")
    ap.add_argument("--intraday", action="store_true", help="H4: kırılım günü ilk-2h lite ailesini de test et")
    ap.add_argument("--intraday1h", action="store_true", help="H5: kırılım günü 1h bar YAPISI ailesini de test et")
    args = ap.parse_args()

    lab = [r for r in m._read_log() if r["label"] != ""]
    df = pd.DataFrame(lab)
    df["asof_ts"] = pd.to_datetime(df["asof"])
    for c in m.FEATURES + ["label"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    print(f"• etiketli örnek: {len(df)} ({df['asof'].min()} → {df['asof'].max()})", flush=True)

    frames = m.load_frames()
    df = enrich(df, frames, refresh=args.refresh)
    nn = df[F_VCP + F_SEC + F_CAT].notna().mean() * 100
    print("• yeni özellik doluluk %: " + " · ".join(f"{k}={v:.0f}" for k, v in nn.items()), flush=True)

    extra = None
    if args.intraday:
        df = intraday_lite(df)
        cov = df[F_I2H].notna().mean() * 100
        print("• H4 doluluk %: " + " · ".join(f"{k}={v:.0f}" for k, v in cov.items()), flush=True)
        extra = OrderedDict([
            ("H4 intraday-2h lite", F_I2H),
            ("HEPSİ+H4 (16)", m.FEATURES + F_VCP + F_SEC + F_CAT + F_I2H),
        ])

    cov5 = None
    if args.intraday1h:
        df = hourly_struct(df, frames)
        cov5 = df[F_H5].notna().mean() * 100
        print("• H5 doluluk %: " + " · ".join(f"{k}={v:.0f}" for k, v in cov5.items()), flush=True)
        extra = extra if extra is not None else OrderedDict()
        extra["H5 1h-yapı"] = F_H5
        if args.intraday:
            extra["H4+H5 (8)"] = F_I2H + F_H5
            extra["HEPSİ+H4+H5 (22)"] = m.FEATURES + F_VCP + F_SEC + F_CAT + F_I2H + F_H5
        else:
            extra["HEPSİ+H5 (20)"] = m.FEATURES + F_VCP + F_SEC + F_CAT + F_H5

    results, imps = ablation(df, extra_fams=extra)

    cuts = bf.FOLD_CUTS
    w = max(len(k) for k in results)
    print("\n" + "═" * (w + 46))
    print(f"{'AİLE':<{w}}  n  " + "  ".join(c[:7] for c in cuts) + "    ORT")
    print("─" * (w + 46))
    for name, r in results.items():
        folds = "  ".join(f"{a:.3f}" for a in r["auc_folds"])
        print(f"{name:<{w}} {len(r['features']):2d}  {folds}  {r['auc_ort']:.3f}")
    print("═" * (w + 46))
    imp_key = next((k for k in ("HEPSİ+H4+H5 (22)", "HEPSİ+H5 (20)", "HEPSİ+H4 (16)",
                                "HEPSİ (baz+yeni)") if k in imps), None)
    if imps.get(imp_key):
        print(f"Özellik önemi ({imp_key}, fold ortalaması): "
              + " · ".join(f"{k}={v}" for k, v in list(imps[imp_key].items())[:8]))

    mt = json.load(open(m.META_PATH)) if os.path.exists(m.META_PATH) else {}
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    mt.setdefault("feature_lab", {})[ts] = {
        "n_rows": len(df), "families": results,
        "importances_all": imps.get("HEPSİ (baz+yeni)", {}),
        "coverage": {k: round(float(v), 1) for k, v in nn.items()}}
    if args.intraday:
        mt["intraday_lite_2h"] = {
            "ts": ts, "n_rows": len(df),
            "coverage_pct": {k: round(float(v), 1) for k, v in cov.items()},
            "H4_only": results.get("H4 intraday-2h lite"),
            "all_plus_H4": results.get("HEPSİ+H4 (16)"),
            "importances_H4": imps.get("H4 intraday-2h lite", {}),
            "importances_all16": imps.get("HEPSİ+H4 (16)", {})}
    if args.intraday1h:
        mt["intraday_1h_struct"] = {
            "ts": ts, "n_rows": len(df),
            "coverage_pct": {k: round(float(v), 1) for k, v in (cov5.items() if cov5 is not None else [])},
            "H5_only": results.get("H5 1h-yapı"),
            "H4_plus_H5": results.get("H4+H5 (8)"),
            "all_combined": results.get("HEPSİ+H4+H5 (22)") or results.get("HEPSİ+H5 (20)"),
            "importances_H5": imps.get("H5 1h-yapı", {}),
            "importances_combined": imps.get("HEPSİ+H4+H5 (22)") or imps.get("HEPSİ+H5 (20)", {})}
    json.dump(mt, open(m.META_PATH, "w"), ensure_ascii=False, indent=1)
    print(f"\nkayıt: {m.META_PATH} → feature_lab" + (" + intraday_lite_2h" if args.intraday else ""))


if __name__ == "__main__":
    main()

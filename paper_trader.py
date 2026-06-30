#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kağıt (paper) trade motoru — qswing canlı tarama sinyalleriyle DRY-RUN portföy.

Kurallar (kullanıcı isteği):
  • Başlangıç sermaye 10.000 $; her pozisyon SABİT 1.000 $ (max 10 eşzamanlı).
  • Giriş: 22:45 (15:45 ET) taramasındaki KIRILIM sinyali, o anki giriş fiyatından.
  • Çıkış: ŞAMPİYON (optimized) — +1R sonrası KAPANIŞ−2.5×ATR trailing; +2R hedef.
    (Motorda partial @ +2R ve hedef @ +2R AYNI seviye → net sonuç TAM pozisyon
     +2R'de kâr-al VEYA trail/stop'ta zarar-kes. Burada o net davranış uygulanır.)
  • Anti-contamination: pozisyon GİRİŞ barında yönetilmez; her cron çalışması
    yalnız son yönetilen tarihten SONRAKİ barları ilerletir (gelecek bar yok).
  • Slippage (opt-in, SLIPPAGE=True): YALNIZ dolum fiyatına — giriş +3bps, stop/trail
    −10bps, gap (Open<stop) → Open'dan; +2R hedef limit = tam. Karar/sinyal mantığı AYNEN.

8/21-EMA varyantı (karşılaştırma dry-run'ı, girişler AYNI — yalnız çıkış farklı):
  • Backtest hibrit split birebir: %50 bacak kapanış<EMA8'de, kalan %50 kapanış<EMA21'de
    çıkar. Ortak felaket stopu YOK. Kapanış-teyitli market çıkış → −SLIP_EXIT_BPS.

Durum dosyaları:
  ~/.swing_paper.json      — ŞAMPİYON portföy (nakit + açık pozisyonlar + kapananlar)
  ~/.swing_paper_ema.json  — 8/21-EMA varyant portföyü (aynı yapı + pozisyonlarda legs)
  ~/.swing_lastscan.json   — son 22:45 mesajı (/lastscan için)

CLI: python3 paper_trader.py [--show | --reset] [--ema]
"""
import os, json, math
from datetime import datetime

import pandas as pd

PAPER = os.path.expanduser("~/.swing_paper.json")
PAPER_EMA = os.path.expanduser("~/.swing_paper_ema.json")      # 8/21-EMA çıkış varyantı (karşılaştırma)
PAPER_CHAND = os.path.expanduser("~/.swing_paper_chand.json")  # 💡 63g kırılım + şamdan trail varyantı
LASTSCAN = os.path.expanduser("~/.swing_lastscan.json")
SCANDATA = os.path.expanduser("~/.swing_lastscan_data.json")   # yapısal tarama (dashboard için)

START_CAPITAL = 10_000.0
PER_POSITION = 1_000.0   # (legacy — eşit-ağırlık modunda kullanılmıyor)
MAX_POSITIONS = 10       # (legacy — eşit-ağırlık modunda tavan YOK)
SIZING = "equal"         # 'equal' = nakit / o günkü yeni sinyal sayısı (tüm sinyaller alınır)
ATR_TRAIL_MULT = 2.5     # şampiyon: +1R sonrası KAPANIŞ − 2.5×ATR
TRAIL_AFTER_R = 1.0      # +1R sonrası trailing devreye girer
EMA_FAST, EMA_SLOW = 8, 21   # EMA varyantı: hibrit çıkış — %50 kapanış<EMA8, kalan %50 kapanış<EMA21
# 💡 Şamdan (chandelier) varyantı — 2026-06-11 deney kazananı (backtest exit_mode='atr_full' birebir):
# giriş yalnız 63g kırılımlarda (KIRILIM listesinin alt kümesi), çıkış: TEPE−3.25×ATR altında KAPANIŞ.
# Kısmi kâr / sabit hedef / gün-içi stop YOK; pozisyon tek parça.
CHAND_MULT = 3.25            # şamdan trail çarpanı (tepe − mult × ATR)
CHAND_LB = 63                # giriş kırılım penceresi (çeyreklik tepe)

# --- Slippage modeli (opt-in; YALNIZ dolum fiyatına uygulanır, karar/sinyal mantığı değişmez) ---
SLIPPAGE = True          # False → ideal (slippage'sız) dolum
SLIP_ENTRY_BPS = 3.0     # giriş market emri: fiyat +3 bps (daha pahalı al)
SLIP_EXIT_BPS = 10.0     # stop/trail çıkışı: −10 bps (stop-market kayması, daha ucuz sat)
GAP_FILL = True          # bar stop'un ALTINDA açıldıysa gerçekçi gap → Open'dan dol
# Not: +2R hedef = LİMİT emir → negatif slippage yok (target'tan dolar).

_FMP_QUOTE = "https://financialmodelingprep.com/stable/quote"


# ----------------------------- durum (state) -----------------------------
def _default_state(variant="champion"):
    return {"start_capital": START_CAPITAL, "per_position": PER_POSITION,
            "max_positions": MAX_POSITIONS, "cash": START_CAPITAL,
            "variant": variant, "started": None, "positions": [], "closed": []}


def load_state(path=PAPER, variant="champion"):
    if os.path.exists(path):
        try:
            st = json.load(open(path))
            for k, v in _default_state(variant).items():
                st.setdefault(k, v)
            return st
        except Exception:
            pass
    return _default_state(variant)


def save_state(st, path=PAPER):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def held_symbols(st):
    return {p["symbol"] for p in st.get("positions", [])}


def _isna(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


# ----------------------------- yönetim (exit) ----------------------------
def _manage_bar(pos, open_, high, low, close, atr):
    """Bir günlük barı şampiyon kurallarıyla değerlendir.
    Dönüş: (çıkış_mı, fill, etiket). fill = slippage'lı gerçekçi dolum fiyatı.
    Karar seviyeleri (stop/target/trailing) slippage'sız — trade mantığı aynen."""
    entry, stop, target, risk0 = pos["entry"], pos["stop"], pos["target"], pos["risk0"]
    # 1) Trailing güncelle (KARAR seviyesi — slippage'sız; +1R sonrası, KAPANIŞ bazlı, yukarı ratchet)
    if not _isna(atr) and not _isna(close) and close >= entry + TRAIL_AFTER_R * risk0:
        new_stop = close - ATR_TRAIL_MULT * atr
        if new_stop > stop:
            stop = pos["stop"] = new_stop
    # 2) Hard stop (gün-içi low). Dolum: bar stop ALTINDA açıldıysa gap → Open'dan;
    #    aksi halde stop − SLIP_EXIT_BPS (stop-market kayması).
    if not _isna(low) and low <= stop:
        if GAP_FILL and not _isna(open_) and open_ < stop:
            fill = open_
        elif SLIPPAGE:
            fill = stop * (1 - SLIP_EXIT_BPS / 1e4)
        else:
            fill = stop
        return True, fill, ("STOP" if stop < entry else "TRAIL")
    # 3) +2R hedef (gün-içi high) — LİMİT emir, negatif slippage yok (target'tan dolar)
    if not _isna(high) and high >= target:
        return True, target, "TP"
    return False, None, None


def manage(st, market, asof):
    """Açık pozisyonları, son yönetilen tarihten SONRAKİ → asof barlarına kadar ilerlet.
    Çıkanları st['closed']'a taşır, nakdi geri verir. Çıkan işlem kayıtlarını döndürür."""
    data = market.get("data", {})
    asof_ts = pd.Timestamp(asof).normalize()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")   # gerçek işleme anı (cron çalışması)
    exited, still = [], []
    for pos in st.get("positions", []):
        df = data.get(pos["symbol"])
        last = pd.Timestamp(pos.get("last_date", pos["entry_date"])).normalize()
        done = False
        if df is not None and len(df):
            bars = df[(df.index > last) & (df.index <= asof_ts)]
            for ts, row in bars.iterrows():
                ex, fill, tag = _manage_bar(pos, row.get("Open"), row.get("High"), row.get("Low"),
                                            row.get("Close"), row.get("ATR"))
                pos["last_date"] = ts.strftime("%Y-%m-%d")
                if ex:
                    ef = pos.get("entry_fill", pos["entry"])     # gerçek ödenen giriş (slippage'lı)
                    proceeds = pos["shares"] * fill
                    cost = pos["shares"] * ef
                    st["cash"] += proceeds
                    rec = {"symbol": pos["symbol"], "entry_date": pos["entry_date"],
                           "entry_ts": pos.get("entry_ts"),
                           "exit_date": ts.strftime("%Y-%m-%d"), "exit_ts": now_ts,
                           "entry": round(pos["entry"], 2), "entry_fill": round(ef, 2),
                           "exit": round(fill, 2), "shares": round(pos["shares"], 4),
                           "pnl": round(proceeds - cost, 2),
                           "pnl_pct": round((fill / ef - 1) * 100, 2), "outcome": tag}
                    st["closed"].append(rec); exited.append(rec); done = True
                    break
        if not done:
            still.append(pos)
    st["positions"] = still
    st["cash"] = round(st["cash"], 2) or 0.0
    return exited


# ------------------- yönetim (exit) — 8/21-EMA varyantı ------------------
def _ema_series(df):
    """EMA8/EMA21 serileri: df'te kolon varsa onu kullan, yoksa kapanıştan hesapla
    (backtest ile aynı formül: ewm(span=n, adjust=False))."""
    e8 = df["EMA8"] if "EMA8" in df.columns else df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    e21 = df["EMA21"] if "EMA21" in df.columns else df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()
    return e8, e21


def manage_ema(st, market, asof):
    """8/21-EMA hibrit çıkış — backtest _manage_split(split_a=ema8, split_b=ema21) birebir:
    her pozisyon iki yarı-bacak; A-bacağı kapanış<EMA8'de, B-bacağı kapanış<EMA21'de çıkar.
    Ortak felaket stopu YOK; kapanış-teyitli market çıkış → SLIP_EXIT_BPS kayması.
    Anti-contamination şampiyon manage() ile aynı (giriş barı yönetilmez)."""
    data = market.get("data", {})
    asof_ts = pd.Timestamp(asof).normalize()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exited, still = [], []
    for pos in st.get("positions", []):
        df = data.get(pos["symbol"])
        last = pd.Timestamp(pos.get("last_date", pos["entry_date"])).normalize()
        if df is None or not len(df):
            still.append(pos)
            continue
        e8, e21 = _ema_series(df)
        ef = pos.get("entry_fill", pos["entry"])
        for ts, row in df[(df.index > last) & (df.index <= asof_ts)].iterrows():
            pos["last_date"] = ts.strftime("%Y-%m-%d")
            close = row.get("Close")
            if _isna(close):
                continue
            for leg in pos["legs"]:
                if leg["shares"] <= 0:
                    continue
                ma = (e8 if leg["rule"] == "ema8" else e21).get(ts)
                if ma is None or _isna(ma) or close >= ma:
                    continue
                fill = close * (1 - SLIP_EXIT_BPS / 1e4) if SLIPPAGE else close
                proceeds = leg["shares"] * fill
                st["cash"] += proceeds
                rec = {"symbol": pos["symbol"], "entry_date": pos["entry_date"],
                       "entry_ts": pos.get("entry_ts"),
                       "exit_date": ts.strftime("%Y-%m-%d"), "exit_ts": now_ts,
                       "entry": round(pos["entry"], 2), "entry_fill": round(ef, 2),
                       "exit": round(fill, 2), "shares": round(leg["shares"], 4),
                       "pnl": round(proceeds - leg["cost"], 2),
                       "pnl_pct": round((fill / ef - 1) * 100, 2),
                       "outcome": "EMA8" if leg["rule"] == "ema8" else "EMA21"}
                st["closed"].append(rec); exited.append(rec)
                pos["shares"] -= leg["shares"]
                leg["shares"] = 0.0; leg["cost"] = 0.0
            if all(l["shares"] <= 0 for l in pos["legs"]):
                break
        if any(l["shares"] > 0 for l in pos["legs"]):
            still.append(pos)
    st["positions"] = still
    st["cash"] = round(st["cash"], 2) or 0.0
    return exited


# ---------------- yönetim (exit) — 💡 şamdan (chandelier) varyantı --------
def manage_chand(st, market, asof):
    """Şamdan trail çıkışı — backtest exit_mode='atr_full' birebir:
    her barda tepe = max(tepe, High); KAPANIŞ < tepe − CHAND_MULT×ATR ise TÜM pozisyon
    kapanıştan çıkar (market → −SLIP_EXIT_BPS). Kısmi/hedef/gün-içi stop YOK.
    Anti-contamination şampiyon manage() ile aynı (giriş barı yönetilmez)."""
    data = market.get("data", {})
    asof_ts = pd.Timestamp(asof).normalize()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exited, still = [], []
    for pos in st.get("positions", []):
        df = data.get(pos["symbol"])
        last = pd.Timestamp(pos.get("last_date", pos["entry_date"])).normalize()
        done = False
        if df is not None and len(df):
            ef = pos.get("entry_fill", pos["entry"])
            for ts, row in df[(df.index > last) & (df.index <= asof_ts)].iterrows():
                pos["last_date"] = ts.strftime("%Y-%m-%d")
                high, close, atr = row.get("High"), row.get("Close"), row.get("ATR")
                if not _isna(high):
                    pos["peak"] = max(pos.get("peak", pos["entry"]), float(high))
                if _isna(close) or _isna(atr):
                    continue
                level = pos.get("peak", pos["entry"]) - CHAND_MULT * float(atr)
                pos["chand_stop"] = round(level, 4)        # bilgi amaçlı (mesaj/dashboard)
                if close < level:                          # kapanış teyidi → market çıkış
                    fill = close * (1 - SLIP_EXIT_BPS / 1e4) if SLIPPAGE else close
                    proceeds = pos["shares"] * fill
                    st["cash"] += proceeds
                    rec = {"symbol": pos["symbol"], "entry_date": pos["entry_date"],
                           "entry_ts": pos.get("entry_ts"),
                           "exit_date": ts.strftime("%Y-%m-%d"), "exit_ts": now_ts,
                           "entry": round(pos["entry"], 2), "entry_fill": round(ef, 2),
                           "exit": round(fill, 2), "shares": round(pos["shares"], 4),
                           "pnl": round(proceeds - pos["shares"] * ef, 2),
                           "pnl_pct": round((fill / ef - 1) * 100, 2), "outcome": "ŞAMDAN"}
                    st["closed"].append(rec); exited.append(rec); done = True
                    break
        if not done:
            still.append(pos)
    st["positions"] = still
    st["cash"] = round(st["cash"], 2) or 0.0
    return exited


# ----------------------------- giriş (open) ------------------------------
def open_new(st, buyable, asof):
    """EŞİT-AĞIRLIK: o günkü TÜM yeni (tutulmayan) KIRILIM sinyallerini aç.
    Mevcut nakit, o günkü yeni sinyallere EŞİT bölünür → per = nakit / yeni_sinyal_sayısı.
    max_positions tavanı YOK; tüm sinyaller alınır. Zaten tutulan sembol atlanır (pyramiding yok)."""
    if st.get("started") is None:
        st["started"] = pd.Timestamp(asof).strftime("%Y-%m-%d")
    held = held_symbols(st)
    fresh = []
    for c in sorted(buyable, key=lambda r: r.get("score", 0), reverse=True):
        sym = c["symbol"]
        if sym in held:
            continue
        entry = float(c["entry"]); stop = float(c["stop"])
        if entry <= 0 or stop >= entry:
            continue
        fresh.append((c, entry, stop))
    if not fresh or st["cash"] <= 1e-6:
        return []
    per = st["cash"] / len(fresh)                 # eşit böl: nakdi o günkü yeni sinyallere dağıt
    asof_s = pd.Timestamp(asof).strftime("%Y-%m-%d")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")   # gerçek işleme anı (cron çalışması)
    opened = []
    for c, entry, stop in fresh:
        entry_fill = entry * (1 + SLIP_ENTRY_BPS / 1e4) if SLIPPAGE else entry  # market emri kayması
        shares = per / entry_fill                     # gerçek ödenen fiyattan adet (nakit tamamı kullanılır)
        target = float(c.get("partial_target") or (entry + 2 * (entry - stop)))
        pos = {"symbol": c["symbol"], "entry_date": asof_s, "entry_ts": now_ts,
               "entry": entry, "entry_fill": round(entry_fill, 4), "shares": shares,
               "stop": stop, "target": target, "atr0": float(c.get("atr") or 0.0),
               "risk0": entry - stop, "alloc": round(per, 2),
               "last_date": asof_s, "score": c.get("score")}
        if st.get("variant") == "ema":                # hibrit 8/21: iki yarı-bacak (backtest birebir)
            half = shares / 2
            pos["legs"] = [{"rule": "ema8",  "shares": half,          "cost": half * entry_fill},
                           {"rule": "ema21", "shares": shares - half, "cost": (shares - half) * entry_fill}]
        elif st.get("variant") == "chand":            # 💡 şamdan: tepe takibi + başlangıç trail seviyesi
            pos["peak"] = entry
            atr0 = pos["atr0"]
            pos["chand_stop"] = round(entry - CHAND_MULT * atr0, 4) if atr0 > 0 else stop
            pos["stop"] = pos["chand_stop"]           # bilgi amaçlı (gün-içi tetik YOK, kapanış teyidi)
            pos["target"] = None                      # sabit hedef yok — trend ne verirse
        st["cash"] -= shares * entry_fill             # = per (eşit-ağırlık korunur)
        st["positions"].append(pos); opened.append(pos)
    st["cash"] = round(st["cash"], 2) or 0.0     # float tozunu / -0.0'ı temizle
    return opened


# ----------------------------- canlı quote -------------------------------
def quote_fmp(symbols, key):
    """FMP /stable/quote ile anlık fiyat: {sym: price}. Başarısızsa sembol atlanır.

    FMP toplu-quote bu planda kapalı (legacy v3 → 403, /stable/batch-quote → 402), o
    yüzden sembol başına ayrı istek gerekiyor — ama PARALEL (ThreadPoolExecutor) çekilir.
    20+ pozisyonda sıralı ~12-27 sn yerine ~1-2 sn (dashboard /api/portfolio + Telegram
    /portfolio aynı yoldan hızlanır)."""
    import urllib.request as _u, urllib.parse as _up, json as _json
    from concurrent.futures import ThreadPoolExecutor

    def _one(sym):
        url = _FMP_QUOTE + "?" + _up.urlencode({"symbol": sym, "apikey": key})
        try:
            req = _u.Request(url, headers={"User-Agent": "swing2/1.0"})
            with _u.urlopen(req, timeout=12) as r:
                raw = _json.loads(r.read().decode("utf-8"))
            if isinstance(raw, list) and raw and raw[0].get("price") is not None:
                return sym, float(raw[0]["price"])
        except Exception:
            pass
        return sym, None

    syms = list(symbols)
    if not syms:
        return {}
    out = {}
    with ThreadPoolExecutor(max_workers=min(10, len(syms))) as ex:
        for sym, px in ex.map(_one, syms):
            if px is not None:
                out[sym] = px
    return out


# ----------------------------- mesaj metinleri ---------------------------
def _slip_note():
    if not SLIPPAGE:
        return ""
    return (f" · slippage: giriş +{SLIP_ENTRY_BPS:.0f}bps · stop/trail −{SLIP_EXIT_BPS:.0f}bps"
            f"{' · gap=Open' if GAP_FILL else ''} (hedef limit=tam)")


def _equity(st, prices=None):
    """Toplam özsermaye = nakit + pozisyon piyasa değeri (prices verilirse, yoksa girişten)."""
    val = st["cash"]
    for p in st["positions"]:
        px = (prices or {}).get(p["symbol"], p["entry"])
        val += p["shares"] * px
    return val


def _cost_basis(p):
    """Pozisyonun gerçek maliyet bazı (giriş komisyonu dahil) → realize ile aynı temel.
    Öncelik: state'teki 'cost' → bacak cost toplamı → adet×entry_fill (geri uyumlu).
    Komisyon dahil baz, unrealize'i realize ile tutarlı kılar (total_pl = realize+unrealize)."""
    if p.get("cost") is not None:
        return p["cost"]
    if p.get("legs"):
        return sum(l["cost"] for l in p["legs"])
    return p["shares"] * p.get("entry_fill", p["entry"])


def _exit_plan_txt(p):
    """Pozisyonun çıkış planı metni: EMA varyantında kalan bacaklar, şamdanda trail seviyesi,
    yoksa stop+hedef."""
    if p.get("legs"):
        _lbl = {"ema8": "kapanış&lt;8-EMA", "ema21": "kapanış&lt;21-EMA", "target": "+2R hedef"}
        rem = [_lbl.get(l["rule"], l["rule"]) for l in p["legs"] if l["shares"] > 0]
        return "çıkış: " + " / ".join(rem) if rem else "çıkış: tamamlandı"
    if p.get("peak") is not None:
        lvl = p.get("chand_stop")
        return (f"çıkış: kapanış &lt; <code>${lvl:.2f}</code> (tepe−{CHAND_MULT}×ATR)"
                if lvl is not None else f"çıkış: kapanış &lt; tepe−{CHAND_MULT}×ATR")
    return f"stop <code>${p['stop']:.2f}</code> · hedef <code>${p['target']:.2f}</code>"


def eod_message(opened, exited, st, asof, tag=None):
    """Gün sonu: açılan + çıkılan pozisyonlar + portföy özeti (HTML)."""
    L = [f"<b>📓 Kağıt Portföy{' — ' + tag if tag else ''} — Gün Sonu ({asof})</b>"]
    if opened:
        per = opened[0].get("alloc", opened[0]["shares"] * opened[0]["entry"])
        L.append(f"\n<b>🟢 AÇILAN ({len(opened)})</b> — eşit-ağırlık ≈ <b>${per:.0f}</b>/poz")
        for p in opened:
            alloc = p.get("alloc", p["shares"] * p["entry"])
            ef = p.get("entry_fill", p["entry"])
            L.append(f"• <b>{p['symbol']}</b> @ <code>${ef:.2f}</code> · ${alloc:.0f} · "
                     f"{p['shares']:.3f} adet · {_exit_plan_txt(p)}\n"
                     f"   🕒 giriş {p.get('entry_ts', p['entry_date'])}")
    if exited:
        tot = sum(r["pnl"] for r in exited)
        L.append(f"\n<b>🔴 ÇIKILAN ({len(exited)})</b> · realize K/Z "
                 f"<b>{'+' if tot>=0 else ''}{tot:.2f}$</b>")
        for r in exited:
            em = "✅" if r["pnl"] >= 0 else "❌"
            L.append(f"{em} <b>{r['symbol']}</b> {r['outcome']} @ <code>${r['exit']:.2f}</code> · "
                     f"giriş <code>${r.get('entry_fill', r['entry']):.2f}</code> · "
                     f"<b>{'+' if r['pnl']>=0 else ''}{r['pnl']:.2f}$ ({r['pnl_pct']:+.1f}%)</b>\n"
                     f"   🕒 giriş {r.get('entry_ts', r['entry_date'])} → çıkış "
                     f"{r.get('exit_ts', r['exit_date'])} (bar {r['exit_date']})")
    if not opened and not exited:
        L.append("\n<i>Bugün açılan/çıkılan pozisyon yok.</i>")
    eq = _equity(st)
    realized = sum(r["pnl"] for r in st["closed"])
    L.append(f"\n<b>📊 Durum:</b> {len(st['positions'])} açık · "
             f"nakit <code>${st['cash']:.0f}</code> · özsermaye (maliyet) <code>${eq:.0f}</code> · "
             f"toplam realize <b>{'+' if realized>=0 else ''}{realized:.0f}$</b>")
    L.append(f"<i>Eğitim amaçlı kağıt-trade — gerçek emir yok.{_slip_note()}</i>")
    return "\n".join(L)


def portfolio_message(st, prices, now_str, tag=None):
    """/portfolio yanıtı: mesajın gönderildiği an için anlık K/Z + detay (HTML)."""
    head = f"<b>📓 Kağıt Portföy{' — ' + tag if tag else ''} ({now_str})</b>"
    if not st["positions"]:
        eq = st["cash"]
        realized = sum(r["pnl"] for r in st["closed"])
        return (head + "\n"
                f"Açık pozisyon yok · nakit <code>${st['cash']:.2f}</code> · "
                f"toplam realize <b>{'+' if realized>=0 else ''}{realized:.2f}$</b>\n"
                f"<i>Eğitim amaçlı kağıt-trade.</i>")
    L = [head]
    unreal = 0.0
    for p in sorted(st["positions"], key=lambda x: x["symbol"]):
        ef = p.get("entry_fill", p["entry"])             # gerçek ödenen giriş
        px = prices.get(p["symbol"])
        if px is None:
            L.append(f"• <b>{p['symbol']}</b> giriş <code>${ef:.2f}</code> · "
                     f"{p['shares']:.3f} adet · <i>fiyat alınamadı</i>")
            continue
        basis = _cost_basis(p)               # komisyon dahil gerçek maliyet
        mv = p["shares"] * px
        pnl = mv - basis
        pct = (mv / basis - 1) * 100 if basis else 0.0
        unreal += pnl
        em = "🟢" if pnl >= 0 else "🔴"
        L.append(f"{em} <b>{p['symbol']}</b> <code>${px:.2f}</code> "
                 f"(giriş <code>${ef:.2f}</code>) · {p['shares']:.3f} adet · "
                 f"<b>{'+' if pnl>=0 else ''}{pnl:.2f}$ ({pct:+.1f}%)</b> · "
                 f"{_exit_plan_txt(p)} · "
                 f"🕒 {p.get('entry_ts', p['entry_date'])}")
    mkt_val = sum(p["shares"] * prices.get(p["symbol"], p["entry"]) for p in st["positions"])
    eq = st["cash"] + mkt_val
    realized = sum(r["pnl"] for r in st["closed"])
    total_pl = eq - st["start_capital"]
    L.append(f"\n<b>📊 Toplam:</b> özsermaye <code>${eq:.2f}</code> "
             f"(başlangıç ${st['start_capital']:.0f}) · "
             f"unrealize <b>{'+' if unreal>=0 else ''}{unreal:.2f}$</b> · "
             f"realize <b>{'+' if realized>=0 else ''}{realized:.2f}$</b>")
    L.append(f"<b>Genel K/Z: {'+' if total_pl>=0 else ''}{total_pl:.2f}$ "
             f"({total_pl/st['start_capital']*100:+.2f}%)</b> · nakit <code>${st['cash']:.2f}</code>")
    L.append(f"<i>Anlık fiyatlar FMP /stable · eğitim amaçlı kağıt-trade.{_slip_note()}</i>")
    return "\n".join(L)


# ----------------------------- aboneler (22:45 yayını) -------------------
SUBSCRIBERS = os.path.expanduser("~/.swing_subscribers.json")


def load_subscribers():
    """{chat_id(str): {name, added}} — 22:45 tarama+portföy yayınının alıcıları."""
    if os.path.exists(SUBSCRIBERS):
        try:
            d = json.load(open(SUBSCRIBERS))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def save_subscribers(subs):
    tmp = SUBSCRIBERS + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(subs, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, SUBSCRIBERS)


def add_subscriber(chat_id, name=""):
    subs = load_subscribers()
    key = str(chat_id)
    if key in subs:
        return False
    subs[key] = {"name": name, "added": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    save_subscribers(subs)
    return True


def remove_subscriber(chat_id):
    subs = load_subscribers()
    if str(chat_id) in subs:
        subs.pop(str(chat_id))
        save_subscribers(subs)
        return True
    return False


# ----------------------------- son scan kaydı ----------------------------
def save_last_scan(text, asof):
    tmp = LASTSCAN + ".tmp"
    payload = {"asof": asof, "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "text": text}
    with open(tmp, "w") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, LASTSCAN)


def load_last_scan():
    if os.path.exists(LASTSCAN):
        try:
            return json.load(open(LASTSCAN))
        except Exception:
            return None
    return None


def _num(x):
    """JSON-güvenli sayı (numpy/NaN → float|None)."""
    try:
        if x is None:
            return None
        f = float(x)
        return None if math.isnan(f) else round(f, 4)
    except Exception:
        return None


def _scan_row(c):
    """Tarama adayından dashboard için sade, JSON-güvenli kayıt."""
    p = c.get("score_parts") or {}
    return {"symbol": str(c.get("symbol", "")),
            "score": int(c["score"]) if c.get("score") is not None else None,
            "status": str(c.get("status", "")),
            "buyable": bool(c.get("buyable", False)),
            "entry": _num(c.get("entry")), "stop": _num(c.get("stop")),
            "partial_target": _num(c.get("partial_target")), "atr": _num(c.get("atr")),
            "rs": _num(c.get("rs")), "risk_pct": _num(c.get("risk_pct")),
            "high40": _num(c.get("high40")), "breakout_lb": c.get("breakout_lb"),
            "score_parts": {k: p.get(k) for k in ("rs", "near52", "fresh", "risk")} if p else {}}


def save_scan_data(res):
    """Canlı tarama sonucunu (res) dashboard için yapısal JSON olarak kaydet (atomik)."""
    payload = {"asof": res.get("asof"),
               "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "regime_open": bool(res.get("regime_open", False)),
               "buyable": [_scan_row(c) for c in res.get("buyable", [])],
               "watch": [_scan_row(c) for c in res.get("watch", [])]}
    tmp = SCANDATA + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, SCANDATA)


def load_scan_data():
    if os.path.exists(SCANDATA):
        try:
            return json.load(open(SCANDATA))
        except Exception:
            return None
    return None


# ----------------------------- CLI ---------------------------------------
def _cli():
    import sys
    ema = "--ema" in sys.argv
    chand = "--chand" in sys.argv
    path, variant = ((PAPER_CHAND, "chand") if chand else
                     (PAPER_EMA, "ema") if ema else (PAPER, "champion"))
    if "--reset" in sys.argv:
        save_state(_default_state(variant), path)
        print(f"Kağıt portföy ({variant}) SIFIRLANDI (10.000 $).")
        return
    st = load_state(path, variant)
    print(json.dumps(st, indent=2, ensure_ascii=False))
    print(f"\nÖzsermaye (maliyet): ${_equity(st):.2f} · açık {len(st['positions'])} · "
          f"kapanan {len(st['closed'])} · realize {sum(r['pnl'] for r in st['closed']):+.2f}$")


if __name__ == "__main__":
    _cli()

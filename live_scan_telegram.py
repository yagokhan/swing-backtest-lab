#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qswing KIRILIM canlı tarayıcı → TELEGRAM (grafik + H/R detayı).
Strateji: Qullamaggie 40-gün tepe KIRILIM girişi + şampiyon ATR-trail çıkış
(hedef +2R · %50 kâr-al sonrası breakeven · +1R sonrası KAPANIŞ−2.5×ATR trailing).
Veri: FMP /stable, 5 yıl (sağlayıcı varsayılan-azamisi → sağlam indikatör).

Kapanışa ~15 dk kala (15:45 ET) cron ile çağrılır:
  1) canlı günlük bar (son bar = gün-içi snapshot = 'kapanış' varsayımı)
  2) run_live_qswing_scan → KIRILIM + İZLE (backtest qswing_breakout ile aynı kapı)
  3) Telegram'a: özet + her KIRILIM için mum grafiği (giriş/stop/+2R hedef/40g-tepe) + H/R detayı

Gizli (~/.portfolio_keys.json | env): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, FMP_API_KEY
Açık pozisyonlar (ops.): ~/.swing_held.json → ["AAPL","MSFT"]  (KIRILIM listesinden düşülür)
Kullanım: python3 live_scan_telegram.py [--test] [--asof YYYY-MM-DD] [--demo-watch] [--et-window]
"""
import os, sys, json, html
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd
import requests
import swing2_backtest as s
import paper_trader as pt

KEYS = os.path.expanduser("~/.portfolio_keys.json")
HELD = os.path.expanduser("~/.swing_held.json")
OUT = "/home/gokhan/swing2_out"
TG = "https://api.telegram.org/bot{tok}/{method}"


def _secret(name):
    v = os.environ.get(name)
    if v:
        return v
    if os.path.exists(KEYS):
        try:
            return json.load(open(KEYS)).get(name)
        except Exception:
            return None
    return None


def _held():
    if os.path.exists(HELD):
        try:
            return [str(x).upper() for x in json.load(open(HELD))]
        except Exception:
            return []
    return []


def _et_window_ok(lo=(15, 30), hi=(16, 5)):
    """ABD Doğu saatiyle [lo,hi] penceresinde + hafta içi mi? (cron DST koruması)."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return True, None
    if "--et-now" in sys.argv:
        spec = sys.argv[sys.argv.index("--et-now") + 1]
        hh, mm = (spec.split(",")[0]).split(":")
        wd = int(spec.split(",")[1]) if "," in spec else et.weekday()
        et = et.replace(hour=int(hh), minute=int(mm))
        mins = et.hour * 60 + et.minute
        return (wd < 5 and (lo[0]*60+lo[1]) <= mins <= (hi[0]*60+hi[1])), et
    mins = et.hour * 60 + et.minute
    ok = et.weekday() < 5 and (lo[0]*60+lo[1]) <= mins <= (hi[0]*60+hi[1])
    return ok, et


def draw_chart(sym, df, c, asof, path, nbars=50):
    """Son nbars Heikin Ashi mumu + SMA50 + giriş/stop/+2R hedef/40g-tepe çizgileri → PNG.
    (Çıkış = şampiyon ATR-trail; +2R hedef çizgisi gösterilir, EMA çıkış çizgileri kaldırıldı.)
    Mumlar HA (görsel yumuşatma); SMA ve yatay çizgiler HAM fiyat. Trade mantığı/veri değişmez."""
    full = df.loc[:asof].dropna(subset=["Open", "High", "Low", "Close"])
    if len(full) < 5:
        return False
    d = full.tail(nbars)                       # ham (SMA sütunları + index)
    ha = s.heikin_ashi(full).tail(nbars)       # HA tüm geçmişle hesaplanır, sonra kesilir
    fig, ax = plt.subplots(figsize=(10, 5.6))
    for i, (_, r) in enumerate(ha.iterrows()):
        col = "#16a34a" if r["Close"] >= r["Open"] else "#dc2626"
        ax.plot([i, i], [r["Low"], r["High"]], color=col, lw=0.8, zorder=2)
        h = abs(r["Close"] - r["Open"]) or (r["Close"] * 0.001)
        ax.add_patch(Rectangle((i - 0.3, min(r["Open"], r["Close"])), 0.6, h, color=col, zorder=3))
    x = range(len(d))
    if "SMA50" in d: ax.plot(x, d["SMA50"].values, color="#f59e0b", lw=1.0, label="SMA50")
    ax.axhline(c["entry"], color="#3b82f6", ls="--", lw=1.2, label=f"Giriş {c['entry']}")
    ax.axhline(c["stop"], color="#dc2626", ls="--", lw=1.2, label=f"Stop {c['stop']}")
    if c.get("partial_target"):
        ax.axhline(c["partial_target"], color="#16a34a", ls=":", lw=1.2, label=f"+2R hedef {c['partial_target']}")
    if c.get("high40"):
        ax.axhline(c["high40"], color="#8a95ad", ls=":", lw=1.0, label=f"{c['breakout_lb']}g tepe {c['high40']}")
    idx = list(d.index)
    ticks = list(range(0, len(idx), max(1, len(idx) // 5)))
    ax.set_xticks(ticks); ax.set_xticklabels([idx[t].strftime("%m-%d") for t in ticks], fontsize=8)
    ax.set_title(f"{sym} · {asof} · {c['status']} · RS +{c['rs']} · Heikin Ashi", fontsize=11)
    ax.set_ylabel("Fiyat ($)"); ax.legend(fontsize=8, loc="best"); ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)
    return True


def candidate_caption(c, watch=False):
    e = html.escape
    if watch:
        if c.get("watch_reason") == "overext":
            head = "⚠️ <i>İZLE — {0}g tepeyi kırdı AMA aşırı uzamış (SMA20'ye %{1})</i>\n".format(
                c["breakout_lb"], c["dist_sma20_pct"])
        else:
            head = "🟡 <i>İZLE — {0}g tepeye %{1} kala</i>\n".format(
                c["breakout_lb"], c["dist_to_breakout_pct"])
    else:
        head = ""
    sc = c.get("score")
    rank = c.get("_rank")
    score_line = ""
    if sc is not None and not watch:
        p = c.get("score_parts") or {}
        rk = f"#{rank} · " if rank else ""
        score_line = (f"🏆 <b>{rk}Puan {sc}/100</b> "
                      f"<i>(RS {p.get('rs','?')}/45 · 52H {p.get('near52','?')}/20 · "
                      f"taze {p.get('fresh','?')}/20 · risk {p.get('risk','?')}/15)</i>\n")
    cap = (head +
           f"<b>{e(c['symbol'])}</b> · {e(c['sector_etf'])} · "
           f"{'🟡 İZLE' if watch else '🚀 KIRILIM'}\n"
           + score_line +
           f"🎯 Giriş <code>${c['entry']}</code> · Stop <code>${c['stop']}</code> "
           f"(risk %{c['risk_pct']})\n"
           f"📈 {c['breakout_lb']}g tepe <code>${c['high40']}</code>"
           f"{' aşıldı' if not watch else ''} · 52H'ye %{c['dist_52h_pct']} · "
           f"SMA20'ye %{c['dist_sma20_pct']}\n"
           f"⚖️ RS <b>+{c['rs']}</b> (60g · SPY'a karşı) · 3a getiri %{c['ret_3m']}\n"
           f"📤 Çıkış (şampiyon · ATR-trail {c.get('atr_trail_mult', 2.5)}×): "
           f"hedef <b>+2R</b> <code>${c.get('partial_target','—')}</code> · "
           f"+1R sonrası stop <b>KAPANIŞ−{c.get('atr_trail_mult', 2.5)}×ATR</b>'ye trailing "
           f"(ATR <code>${c.get('atr','—')}</code>) · %50 kâr-al sonrası girişe (breakeven) · "
           f"ilk koruma stopu <code>${c['stop']}</code>")
    if c.get("overext"):
        cap += (f"\n⚠️ <b>AŞIRI UZAMIŞ</b> (SMA20'ye %{c['dist_sma20_pct']}) — "
                f"parabolik/climax, geri çekilmeyi bekle.")
    return cap


def summary_text(res, demo=False):
    flag = "🟢 AÇIK" if res["regime_open"] else "🔴 KAPALI"
    L = [f"<b>🚀 qswing Kırılım Tarayıcı ({res['asof']})</b>",
         f"🕒 15:45 ET · Rejim: {flag} · SPY ${res['spy_close']} · {res['n_universe']} hisse"]
    if not res["regime_open"]:
        L.append("\n⚠️ <b>Rejim KAPALI</b> (SPY&lt;SMA200) → momentum stratejisinde yeni alım YOK.")
    n = len(res["buyable"])
    L.append(f"\n🚀 <b>KIRILIM: {n}</b>" + (" — puana göre sıralı, aşağıda grafik+detay 👇" if n else
             f" ({res['breakout_lb']}g tepe kırılımı + 52H yakın + SPY'ı geçen momentum koşulunu geçen yok)"))
    if n:
        rank = " · ".join(f"{i}.{html.escape(r['symbol'])} <b>{r.get('score','?')}</b>"
                          for i, r in enumerate(res["buyable"], 1))
        L.append(f"🏆 <b>Sıralama (puan):</b> {rank}")
    if demo and not n:
        L.append("🟡 Demo: tepeye en yakın <b>İZLE</b> adayları tam detayla gönderiliyor.")
    near = [r for r in res["watch"] if r.get("watch_reason") == "near"]
    over = [r for r in res["watch"] if r.get("watch_reason") == "overext"]
    if near:
        w = " · ".join(f"{html.escape(r['symbol'])}(tepeye %{r['dist_to_breakout_pct']})" for r in near[:10])
        L.append(f"🟡 <b>İZLE — tepeye ≤%3:</b> {w}")
    if over:
        w = " · ".join(f"{html.escape(r['symbol'])}(SMA20'ye %{r['dist_sma20_pct']})" for r in over[:10])
        L.append(f"⚠️ <b>İZLE — kırdı ama AŞIRI UZAMIŞ:</b> {w}")
    L.append("\n<i>Strateji: Qullamaggie 40g kırılım girişi · şampiyon ATR-trail çıkış "
             "(hedef +2R · %50 kâr-al sonrası breakeven · +1R sonrası KAPANIŞ−2.5×ATR trailing). "
             "Sinyal 15:45 anlık fiyatına göre — geçici. Eğitim amaçlı.</i>")
    return "\n".join(L)


def send_message(text, token, chat):
    return requests.post(TG.format(tok=token, method="sendMessage"),
                         data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                               "disable_web_page_preview": "true"}, timeout=30)


def send_photo(path, caption, token, chat):
    with open(path, "rb") as ph:
        return requests.post(TG.format(tok=token, method="sendPhoto"),
                             data={"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                             files={"photo": ph}, timeout=60)


def _scan_text(summ, cands, demo):
    """22:45 mesajının tek-metin sürümü (özet + her aday caption'ı) → /lastscan için."""
    parts = [summ] + [candidate_caption(c, watch=demo) for c in cands]
    return "\n\n".join(parts)


def main():
    test = "--test" in sys.argv
    demo_watch = "--demo-watch" in sys.argv
    asof = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else None

    if "--et-window" in sys.argv:
        ok, et = _et_window_ok()
        if not ok:
            print(f"[atlandı] ET {et:%Y-%m-%d %H:%M %a} pencere dışında "
                  f"(15:30–16:05 ET, hafta içi bekleniyor)")
            return

    cfg = s.Config()
    cfg.universe = s.UNIVERSE_PRESETS["sp500"]   # geniş evren: ~352 Mega+Large cap
    cfg.period = "5y"                    # FMP varsayılan-azamisi → sağlam SMA200/52H/RS
    cfg.price_source = "fmp"             # ücretli FMP
    cfg.use_earnings = False
    cfg.per_ticker_download = False
    cfg.disk_cache = bool(asof)          # canlı: taze; asof verilirse cache OK
    market = s.download_and_align_data(cfg)
    if asof is None:
        cfg.disk_cache = False
    # KIRILIM listesinden: elle tutulanlar + kağıt-portföyde açık olanlar düşülür (çift alım yok)
    paper_st = pt.load_state()
    held_union = sorted(set(_held()) | pt.held_symbols(paper_st))
    res = s.run_live_qswing_scan(market, cfg, asof=asof, held=held_union)

    cands, demo = res["buyable"], False          # tüm KIRILIM'ler için grafik+detay (puan sırasıyla)
    if not cands and demo_watch:
        cands = res["watch"][:3]; demo = True
    for i, c in enumerate(cands, 1):             # puan sırası numarası (caption başlığında #N)
        c["_rank"] = i

    summ = summary_text(res, demo=demo)
    os.makedirs(OUT, exist_ok=True)

    def _plain(t):
        for a, b in (("<b>", ""), ("</b>", ""), ("<i>", ""), ("</i>", ""), ("<code>", ""), ("</code>", "")):
            t = t.replace(a, b)
        return t

    def _lb63_subset(buyable):
        """💡 Şamdan varyantı girişi: KIRILIM listesinin 63g (çeyreklik) tepe kıran alt kümesi.
        63g tepe ≥ 40g tepe olduğundan bu DAİMA bir alt kümedir; tarama/sinyal mantığı değişmez."""
        out = []
        asof_ts = pd.Timestamp(res["asof"]).normalize()
        for c in buyable:
            df = market["data"].get(c["symbol"])
            if df is None or not len(df):
                continue
            sub = df[df.index <= asof_ts]
            if not len(sub):
                continue
            h63 = sub.iloc[-1].get("HIGH_PRIOR_63")
            if h63 is not None and not pd.isna(h63) and float(c["close"]) > float(h63):
                out.append(c)
        return out

    if test:
        print(_plain(summ), "\n")
        for c in cands:
            print(_plain(candidate_caption(c, watch=demo)), "\n")
        # Kağıt-trade SİMÜLASYONU (durum diske YAZILMAZ, Telegram'a gönderilmez)
        import copy
        sim = copy.deepcopy(paper_st)
        ex = pt.manage(sim, market, res["asof"])
        op = pt.open_new(sim, res["buyable"], res["asof"])
        print("=== KAĞIT-TRADE (simülasyon, kaydedilmedi) ===")
        print(_plain(pt.eod_message(op, ex, sim, res["asof"])))
        sim_e = copy.deepcopy(pt.load_state(pt.PAPER_EMA, variant="ema"))
        ex_e = pt.manage_ema(sim_e, market, res["asof"])
        op_e = pt.open_new(sim_e, res["buyable"], res["asof"])
        print("=== 8/21-EMA VARYANTI (simülasyon, kaydedilmedi) ===")
        print(_plain(pt.eod_message(op_e, ex_e, sim_e, res["asof"], tag="📐 8/21-EMA")))
        sim_c = copy.deepcopy(pt.load_state(pt.PAPER_CHAND, variant="chand"))
        ex_c = pt.manage_chand(sim_c, market, res["asof"])
        buy63 = _lb63_subset(res["buyable"])
        op_c = pt.open_new(sim_c, buy63, res["asof"])
        print(f"=== 💡 63G-ŞAMDAN VARYANTI (simülasyon, kaydedilmedi) · 63g filtre: "
              f"{len(res['buyable'])}→{len(buy63)} sinyal ===")
        print(_plain(pt.eod_message(op_c, ex_c, sim_c, res["asof"], tag="💡 63G-Şamdan")))
        print(f"\n[--test: {len(cands)} aday · {len(op)} açılan · {len(ex)} çıkan · gönderilmedi]")
        return

    token, chat = _secret("TELEGRAM_BOT_TOKEN"), _secret("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("HATA: TELEGRAM_BOT_TOKEN/CHAT_ID yok.", file=sys.stderr); sys.exit(2)

    # Alıcılar: sahip + /abone olan herkes (komut botu kaydeder)
    chats = [str(chat)] + [c for c in pt.load_subscribers() if c != str(chat)]

    def _bcast(fn, *args):
        """Tüm alıcılara gönder; yanıtı kontrol et (sessiz kayıp olmasın).
        Botu bloklayan (403) abone listeden otomatik düşürülür."""
        for c in chats:
            try:
                j = fn(*args, token=token, chat=c).json()
                if not j.get("ok"):
                    print(f"[send NON-OK] chat={c} {j.get('error_code')} {j.get('description')}", flush=True)
                    if j.get("error_code") == 403 and c != str(chat):
                        pt.remove_subscriber(c)
                        print(f"[abone düşürüldü] {c}", flush=True)
            except Exception as e:
                print(f"[send hata] chat={c} {e}", flush=True)

    _bcast(send_message, summ)
    for c in cands:
        cap = candidate_caption(c, watch=demo)
        path = os.path.join(OUT, f"qswing_{c['symbol']}.png")
        if draw_chart(c["symbol"], market["data"][c["symbol"]], c, res["asof"], path):
            _bcast(send_photo, path, cap)
        else:
            _bcast(send_message, cap)

    # --- Kağıt-trade: önce açık pozisyonları yönet (çıkışlar), sonra yeni KIRILIM'leri aç ---
    exited = pt.manage(paper_st, market, res["asof"])
    opened = pt.open_new(paper_st, res["buyable"], res["asof"])
    pt.save_state(paper_st)
    _bcast(send_message, pt.eod_message(opened, exited, paper_st, res["asof"], tag="🏆 ATR-trail"))

    # --- 8/21-EMA varyantı: girişler AYNI sinyallerden, yalnız çıkış kuralı farklı ---
    ema_st = pt.load_state(pt.PAPER_EMA, variant="ema")
    ema_ex = pt.manage_ema(ema_st, market, res["asof"])
    ema_op = pt.open_new(ema_st, res["buyable"], res["asof"])
    pt.save_state(ema_st, pt.PAPER_EMA)
    _bcast(send_message, pt.eod_message(ema_op, ema_ex, ema_st, res["asof"], tag="📐 8/21-EMA"))

    # --- 💡 63G-Şamdan varyantı: giriş = KIRILIM'ın 63g alt kümesi, çıkış = tepe−3.25×ATR (kapanış) ---
    ch_st = pt.load_state(pt.PAPER_CHAND, variant="chand")
    ch_ex = pt.manage_chand(ch_st, market, res["asof"])
    buy63 = _lb63_subset(res["buyable"])
    ch_op = pt.open_new(ch_st, buy63, res["asof"])
    pt.save_state(ch_st, pt.PAPER_CHAND)
    cmp_line = (f"\n<b>⚖️ Karşılaştırma (maliyet):</b> 🏆 ATR-trail <code>${pt._equity(paper_st):.0f}</code>"
                f" vs 📐 8/21-EMA <code>${pt._equity(ema_st):.0f}</code>"
                f" vs 💡 63G-Şamdan <code>${pt._equity(ch_st):.0f}</code>")
    _bcast(send_message, pt.eod_message(ch_op, ch_ex, ch_st, res["asof"], tag="💡 63G-Şamdan") + cmp_line)
    # /lastscan için son 22:45 mesajını kaydet
    pt.save_last_scan(_scan_text(summ, cands, demo), res["asof"])
    # dashboard için yapısal tarama verisi (eklemeli — mesaj/trade mantığını etkilemez)
    try:
        pt.save_scan_data(res)
    except Exception as _e:
        print(f"[scan_data kaydı atlandı] {_e}", flush=True)

    print(f"Gönderildi ({len(chats)} alıcı) · asof {res['asof']} · KIRILIM={len(res['buyable'])} · "
          f"grafik+detay={len(cands)} · İZLE={len(res['watch'])} · "
          f"kağıt: +{len(opened)} açıldı / -{len(exited)} çıktı / {len(paper_st['positions'])} açık · "
          f"ema: +{len(ema_op)} / -{len(ema_ex)} / {len(ema_st['positions'])} açık · "
          f"şamdan(63g {len(res['buyable'])}→{len(buy63)}): +{len(ch_op)} / -{len(ch_ex)} / {len(ch_st['positions'])} açık")


if __name__ == "__main__":
    main()

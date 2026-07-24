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
import os, sys, json, html, time
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd
import requests
import swing2_backtest as s
import paper_trader as pt
import qulla_paper as qp

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


def _filter_glitches(buyable, quotes, tol=0.25):
    """Veri-glitch çapraz kontrolü: tarama kapanışını BAĞIMSIZ gerçek-zamanlı FMP
    quote ile karşılaştır; oran (büyük/küçük) > 1+tol ise veri hatası say → AL
    listesinden DÜŞ. (2026-06-11 KLAC olayı: bulk veri hattı KLAC'ı 10× ölçekle
    verdi, quote gerçekti; sahte fiyat üç kağıt portföye de bulaştı.)
    Referans yoksa (quote dönmemişse) MUHAFAZAKÂR: adayı KORU → yanlış pozitif yok.
    Dönen: (temiz_liste, [(sembol, tarama_close, quote), ...])"""
    clean, dropped = [], []
    for c in buyable:
        ref = quotes.get(c["symbol"])
        sc = c.get("close")
        if ref and sc and ref > 0 and sc > 0 and (max(sc, ref) / min(sc, ref)) > (1 + tol):
            dropped.append((c["symbol"], sc, ref))
        else:
            clean.append(c)
    return clean, dropped


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


# NYSE tam-kapalı günler (yarım günler hariç: onlarda bar oluşur, sorun çıkmaz).
# Tatilde bar HİÇ gelmeyecektir → tekrar deneme de uyarı da anlamsız, sessiz geç.
NYSE_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}

# Bar gecikmesinde tekrar deneme. Son tarih 16:20 ET: piyasa 16:00'da kapanır ve
# bar KESİNLEŞİR; kalibrasyon zaten "15:45 girişi ≈ kapanış" diyor, dolayısıyla
# kapanış sonrası kesin barla giriş varsayımı bozmaz. 16:20'den sonrası ise
# "bugünü boşver, haber ver" bölgesi.
RETRY_ATTEMPTS, RETRY_WAIT_S, RETRY_DEADLINE = 4, 120, (16, 20)


def _now_et():
    """Şimdi (ABD Doğu). zoneinfo yoksa yerel saate düşer (deadline yine işler)."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return datetime.now()


def _is_market_holiday(day):
    """day (YYYY-MM-DD) NYSE'nin tam kapalı olduğu bir gün mü?"""
    return str(day) in NYSE_HOLIDAYS


def _stale_action(prev_locked, today):
    """asof defterdeki günden ileri gitmediğinde ne yapmalı?

    Üç farklı sebep aynı belirtiyi verir; ayırmazsak ya boş alarm çalar ya da
    gerçek arıza sessiz kalır:
      'yayınlandı' → defter BUGÜNDE kilitli: bugün zaten yayınlandı (elle tekrar
                     çalıştırma / ikinci cron slotu). Sessiz no-op — alarm YOK.
      'tatil'      → NYSE kapalı: bar hiç oluşmayacak. Sessiz — alarm YOK.
      'gecikme'    → piyasa açıktı, bar GELMELİYDİ ama yok (2026-07-14 FMP
                     gecikmesi). Tekrar dene; yine yoksa KULLANICIYI UYAR.
    """
    if str(prev_locked) >= str(today):
        return "yayınlandı"
    if _is_market_holiday(today):
        return "tatil"
    return "gecikme"


def _wait_for_new_bar(prev_locked, *, runner, now_et, sleeper=time.sleep,
                      attempts=RETRY_ATTEMPTS, wait_s=RETRY_WAIT_S,
                      deadline=RETRY_DEADLINE):
    """Bugünün barı gecikmişse taramayı tekrarla (FMP'yi yeniden yoklar).

    2026-07-14: FMP barı 15:45 ET'de vermedi, ~10 dk sonra verdi; script tek
    denemede pes edip sessizce sustu. Artık son tarihe kadar tekrar denenir.
    Dönen: (qr, asof, deneme_sayısı) — bar hâlâ yoksa (None, None, deneme).
    """
    tried = 0
    for _ in range(attempts):
        now = now_et()
        if now.hour * 60 + now.minute >= deadline[0] * 60 + deadline[1]:
            break
        sleeper(wait_s)
        tried += 1
        qr = runner(None)
        if qr["asof"] > prev_locked:
            print(f"[bar geldi] {tried}. denemede asof {qr['asof']} (FMP gecikmesi)",
                  flush=True)
            return qr, qr["asof"], tried
        print(f"[bekleniyor] {tried}. deneme: bar hâlâ {qr['asof']}", flush=True)
    return None, None, tried


def _stale_alert_text(prev_locked, tried, et):
    """Sessiz kalma: bugün neden yayın olmadığını Telegram'dan söyle."""
    return ("⚠️ <b>Bugün tarama yapılamadı</b>\n\n"
            f"FMP {et:%Y-%m-%d} gününün barını vermedi "
            f"({tried} deneme, sonuncusu {et:%H:%M} ET).\n"
            f"Defter <code>{prev_locked}</code> gününde kilitli kaldı — "
            "<b>yayın yok, işlem yok, pozisyonlar değişmedi.</b>\n\n"
            "Veri gelince elle çalıştır:\n"
            "<code>python3 live_scan_telegram.py</code>")


def _tg_targets():
    """(token, alıcılar) — sahip + /abone olanlar. Yoksa (None, [])."""
    token, chat = _secret("TELEGRAM_BOT_TOKEN"), _secret("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return None, []
    return token, [str(chat)] + [c for c in pt.load_subscribers() if c != str(chat)]


def _bcast(fn, *args, token=None, chats=()):
    """Tüm alıcılara gönder; yanıtı kontrol et (sessiz kayıp olmasın).
    Botu bloklayan (403) abone listeden otomatik düşürülür."""
    for c in chats:
        try:
            j = fn(*args, token=token, chat=c).json()
            if not j.get("ok"):
                print(f"[send NON-OK] chat={c} {j.get('error_code')} {j.get('description')}", flush=True)
                if j.get("error_code") == 403 and c != chats[0]:
                    pt.remove_subscriber(c)
                    print(f"[abone düşürüldü] {c}", flush=True)
        except Exception as e:
            print(f"[send hata] chat={c} {e}", flush=True)


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
    asof = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else None

    if "--et-window" in sys.argv:
        ok, et = _et_window_ok()
        if not ok:
            print(f"[atlandı] ET {et:%Y-%m-%d %H:%M %a} pencere dışında "
                  f"(15:30–16:05 ET, hafta içi bekleniyor)")
            return

    # 👑 Qulla-21 (TEK yöntem): backtest-replay 2026-06-04→asof
    #    RS top-50 sistematik evren + 63g kırılım girişi + split çıkış (yarı +2R / kalan 21-EMA runner)
    auto = asof is None                                   # cron modu: asof otomatik çözülür
    prev_locked = (qp.load_ledger() or {}).get("last_date")
    qr = qp.run_qulla(asof)
    market = qr["market"]
    asof = qr["asof"]

    # YAYIN KAPISI: otomatik modda yeni bar yoksa (ABD tatili / FMP'de bar gecikmesi) asof
    # defterde zaten kilitli güne çözülür → aynı gün-sonu raporu İKİNCİ kez yayınlanır ve
    # "bugün işlem yapılmış" izlenimi verir (2026-07-03, 4 Temmuz tatili olayı). Defter
    # zaten ilerlemez; yayını da kes. Bilinçli tekrar için --asof ver (kapıya takılmaz).
    if auto and prev_locked and asof <= prev_locked:
        now = _now_et()
        today = f"{now:%Y-%m-%d}"
        action = _stale_action(prev_locked, today)
        if action == "yayınlandı":
            print(f"[atlandı] {today} zaten yayınlandı (defter kilitli) — yayın yok")
            return
        if action == "tatil":
            print(f"[atlandı] {today} NYSE tatili — bar zaten oluşmayacak; yayın yok")
            return
        # Tatil değil, bugün de yayınlanmadı → bar GELMELİYDİ. Sessizce pes etme:
        # son tarihe kadar tekrar dene (2026-07-14: FMP ~10 dk gecikti), olmazsa uyar.
        print(f"[gecikme] bar yok (defter {prev_locked}'te kilitli) — tekrar deneniyor", flush=True)
        qr2, asof2, tried = _wait_for_new_bar(
            prev_locked, runner=qp.run_qulla, now_et=_now_et)
        if qr2 is None:
            token, chats = _tg_targets()
            if token:
                _bcast(send_message, _stale_alert_text(prev_locked, tried, now),
                       token=token, chats=chats)
            print(f"[UYARI gönderildi] bar {tried} denemede de gelmedi — yayın yok",
                  file=sys.stderr)
            sys.exit(1)
        qr, asof, market = qr2, asof2, qr2["market"]
    summ = qp.qulla_summary(qr)
    cands = qp.chart_cands(qr)       # bugün açılan Qulla girişleri (grafik)
    msg = qp.qulla_message(qr)       # portföy gün-sonu
    os.makedirs(OUT, exist_ok=True)

    def _plain(t):
        for a, b in (("<b>", ""), ("</b>", ""), ("<i>", ""), ("</i>", ""),
                     ("<code>", ""), ("</code>", ""), ("&lt;", "<")):
            t = t.replace(a, b)
        return t

    if test:
        print(_plain(summ), "\n")
        for c in cands:
            print(_plain(qp.chart_caption(c)), "\n")
        print("=== 👑 QULLA-21 PORTFÖY (simülasyon, kaydedilmedi) ===")
        print(_plain(msg))
        print(f"\n[--test: {len(cands)} giriş · {len(qr['exited'])} çıkış · "
              f"{len(qr['positions'])} açık · gönderilmedi]")
        return

    token, chats = _tg_targets()
    if not token:
        print("HATA: TELEGRAM_BOT_TOKEN/CHAT_ID yok.", file=sys.stderr); sys.exit(2)

    _bcast(send_message, summ, token=token, chats=chats)
    for c in cands:
        cap = qp.chart_caption(c)
        path = os.path.join(OUT, f"qulla_{c['symbol']}.png")
        if draw_chart(c["symbol"], market["data"][c["symbol"]], c, asof, path):
            _bcast(send_photo, path, cap, token=token, chats=chats)
        else:
            _bcast(send_message, cap, token=token, chats=chats)
    _bcast(send_message, msg, token=token, chats=chats)

    # /lastscan için son mesajı + dashboard için Qulla durumunu + yapısal tarama verisini kaydet
    pt.save_last_scan("\n\n".join([summ] + [qp.chart_caption(c) for c in cands] + [msg]), asof)
    try:
        qp.commit_ledger(qr)   # GERÇEK DEFTERİ İLERLET: bugünü kilitle (yalnız gerçek gönderimde)
    except Exception as _e:
        print(f"[qulla defter commit atlandı] {_e}", flush=True)
    try:
        qp.write_state(qr)
    except Exception as _e:
        print(f"[qulla state kaydı atlandı] {_e}", flush=True)
    try:
        pt.save_scan_data({"asof": asof, "regime_open": qr["regime_open"],
                           "buyable": cands, "watch": []})
    except Exception as _e:
        print(f"[scan_data kaydı atlandı] {_e}", flush=True)

    print(f"Gönderildi ({len(chats)} alıcı) · asof {asof} · 👑 Qulla-21 · "
          f"giriş={len(cands)} · çıkış={len(qr['exited'])} · açık={len(qr['positions'])} · "
          f"toplam {(qr['cost_equity']/qp.INITIAL-1)*100:+.1f}% vs SPY {qr['spy_roi']:+.1f}%")


if __name__ == "__main__":
    main()

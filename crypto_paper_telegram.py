#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🪙 KRİPTO kağıt-trade + Telegram — Binance günlük kapanış (00:00 UTC) sonrası.

Strateji (backtest 15-hücre + ATR-rejim ızgarası ŞAMPİYONU, 2026-06 kalibrasyonu):
  • GİRİŞ: qswing 40g kırılım (BTC rejim kapısı: BTCUSDT>SMA200) + BTC OYNAKLIK KİLİDİ
    (BTCUSDT ATR20% > 2.5 → piyasa testere, yeni alım YOK; ızgara: DD −36%→−13%, ROI ↑).
  • ÇIKIŞ: HYBRID_TREND — %50 kapanış<EMA8, %50 (runner) kapanış<EMA21. Sabit hedef yok.
    (paper_trader.manage_ema = backtest tp_grid/HYBRID_TREND, ma_confirm_close birebir.)
  • Eşit-ağırlık giriş, slippage modeli paper_trader ile aynı (giriş +3bps, çıkış −10bps).

Zamanlama: kripto günlük barı 00:00 UTC'de kapanır (TR 03:00). Cron UTC 00:15 / TR 03:15:
  15 0 * * *  cd /path/to/swing-backtest-lab && python3 crypto_paper_telegram.py >> cron_crypto.log 2>&1
  (sunucu TR saatindeyse:  15 3 * * * ...)
7 gün/hafta çalışır (hafta sonu dahil — kripto kapanmaz). --utc-window bayrağı cron'un
yanlış saatte tetiklenmesine karşı 00:05–02:00 UTC dışını atlar (DST koruması analoğu).

Durum: ~/.swing_paper_crypto.json (10.000$ başlangıç) · son tarama: ~/.swing_lastscan_crypto.json
Alıcı: yalnız TELEGRAM_CHAT_ID (hisse abone listesine kripto yayını GÖNDERİLMEZ).
Kullanım: python3 crypto_paper_telegram.py [--test] [--asof YYYY-MM-DD] [--utc-window]
"""
import os, sys, html
from datetime import datetime, timezone

import pandas as pd
import swing2_backtest as s
import paper_trader as pt
import live_scan_telegram as lst          # _secret, send_message, send_photo, draw_chart (yeniden kullanım)
from crypto_data import load_pinned_universe, quote_binance
from short_backtest import live_short_candidates

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "swing2_out")
REGIME_ATR_MAX = 2.5      # BTC ATR20% kilidi — crypto_regime_grid.csv şampiyonu
TAG = "🪙 Kripto-HYBRID"


def crypto_cfg():
    cfg = s.Config()
    cfg.universe = load_pinned_universe()
    cfg.benchmark = "BTCUSDT"
    cfg.price_source = "binance"
    cfg.use_earnings = False
    cfg.period = "3y"                      # SMA200 + HIGH52(365) + warmup için bol
    cfg.high52_bars = 365
    cfg.warmup_bars = 380
    cfg.regime_atr_filter = True           # BTC oynaklık kilidi (ızgara şampiyonu)
    cfg.regime_atr_threshold = REGIME_ATR_MAX
    return cfg


def _utc_window_ok(lo=(0, 5), hi=(2, 0)):
    """UTC [00:05, 02:00] penceresinde miyiz? (cron yanlış saat koruması; kripto 7g/hafta)."""
    now = datetime.now(timezone.utc)
    mins = now.hour * 60 + now.minute
    return (lo[0] * 60 + lo[1]) <= mins <= (hi[0] * 60 + hi[1]), now


def candidate_caption(c, rank=None):
    """KIRILIM adayı metni — HYBRID_TREND çıkışlı kripto sürümü."""
    e = html.escape
    f = pt._fmt
    sc = c.get("score")
    p = c.get("score_parts") or {}
    rk = f"#{rank} · " if rank else ""
    score_line = (f"🏆 <b>{rk}Puan {sc}/100</b> "
                  f"<i>(RS {p.get('rs','?')}/45 · 52H {p.get('near52','?')}/20 · "
                  f"taze {p.get('fresh','?')}/20 · risk {p.get('risk','?')}/15)</i>\n") if sc is not None else ""
    return (f"<b>{e(c['symbol'])}</b> · 🚀 KIRILIM\n"
            + score_line +
            f"🎯 Giriş <code>${f(c['entry'])}</code> · Stop <code>${f(c['stop'])}</code> "
            f"(risk %{c['risk_pct']})\n"
            f"📈 {c['breakout_lb']}g tepe <code>${f(c['high40'])}</code> aşıldı · "
            f"52H'ye %{c['dist_52h_pct']} · SMA20'ye %{c['dist_sma20_pct']}\n"
            f"⚖️ RS <b>+{c['rs']}</b> (60g · BTC'ye karşı) · 2a getiri %{c['ret_3m']}\n"
            f"📤 Çıkış (HYBRID_TREND): %50 kapanış&lt;EMA8 <code>${f(c.get('ema8'))}</code> · "
            f"%50 kapanış&lt;EMA21 <code>${f(c.get('ema21'))}</code> — sabit hedef yok, trend ne verirse")


def summary_text(res):
    flag = "🟢 AÇIK" if res["regime_open"] else "🔴 KAPALI"
    L = [f"<b>🪙 Kripto qswing Kırılım Tarayıcı ({res['asof']})</b>",
         f"🕒 00:00 UTC kapanışı · Rejim: {flag} · BTC ${res['spy_close']:,.0f} · "
         f"{res['n_universe']} coin"]
    if not res["regime_open"]:
        L.append("\n⚠️ <b>Rejim KAPALI</b> (BTC&lt;SMA200) → yeni alım YOK; sadece pozisyon yönetimi.")
    if res.get("vol_locked"):
        L.append(f"\n🌪 <b>OYNAKLIK KİLİDİ</b>: BTC ATR20% = {res.get('spy_atr_pct')}% &gt; "
                 f"{REGIME_ATR_MAX}% → piyasa testere, kırılımlar İZLE'ye düştü (yeni alım yok).")
    elif res.get("spy_atr_pct") is not None:
        L.append(f"🌡 BTC ATR20%: {res['spy_atr_pct']}% (kilit eşiği {REGIME_ATR_MAX}%)")
    n = len(res["buyable"])
    L.append(f"\n🚀 <b>KIRILIM: {n}</b>" + (" — puana göre sıralı, aşağıda grafik+detay 👇" if n else
             f" ({res['breakout_lb']}g tepe + 52H yakın + BTC'yi geçen momentum koşulunu geçen yok)"))
    if n:
        rank = " · ".join(f"{i}.{html.escape(r['symbol'])} <b>{r.get('score','?')}</b>"
                          for i, r in enumerate(res["buyable"], 1))
        L.append(f"🏆 <b>Sıralama (puan):</b> {rank}")
    vol_watch = [r for r in res["watch"] if r.get("watch_reason") == "vol_lock"]
    if vol_watch:
        w = " · ".join(html.escape(r["symbol"]) for r in vol_watch[:10])
        L.append(f"🌪 <b>İZLE — kilit nedeniyle bekleyen kırılım:</b> {w}")
    near = [r for r in res["watch"] if r.get("watch_reason") == "near"]
    if near:
        w = " · ".join(f"{html.escape(r['symbol'])}(tepeye %{r['dist_to_breakout_pct']})" for r in near[:10])
        L.append(f"🟡 <b>İZLE — tepeye ≤%3:</b> {w}")
    L.append("\n<i>Strateji: qswing 40g kırılım + BTC rejim/oynaklık kapıları · HYBRID_TREND çıkış "
             "(%50 EMA8 · %50 EMA21, kapanış teyitli). Binance spot günlük bar. Eğitim amaçlı.</i>")
    return "\n".join(L)


def main():
    test = "--test" in sys.argv
    asof = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else None

    if "--utc-window" in sys.argv:
        ok, now = _utc_window_ok()
        if not ok:
            print(f"[atlandı] UTC {now:%Y-%m-%d %H:%M} pencere dışında (00:05–02:00 UTC bekleniyor)")
            return

    cfg = crypto_cfg()
    market = s.download_and_align_data(cfg)

    paper_st = pt.load_state(pt.PAPER_CRYPTO, variant="ema")
    res = s.run_live_qswing_scan(market, cfg, asof=asof, held=sorted(pt.held_symbols(paper_st)))

    # ⚖️ Birleşik U/K defteri için kısa tarama (yalnız ayı rejiminde aday döner; kilitsiz;
    # tutulan-sembol filtresi open_new_short içinde — bugünkü çıkışlardan SONRAKİ duruma göre)
    ls_st = pt.load_state(pt.PAPER_CRYPTO_LS, variant="ema")
    _sdate, _bear, short_cands = live_short_candidates(market, asof=asof)

    def _ls_step(st):
        """Birleşik defteri bir gün ilerlet: önce çıkışlar (iki yön), sonra rejime göre giriş."""
        n0 = len(st["closed"])
        pt.manage_ema(st, market, res["asof"])
        for r in st["closed"][n0:]:
            r.setdefault("side", "long")
        pt.manage_short_hybrid(st, market, res["asof"])
        exited = st["closed"][n0:]
        op_l, op_s = [], []
        if res["regime_open"]:
            shorted = {p["symbol"] for p in st.get("short_positions", [])}
            op_l = pt.open_new(st, [c for c in res["buyable"] if c["symbol"] not in shorted],
                               res["asof"])           # kilitliyken buyable zaten boş
        else:
            op_s = pt.open_new_short(st, short_cands, res["asof"])
        return op_l, op_s, exited

    cands = res["buyable"]
    for i, c in enumerate(cands, 1):
        c["_rank"] = i
    summ = summary_text(res)
    os.makedirs(OUT, exist_ok=True)

    def _plain(t):
        for a, b in (("<b>", ""), ("</b>", ""), ("<i>", ""), ("</i>", ""),
                     ("<code>", ""), ("</code>", ""), ("&lt;", "<"), ("&gt;", ">")):
            t = t.replace(a, b)
        return t

    if test:
        print(_plain(summ), "\n")
        for i, c in enumerate(cands, 1):
            print(_plain(candidate_caption(c, rank=i)), "\n")
        import copy
        sim = copy.deepcopy(paper_st)
        ex = pt.manage_ema(sim, market, res["asof"])
        op = pt.open_new(sim, res["buyable"], res["asof"])
        print("=== 🪙 KRİPTO KAĞIT-TRADE (simülasyon, kaydedilmedi) ===")
        print(_plain(pt.eod_message(op, ex, sim, res["asof"], tag=TAG)))
        sim_ls = copy.deepcopy(ls_st)
        op_l, op_s, ex_ls = _ls_step(sim_ls)
        print(f"=== ⚖️ U/K BİRLEŞİK (simülasyon, kaydedilmedi) · kısa aday: {len(short_cands)} ===")
        print(_plain(pt.ls_eod_message(op_l, op_s, ex_ls, sim_ls, res["asof"])))
        print(f"\n[--test: {len(cands)} uzun aday · {len(short_cands)} kısa aday · gönderilmedi]")
        return

    token, chat = lst._secret("TELEGRAM_BOT_TOKEN"), lst._secret("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("HATA: TELEGRAM_BOT_TOKEN/CHAT_ID yok.", file=sys.stderr)
        sys.exit(2)

    def _send_text(text):
        try:
            j = lst.send_message(text, token, chat).json()
            if not j.get("ok"):
                print(f"[send NON-OK] {j.get('error_code')} {j.get('description')}", flush=True)
        except Exception as e:
            print(f"[send hata] {e}", flush=True)

    _send_text(summ)
    for i, c in enumerate(cands, 1):
        cap = candidate_caption(c, rank=i)
        path = os.path.join(OUT, f"crypto_{c['symbol']}.png")
        try:
            ok = lst.draw_chart(c["symbol"], market["data"][c["symbol"]], c, res["asof"], path)
        except Exception:
            ok = False
        if ok:
            try:
                lst.send_photo(path, cap, token, chat)
            except Exception as e:
                print(f"[foto hata] {c['symbol']} {e}", flush=True); _send_text(cap)
        else:
            _send_text(cap)

    # --- Kağıt-trade: önce açık pozisyonları yönet (çıkışlar), sonra yeni KIRILIM'leri aç ---
    exited = pt.manage_ema(paper_st, market, res["asof"])
    opened = pt.open_new(paper_st, res["buyable"], res["asof"])
    pt.save_state(paper_st, pt.PAPER_CRYPTO)
    _send_text(pt.eod_message(opened, exited, paper_st, res["asof"], tag=TAG))

    # --- ⚖️ Birleşik U/K defteri: rejim anahtarlı (uzun: kırılım+kilit · kısa: ½ boy, kilitsiz) ---
    op_l, op_s, ex_ls = _ls_step(ls_st)
    pt.save_state(ls_st, pt.PAPER_CRYPTO_LS)
    _send_text(pt.ls_eod_message(op_l, op_s, ex_ls, ls_st, res["asof"]))

    pt.save_last_scan("\n\n".join([summ] + [candidate_caption(c, rank=i)
                                            for i, c in enumerate(cands, 1)]),
                      res["asof"], path=pt.LASTSCAN_CRYPTO)

    print(f"Gönderildi · asof {res['asof']} · rejim={'AÇIK' if res['regime_open'] else 'KAPALI'} · "
          f"kilit={'EVET' if res.get('vol_locked') else 'hayır'} (BTC ATR20% {res.get('spy_atr_pct')}) · "
          f"KIRILIM={len(res['buyable'])} · kısa aday={len(short_cands)} · "
          f"kağıt: +{len(opened)}/-{len(exited)}/{len(paper_st['positions'])} açık · "
          f"U/K: +{len(op_l)}U+{len(op_s)}K/-{len(ex_ls)}/"
          f"{len(ls_st['positions'])}U+{len(ls_st.get('short_positions', []))}K açık")


if __name__ == "__main__":
    main()

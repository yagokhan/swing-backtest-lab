#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DENEME: dünün (son tamamlanmış seans) taraması → Telegram'a ZENGİN gönderim.
Tarayıcı sürümü gibi: her aday için 8-katman dökümü + H/R detayı + mum grafiği (giriş/stop/hedef).
ALINABİLİR yoksa demo amaçlı en yüksek İZLE adaylarını (skor≥14) tam detayla gösterir.
Kullanım: python3 trial_scan_send.py [--asof YYYY-MM-DD] [--test]
"""
import os, sys, html, json, datetime as dt
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd
import requests
import swing2_backtest as s
from live_scan_telegram import _secret, _held

LAYER_NAMES = {1: "Stage", 2: "VCP/Patern", 3: "Kurumsal", 4: "Piyasa/Sektör",
               5: "Opsiyon", 6: "Momentum", 7: "R/R", 8: "Bilanço"}
OUT = "/home/gokhan/swing2_out"


def draw_chart(sym, df, cand, asof, path, nbars=45):
    """Son nbars Heikin Ashi mumu + SMA20/50 + giriş/stop/hedef yatay çizgileri.
    Mumlar HA (görsel); SMA/çizgiler ham fiyat. Trade mantığı/veri değişmez."""
    full = df.loc[:asof].dropna(subset=["Open", "High", "Low", "Close"])
    if len(full) < 5:
        return False
    d = full.tail(nbars)                      # ham (SMA sütunları + index)
    ha = s.heikin_ashi(full).tail(nbars)      # HA tüm geçmişle, sonra kesilir
    fig, ax = plt.subplots(figsize=(10, 5.6))
    for i, (_, r) in enumerate(ha.iterrows()):
        up = r["Close"] >= r["Open"]
        col = "#16a34a" if up else "#dc2626"
        ax.plot([i, i], [r["Low"], r["High"]], color=col, lw=0.8, zorder=2)
        h = abs(r["Close"] - r["Open"]) or (r["Close"] * 0.001)
        ax.add_patch(Rectangle((i - 0.3, min(r["Open"], r["Close"])), 0.6, h,
                               color=col, zorder=3))
    x = range(len(d))
    if "SMA20" in d: ax.plot(x, d["SMA20"].values, color="#2563eb", lw=1.1, label="SMA20", zorder=1)
    if "SMA50" in d: ax.plot(x, d["SMA50"].values, color="#f59e0b", lw=1.1, label="SMA50", zorder=1)
    ax.axhline(cand["entry"], color="#3b82f6", ls="--", lw=1.2, label=f"Giriş {cand['entry']}")
    ax.axhline(cand["stop"], color="#dc2626", ls="--", lw=1.2, label=f"Stop {cand['stop']}")
    ax.axhline(cand["target"], color="#16a34a", ls="--", lw=1.2, label=f"Hedef {cand['target']}")
    # tarih etiketleri (5 nokta)
    idx = list(d.index)
    ticks = list(range(0, len(idx), max(1, len(idx)//5)))
    ax.set_xticks(ticks); ax.set_xticklabels([idx[t].strftime("%m-%d") for t in ticks], fontsize=8)
    ax.set_title(f"{sym} · {asof} · skor {cand['score']}/24 · {cand['decision']} · Heikin Ashi", fontsize=11)
    ax.set_ylabel("Fiyat ($)"); ax.legend(fontsize=8, loc="best"); ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)
    return True


def candidate_caption(cand):
    e = html.escape
    ed = "—" if cand["earnings_days"] is None else f"{cand['earnings_days']}g"
    layers = " · ".join(f"{LAYER_NAMES[i]} {cand['layers'].get('L'+str(i),0)}" for i in range(1, 9))
    cap = (f"<b>{e(cand['symbol'])}</b> · {e(cand['sector_etf'])} · <b>skor {cand['score']}/24</b>\n"
           f"📋 {e(cand['decision'])}\n"
           f"🎯 Giriş <code>${cand['entry']}</code> · Stop <code>${cand['stop']}</code> · "
           f"Hedef <code>${cand['target']}</code>\n"
           f"⚖️ Risk %{cand['risk_pct']} · R/R {cand['rr_potential']} · "
           f"SMA20'ye %{cand['dist_sma20_pct']} · Bilanço {ed}\n"
           f"🧱 {layers}")
    dist = cand.get("dist_sma20_pct") or 0
    if dist > 25:
        cap += (f"\n⚠️ <b>AŞIRI UZAMIŞ</b> (SMA20'ye %{dist}) — parabolik/climax, "
                f"chase riski yüksek. Geri çekilmeyi bekle veya pas geç.")
    return cap


def main():
    test = "--test" in sys.argv
    asof = None
    if "--asof" in sys.argv:
        asof = sys.argv[sys.argv.index("--asof") + 1]

    cfg = s.Config()
    cfg.universe = s.DEFAULT_UNIVERSE; cfg.period = "2y"
    cfg.use_earnings = False; cfg.per_ticker_download = False
    cfg.disk_cache = True; cfg.min_score = 16
    market = s.download_and_align_data(cfg)

    # "dün" = bugünden önceki son tamamlanmış seans
    if asof is None:
        today = pd.Timestamp.now().normalize()
        prior = [d for d in market["calendar"] if d < today]
        asof = (prior[-1] if prior else market["calendar"][-1]).strftime("%Y-%m-%d")

    res = s.run_live_pre_close_scan(market, cfg, asof=asof, held=_held())
    data = market["data"]

    # adaylar: ALINABİLİR; yoksa demo için en iyi İZLE (skor≥14)
    cands = res["buyable"]
    demo = False
    if not cands:
        cands = [r for r in res["watch"] if r["score"] >= 14][:3]
        demo = True

    # özet mesaj
    flag = "🟢 AÇIK" if res["regime_open"] else "🔴 KAPALI"
    head = [f"<b>📊 Swing 2.0 — DENEME taraması (dün: {res['asof']})</b>",
            f"🕒 15:45 ET kapanış-öncesi · Rejim: {flag} · SPY ${res['spy_close']}"]
    if res["buyable"]:
        head.append(f"\n🟢 <b>ALINABİLİR: {len(res['buyable'])}</b> (skor≥16, kill-switch temiz)")
    else:
        head.append("\n🟢 <b>ALINABİLİR: YOK</b> (skor≥16 eşiğini geçen yok)")
        if demo:
            head.append(f"🟡 Demo: en yüksek <b>İZLE</b> adayları (skor≥14) tam detayla gönderiliyor.")
    msg = "\n".join(head)

    token, chat = _secret("TELEGRAM_BOT_TOKEN"), _secret("TELEGRAM_CHAT_ID")
    os.makedirs(OUT, exist_ok=True)

    if test:
        print(msg, "\n")
        for c in cands:
            print(candidate_caption(c).replace("<b>", "").replace("</b>", "")
                  .replace("<code>", "").replace("</code>", ""), "\n")
        print(f"[--test: {len(cands)} aday · gönderilmedi]")
        return

    # 1) özet
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  data={"chat_id": chat, "text": msg, "parse_mode": "HTML",
                        "disable_web_page_preview": "true"}, timeout=30)
    # 2) her aday: grafik + H/R detayı (caption)
    sent = 0
    for c in cands:
        path = os.path.join(OUT, f"trial_{c['symbol']}.png")
        ok = draw_chart(c["symbol"], data[c["symbol"]], c, res["asof"], path)
        cap = candidate_caption(c)
        if demo:
            cap = "🟡 <i>(İZLE — eşik altı, demo)</i>\n" + cap
        if ok:
            with open(path, "rb") as ph:
                requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                              data={"chat_id": chat, "caption": cap, "parse_mode": "HTML"},
                              files={"photo": ph}, timeout=60)
        else:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": cap, "parse_mode": "HTML"}, timeout=30)
        sent += 1
    print(f"Gönderildi · özet + {sent} aday (grafik+detay) · asof {res['asof']} · "
          f"ALINABİLİR={len(res['buyable'])}")


if __name__ == "__main__":
    main()

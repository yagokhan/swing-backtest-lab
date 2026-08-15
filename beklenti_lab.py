#!/usr/bin/env python3
"""Beklenti Karnesi: canlı Qulla-21 penceresi normal varyans mı? (spec: 2026-08-15)

SALT-OKUR: canlı defter/state/depoya asla yazmaz; commit_ledger/write_state/
load_market_incremental/_save_store ÇAĞRILMAZ. Çıktılar swing2_out/beklenti/.
"""
import json
import os
import sys

import pandas as pd

HOME = os.path.expanduser("~")
OUT = os.path.join(HOME, "swing2_out", "beklenti")
LEDGER_PATH = os.path.join(HOME, ".swing_paper_qulla_ledger.json")
BACKUP_PATH = LEDGER_PATH + ".bak.20260705-aday3"
START, SON, NWIN = "2026-05-27", "2026-08-14", 56
FWD = "2026-07-06"                    # Aday 3 kararı 07-05; sonrası saf forward
MIN_START = "2021-07-01"              # SMA200+RS ısınması


def pct_rank(vals, x):
    vals = sorted(vals)
    return round(100.0 * sum(1 for v in vals if v <= x) / len(vals), 1)


def max_drawdown(vals):
    peak, mdd = float("-inf"), 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100)
    return round(mdd, 4)


def roi(first, last):
    return round((last / first - 1) * 100, 4)


def window_starts(n_cal, step, first_idx, force_idx, nwin=NWIN):
    out = sorted(set(list(range(first_idx, n_cal - nwin + 1, step)) + [force_idx]))
    return [i for i in out if first_idx <= i <= n_cal - nwin]


def _save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    tmp = os.path.join(OUT, name + ".tmp")
    with open(tmp, "w") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, os.path.join(OUT, name))


def _load(name):
    with open(os.path.join(OUT, name)) as fh:
        return json.load(fh)


def load_market_ro():
    """Depodan salt-okur market inşası. attach_watchlist ZORUNLU (RS tuzağı)."""
    import qulla_paper as qp
    import swing2_backtest as s2
    store = qp._load_store()
    assert str(store["last_date"])[:10] >= SON, f"depo eski: {store['last_date']}"
    cfg = qp._cfg(SON)
    market = s2.build_market_from_frames(store["frames"], cfg)
    s2.attach_watchlist(market, cfg)
    return market


def _mk_cfg(start, end):
    import qulla_paper as qp
    cfg = qp._cfg(str(end)[:10])
    cfg.start_date = str(start)[:10]
    cfg.liquidate_at_end = True           # pencere sonunda MTM; canlı False kullanır
    return cfg


def run_window(market, cal, i, nwin=NWIN, detail=False):
    import qulla_paper as qp
    start, end = cal[i], cal[i + nwin - 1]
    bt = qp.DengeBacktester(_mk_cfg(start, end), market=market)
    bt.run()
    eq = [v for _, v in bt.equity_curve]
    spy = market["spy"]["Close"]
    s0, s1 = float(spy.asof(start)), float(spy.asof(end))
    r = roi(eq[0], eq[-1])
    row = {"start": str(start)[:10], "end": str(end)[:10], "roi": float(r),
           "spy": roi(s0, s1), "alpha": round(float(r) - roi(s0, s1), 4),
           "maxdd": float(max_drawdown(eq))}
    if detail:
        girisler = {(t.symbol, str(pd.Timestamp(t.entry_date).date())) for t in bt.trades}
        girisler |= {(p.symbol, str(pd.Timestamp(p.entry_date).date()))
                     for p in bt.positions.values()}
        row["_girisler"] = sorted(girisler)
        row["_curve"] = {str(pd.Timestamp(d).date()): v for d, v in bt.equity_curve}
    return row


def dagilim(smoke=False):
    market = load_market_ro()
    cal = list(pd.DatetimeIndex(sorted(market["spy"].index)))
    first_idx = next(i for i, d in enumerate(cal) if str(d)[:10] >= MIN_START)
    force_idx = next(i for i, d in enumerate(cal) if str(d)[:10] == START)
    starts = window_starts(len(cal), 10, first_idx, force_idx)
    if smoke:
        starts = starts[:2] + [force_idx]
        print("DUMAN MODU: yalnız 3 pencere")
    print(f"{len(starts)} pencere koşulacak (adım 10 işlem günü, "
          f"{cal[first_idx].date()} → {cal[starts[-1]].date()})", flush=True)
    rows = []
    canli_detay = None
    for k, i in enumerate(starts):
        r = run_window(market, cal, i, detail=(i == force_idx))
        if i == force_idx:
            canli_detay = {"girisler": r.pop("_girisler"), "curve": r.pop("_curve")}
        rows.append(r)
        if (k + 1) % 10 == 0 or k == len(starts) - 1:
            print(f"  {k+1}/{len(starts)} · son: {rows[-1]}", flush=True)
            _save("dagilim.json", {"rows": rows, "parite": None, "full_curve": None})
    # PARİTE KAPISI v2 (2026-08-15 teşhisi): FMP veri revizyonları birebir ROI paritesini
    # imkânsız kılar (TAM depo yenilemeleri kalabalık-gün sıralamasını çevirir). Kod-doğruluğu
    # YAPISAL doğrulanır (fail-closed): giriş örtüşmesi ≥%90 VE 07-06 öncesi izleme <%0,3.
    # ROI farkı 'drift' olarak KAYDEDİLİR → karnede çift yerleştirme (defter + replay).
    led = json.load(open(LEDGER_PATH))
    led_roi = roi(10000.0, led["equity_curve"][-1][1])
    canli = next(r for r in rows if r["start"] == START)
    led_all = {(t["symbol"], t["entry_date"]) for t in led["trades"]}
    led_all |= {(p["symbol"], p["entry_date"]) for p in led["positions"]}
    fr_all = {tuple(g) for g in canli_detay["girisler"]}
    ortusme = len(led_all & fr_all) / max(1, len(led_all)) * 100
    ledc = {d: v for d, v in led["equity_curve"]}
    izleme = max((abs(canli_detay["curve"][d] / ledc[d] - 1) * 100
                  for d in ledc if d < FWD and d in canli_detay["curve"]), default=99.0)
    parite = {"kosu_roi": canli["roi"], "defter_roi": led_roi,
              "drift": round(canli["roi"] - led_roi, 4),
              "giris_ortusme_pct": round(ortusme, 1),
              "fwd_oncesi_izleme_pct": round(izleme, 3)}
    print("parite v2:", parite, flush=True)
    # Tam eğri (kayan-dilim yan notu için) — duman modunda atla
    full = None
    if not smoke:
        import qulla_paper as qp
        bt = qp.DengeBacktester(_mk_cfg(cal[first_idx], cal[-1]), market=market)
        bt.run()
        full = [[str(pd.Timestamp(d).date()), v] for d, v in bt.equity_curve]
    _save("dagilim.json", {"rows": rows, "parite": parite, "full_curve": full})
    if ortusme < 90.0 or izleme > 0.3:
        sys.exit(f"YAPISAL KAPI: örtüşme %{ortusme:.1f} (<90?) veya izleme "
                 f"%{izleme:.3f} (>0.3?) → dağılım YAYINLANMAZ; kod hatası şüphesi")


def golge():
    """07-05 yedeğinden ESKİ-BAZ motorla (denge/A200 yok) 07-06→08-14 replay.
    Canlı dosyalara sıfır dokunuş: yedek OUT altına kopyalanır."""
    import shutil
    import qulla_paper as qp
    import swing2_backtest as s2
    os.makedirs(OUT, exist_ok=True)
    work = os.path.join(OUT, "shadow_ledger.json")
    shutil.copy2(BACKUP_PATH, work)
    led = json.load(open(work))
    on = {"last_date": led["last_date"], "son_eq": led["equity_curve"][-1][1],
          "n_pos": len(led["positions"]), "n_trades": len(led["trades"])}
    print("ön-kontrol:", on, flush=True)
    assert led["last_date"] == "2026-07-02", f"beklenen 2026-07-02, {led['last_date']} bulundu"
    assert 9000 < on["son_eq"] < 12000, "yedek equity makul aralık dışında"
    market = load_market_ro()
    bt = s2.Swing2Backtester(_mk_cfg(START, SON), market=market)   # ESKİ BAZ motor
    bt.cash = led["cash"]
    bt.positions = {d["symbol"]: qp._d_to_pos(d) for d in led["positions"]}
    bt.trades = [qp._d_to_trade(t) for t in led["trades"]]
    bt.equity_curve = [(pd.Timestamp(d), v) for d, v in led["equity_curve"]]
    qp._fix_split_scale(bt)                   # split koruması aynen
    cal = list(pd.DatetimeIndex(sorted(market["spy"].index)))
    last_done = pd.Timestamp(led["last_date"])
    for d in [d for d in cal if last_done < d <= pd.Timestamp(SON)]:
        bt._step(d)
    curve = [[str(pd.Timestamp(d).date()), v] for d, v in bt.equity_curve]
    canli = json.load(open(LEDGER_PATH))["equity_curve"][-1][1]
    _save("golge.json", {"on_kontrol": on, "curve": curve,
                         "final": curve[-1][1], "canli_final": canli})
    print(f"gölge final ${curve[-1][1]:.2f} vs canlı ${canli:.2f} · son gün {curve[-1][0]}")


def shares_on(pos_shares, exits, day):
    """day günü sonunda tutulan adet = bugünkü adet + o günden SONRA çıkan bacakların adedi."""
    return pos_shares + sum(e["shares"] for e in exits if str(e["exit_date"])[:10] > str(day)[:10])


def temmuz():
    import qulla_paper as qp
    led = json.load(open(LEDGER_PATH))
    ec = {d: v for d, v in led["equity_curve"]}
    d0, d1 = "2026-06-30", "2026-07-31"
    toplam = ec[d1] - ec[d0]
    frames = qp._load_store()["frames"]

    def close(sym, day):
        return float(frames[sym]["Close"].asof(pd.Timestamp(day)))

    ALTI = ["ENPH", "GLW", "WDC", "INTC", "LRCX", "TER"]
    pos = {p["symbol"]: p for p in led["positions"]}
    katki = {}
    for sym in ALTI:
        p = pos[sym]
        exits = [t for t in led["trades"] if t["symbol"] == sym
                 and t["entry_date"] == p["entry_date"]]
        sh = shares_on(p["shares"], exits, d0)      # Temmuz başında tutulan adet
        mtm = sh * (close(sym, d1) - close(sym, d0))
        real = sum(t["pnl"] for t in exits if d0 < str(t["exit_date"])[:10] <= d1)
        katki[sym] = round(mtm + real, 2)
    spy_pct = roi(close("SPY", d0), close("SPY", d1))
    alti_top = sum(katki.values())
    _save("temmuz.json", {"toplam": round(toplam, 2), "spy_pct": spy_pct,
                          "alti_kirmizi": katki, "alti_toplam": round(alti_top, 2),
                          "kalan": round(toplam - alti_top, 2)})
    print(f"Temmuz Δ ${toplam:+.0f} · SPY %{spy_pct:+.1f} · "
          f"6-kırmızı ${alti_top:+.0f} · kalan ${toplam - alti_top:+.0f}")
    print("  kırılım:", {k: round(v) for k, v in sorted(katki.items(), key=lambda x: x[1])})


def karne():
    import qulla_paper as qp
    dg, gl, tm = _load("dagilim.json"), _load("golge.json"), _load("temmuz.json")
    led = json.load(open(LEDGER_PATH))
    ec = led["equity_curve"]
    pr = dg["parite"]
    rows = dg["rows"]
    rois = [r["roi"] for r in rows]
    alphas = [r["alpha"] for r in rows]
    dds = [r["maxdd"] for r in rows]
    canli_spy = next(r["spy"] for r in rows if r["start"] == START)

    # Çift yerleştirme (drift bulgusu): defter=gerçek canlı sonuç, replay=aynı-motor bugünkü veri
    roi_defter, roi_replay = pr["defter_roi"], pr["kosu_roi"]
    al_defter = round(roi_defter - canli_spy, 2)
    al_replay = round(roi_replay - canli_spy, 2)
    canli_dd = max_drawdown([v for _, v in ec])
    p_roi_d, p_roi_r = pct_rank(rois, roi_defter), pct_rank(rois, roi_replay)
    p_al_d, p_al_r = pct_rank(alphas, al_defter), pct_rank(alphas, al_replay)
    dd_derin = round(pct_rank(dds, canli_dd), 1)          # maxdd ≤ canlı = daha derin pay
    neg_alpha = round(100 - pct_rank(alphas, 0.0), 1)     # alpha > 0 payının tersi
    neg_alpha = round(100 - neg_alpha, 1)                 # = alpha ≤ 0 payı

    # Kayan-dilim yan notu (sürekli-yatırım versiyonu)
    fc = [v for _, v in dg["full_curve"]]
    roll = [roi(fc[i], fc[i + NWIN - 1]) for i in range(len(fc) - NWIN + 1)]
    p_roll_d = pct_rank(roll, roi_defter)

    # Forward kesit: taban = FWD öncesi son kilitli gün (07-02), uç = SON
    fwd_taban_d, fwd_taban_v = [(d, v) for d, v in ec if d < FWD][-1]
    fwd_roi = roi(fwd_taban_v, ec[-1][1])
    spy = qp._load_store()["frames"]["SPY"]["Close"]
    fwd_spy = roi(float(spy.asof(pd.Timestamp(fwd_taban_d))),
                  float(spy.asof(pd.Timestamp(SON))))

    karar = ("NORMAL VARYANS — değişiklik önerilmez"
             if min(p_roi_d, p_roi_r) > 10.0
             else "YAPISAL ŞÜPHE — derinleşme gerek (ayrı karar)")
    txt = f"""🔎 BEKLENTİ KARNESİ ({START} → {SON} · {NWIN} işlem günü · {len(rows)} taze-başlangıç koşusu)

ROI    : defter %{roi_defter:+.2f} → P{p_roi_d:.0f} · aynı-motor replay %{roi_replay:+.2f} → P{p_roi_r:.0f}
         (drift {pr['drift']:+.2f}p = veri revizyonu bandı; örtüşme %{pr['giris_ortusme_pct']}, izleme %{pr['fwd_oncesi_izleme_pct']})
Alpha  : defter {al_defter:+.2f}pp → P{p_al_d:.0f} · replay {al_replay:+.2f}pp → P{p_al_r:.0f}
         (koşuların %{neg_alpha:.0f}'ında alpha ≤ 0 — kısa pencerede SPY'a yenilmek olağan mı, sayı bu)
MaxDD  : canlı %{canli_dd:.1f} → koşuların %{dd_derin:.0f}'ında DD bundan derin
Kayan-dilim yan notu: defter ROI sürekli-yatırım dağılımında P{p_roll_d:.0f}
Forward ({fwd_taban_d} → {SON}): sistem %{fwd_roi:+.1f} vs SPY %{fwd_spy:+.1f}  ⇐ Aday-3 seçimi sonrası saf test
Gölge  : eski yöntem devam etseydi ${gl['final']:.0f} — canlı ${gl['canli_final']:.0f} (fark ${gl['canli_final']-gl['final']:+.0f} Aday 3 lehine)
Temmuz : Δ${tm['toplam']:+.0f} · SPY %{tm['spy_pct']:+.1f} (düz!) · 6-kırmızı ${tm['alti_toplam']:+.0f} · kalan defter ${tm['kalan']:+.0f}

Not: pencereler örtüşür → yüzdelikler betimseldir (iid güven aralığı değil); 5y tarih Aday 3
seçim verisini içerir (forward satırı bu yüzden ayrı okunur).
KARAR (P10 kuralı, iki yerleştirmenin KÖTÜSÜyle): {karar}"""
    print(txt)
    _save("karne.json", {"p_roi_defter": p_roi_d, "p_roi_replay": p_roi_r,
                         "p_alpha_defter": p_al_d, "p_alpha_replay": p_al_r,
                         "dd_derin_pay": dd_derin, "p_roll_defter": p_roll_d,
                         "neg_alpha_pay": neg_alpha, "fwd_roi": fwd_roi,
                         "fwd_spy": fwd_spy, "karar": karar})
    with open(os.path.join(OUT, "karne.txt"), "w") as fh:
        fh.write(txt + "\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "--karne"
    if cmd == "--dagilim":
        dagilim(smoke="--smoke" in sys.argv)
    else:
        {"--golge": golge, "--temmuz": temmuz, "--karne": karne}[cmd]()

"""pit_results.json → okunabilir özet + karar tablosu."""
import json, sys
sys.path.insert(0, "/home/gokhan")

J = "/home/gokhan/swing2_out/pit_results.json"


def line(w=94): print("-" * w)


def main(path=J):
    r = json.load(open(path))
    m = r["meta"]
    print("\n" + "=" * 94)
    print("POINT-IN-TIME EVREN — SURVIVORSHIP BIAS ÖLÇÜMÜ")
    print("=" * 94)
    print(f"havuz: {m['pool_raw']} indirildi · {m['pool_used']} kullanıldı "
          f"(glitch süzgeci {m['glitch_dropped']} attı) · yaşayan {m['alive']} · ölü {m['dead']}")
    print(f"eşikler: fiyat >= ${m['min_price']:.0f} · {m['adv_window']}g ADV >= "
          f"${m['min_dollar_vol']/1e6:.0f}M · geçmiş >= {m['min_history']} bar · "
          f"top-{m['n']} · delist boşluğu {m['delist_gap']} seans")

    arms = r["arms"]
    print("\n" + "=" * 94)
    print(f"{'KOL':18s} {'evren':>7s} {'5y ROI':>8s} {'MaxDD':>8s} {'Calmar':>7s} "
          f"{'PF':>5s} {'işlem':>6s} {'delist':>7s}")
    line()
    for name, a in arms.items():
        w = a["windows"][0]
        info = a.get("info", {})
        print(f"{name:18s} {info.get('union', info.get('pool','?')):>7} "
              f"{w['roi']:>8.1f} {w['mdd']:>8.1f} {w['calmar']:>7.2f} {w['pf']:>5.2f} "
              f"{w['n']:>6d} {w['delist_n']:>7d}")
    line()

    def roi(k, i=0):
        return arms[k]["windows"][i]["roi"] if k in arms else None

    print("\nFARKLAR (5y tam)")
    line()
    pairs = [
        ("veri/takvim etkisi", "BAZ", "BAZ-kontrol",
         "aynı havuz, taze indirme — bu fark ölü etkisi DEĞİL"),
        ("SAF SURVIVORSHIP (gerçekçi)", "BAZ-kontrol", "BAZ+ÖLÜ-auto",
         "← ASIL CEVAP: evren aynı, yalnız ölüler eklendi"),
        ("SAF SURVIVORSHIP (iflas ucu)", "BAZ-kontrol", "BAZ+ÖLÜ-iflas",
         "her delist tam kayıp sayılırsa (kötümser sınır)"),
        ("evren tanımı etkisi", "BAZ", "PIT-SAG",
         "sp500_ndx → $10/$50M dolar-hacmi taraması"),
        ("geniş evrende yanlılık", "PIT-SAG", "PIT-TAM-auto",
         "aynı geniş evren, ölüler eklendi"),
    ]
    for lab, a1, a2, note in pairs:
        r1, r2 = roi(a1), roi(a2)
        if r1 is None or r2 is None:
            continue
        print(f"  {lab:30s} {r1:7.1f}% → {r2:7.1f}%   {r2-r1:+7.1f} puan")
        print(f"  {'':30s} {note}")
    line()

    if "jitter" in r:
        j = r["jitter"]; s = j["summary"]
        print("\nJITTER — yanlılık farkı başlangıç tarihine göre savruluyor mu?")
        line()
        print(f"  {'başlangıç':12s} {'kontrol':>9s} {'+ölü':>9s} {'fark':>9s} {'iflas ucu':>10s}")
        for row in j["rows"]:
            print(f"  {row['start']:12s} {row['kontrol_roi']:>9.1f} {row['olu_roi']:>9.1f} "
                  f"{row['fark']:>+9.1f} {row['fark_iflas']:>+10.1f}")
        print(f"  → ortalama {s['fark_ort']:+.1f}p · aralık "
              f"{s['fark_min']:+.1f}..{s['fark_max']:+.1f}p · 5/5 negatif: "
              f"{'EVET' if s['hepsi_negatif'] else 'HAYIR'}")
        line()

    f = r.get("_forensic", {})
    for arm in ("BAZ+ÖLÜ-auto", "PIT-TAM-auto"):
        if arm not in f:
            continue
        d = f[arm]
        print(f"\nADLİ TIP — {arm}")
        line()
        print(f"  işlem gören ölü sembol: {d['traded_dead_n']} · "
              f"ölülerin net katkısı ${d['dead_pnl']:,.0f} / toplam ${d['total_pnl']:,.0f}")
        if d.get("dead_detail"):
            print(f"  {'sembol':8s} {'P&L $':>10s} {'işlem':>6s} {'en kötü %':>10s}  ilk alım")
            for sym, v in list(d["dead_detail"].items())[:12]:
                print(f"  {sym:8s} {v['pnl']:>10.0f} {v['n']:>6d} {v['worst']:>10.1f}  {v['first']}")
        if d.get("delist_exits"):
            print(f"  delist çıkışları ({len(d['delist_exits'])}):")
            for e in d["delist_exits"][:12]:
                tag = e[4] if len(e) > 4 else "?"
                print(f"     {e[0]}  {e[1]:6s} son ${e[2]:8.2f}  {e[3]:+7.1f}%  [{tag}]")
        if d.get("worst_trades"):
            print("  en kötü 8 işlem (ölü mü?):")
            for t in d["worst_trades"][:8]:
                print(f"     {t['sym']:6s} {t['in']}→{t['out']}  ${t['pnl']:>9,.0f}  "
                      f"{t['pct']:>7.1f}%  {t['tag']:12s} {'ÖLÜ' if t['olu'] else ''}")
        line()

    print("\nTÜM PENCERELER")
    line()
    labels = [w["win"] for w in next(iter(arms.values()))["windows"]]
    print(f"{'KOL':18s}" + "".join(f"{l:>14s}" for l in labels))
    for name, a in arms.items():
        print(f"{name:18s}" + "".join(f"{w['roi']:>13.1f}%" for w in a["windows"]))
    line()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else J)

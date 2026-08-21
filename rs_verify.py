"""RS izleme listesi sadakat kapısı — canlı depo üzerinde eski yol == vektörel yol.

2026-08-21'de rs_universe.build_watchlist vektörleştirildi (185× hızlı). Bu betik
kanıtı ISTEDIGIN ZAMAN yeniden üretir: canlı depodan market kurar, iki uygulamayı
da koşar, GÜN GÜN küme eşitliği arar. Canlı dosyalara DOKUNMAZ (salt okuma).

    python3 rs_verify.py            # canlı depo
    python3 rs_verify.py --store X  # başka bir depo

Çıkış kodu 0 = birebir · 1 = FARK VAR (o hâlde RS_WATCHLIST_SLOW=1 ile geri dön).
"""
import argparse
import os
import pickle
import sys
import time

sys.path.insert(0, "/home/gokhan")
import pandas as pd
import swing2_backtest as s
import qulla_paper as qp
import rs_universe as ru


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=qp.DAILY_STORE)
    a = ap.parse_args()

    if not os.path.exists(a.store):
        print(f"depo yok: {a.store}")
        return 1
    store = pickle.load(open(a.store, "rb"))          # salt okuma
    cfg = qp._cfg()
    asof = pd.Timestamp(store["last_date"])
    print(f"depo {len(store['frames'])} sembol · son gün {store['last_date']} · "
          f"havuz {len(cfg.rs_pool)} · top-{cfg.rs_n}", flush=True)

    market = s.build_market_from_frames(store["frames"], cfg, today=asof)
    pool = cfg.rs_pool or cfg.universe
    data = {x: market["data"][x] for x in pool if x in market["data"]}
    cal = market["calendar"]
    kw = dict(n=cfg.rs_n, weights=cfg.rs_weights, skip=cfg.rs_skip,
              windows=cfg.rs_windows, dollar_vol_floor=cfg.rs_dollar_vol_floor)

    t = time.time(); slow = ru.build_watchlist_slow(data, cal, **kw); t_slow = time.time() - t
    t = time.time(); fast = ru.build_watchlist_fast(data, cal, **kw); t_fast = time.time() - t

    bad = [d for d in cal if slow.get(d, set()) != fast.get(d, set())]
    print(f"eski yol {t_slow:.1f}s · vektörel {t_fast:.1f}s "
          f"({t_slow/max(t_fast,1e-9):.0f}×) · fark {len(bad)}/{len(cal)} gün")
    if bad:
        for d in bad[:5]:
            x, y = slow.get(d, set()), fast.get(d, set())
            print(f"  {d.date()} yalnız-eski={sorted(x-y)[:6]} yalnız-yeni={sorted(y-x)[:6]}")
        print("❌ FARK VAR — RS_WATCHLIST_SLOW=1 ile eski yola dön")
        return 1
    print(f"✅ {len(cal)}/{len(cal)} gün birebir · son gün ({cal[-1].date()}) "
          f"{len(fast[cal[-1]])} sembol")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Havuz budaması BAZ evreninden isim düşürmüş olabilir — onları eşiksiz tamamla.

keep_floor=$50M budaması, tepe 20g-ADV'si bu eşiğe hiç ulaşmamış sembolleri
atıyor. sp500_ndx isimlerinin ÇOĞU rahat geçer ama küçük S&P üyeleri geçmeyebilir.
BAZ-kontrol kolunun BAZ ile kıyaslanabilmesi için 373 ismin TAMAMI gerekli, bu
yüzden eksik kalanlar eşiksiz (keep_floor=0) ayrıca indirilip birleştirilir."""
import sys, pickle, os
sys.path.insert(0, "/home/gokhan")
import pit_universe as pu, altguard_lab as ag, swing2_backtest as s

START, END = "2020-05-01", "2026-08-20"
d = pickle.load(open(pu.FRAMES_PKL, "rb"))
frames = d["frames"]
pool = list(s.UNIVERSE_PRESETS["sp500_ndx"])
missing = [x for x in pool if x not in frames]
print(f"BAZ havuzu {len(pool)} · mevcut {len(pool)-len(missing)} · eksik {len(missing)}", flush=True)
if missing:
    print(f"eksikler: {missing}", flush=True)
    fr, st = pu.download_pool(missing, START, END, workers=4, batch=200,
                              keep_floor=0.0, rpm=200)     # EŞİKSİZ
    frames.update(fr)
    print(f"tamamlandı: +{len(fr)} · stat={st}", flush=True)
    d["frames"] = frames
    d["base_filled"] = sorted(fr)
    with open(pu.FRAMES_PKL, "wb") as f:
        pickle.dump(d, f, protocol=4)
    print(f"kaydedildi · toplam {len(frames)} sembol", flush=True)
still = [x for x in pool if x not in frames]
print(f"hâlâ eksik: {len(still)} {still[:20]}", flush=True)

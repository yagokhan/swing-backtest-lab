"""Havuzu indir → swing2_cache/pit_frames.pkl

Uyarlanır hız sınırlayıcı (FMP 429 belgesiz limit) + ara kayıt (checkpoint).
Yeniden çalıştırılırsa kaldığı yerden devam eder — 2 saatlik iş tek kesintide
kaybolmasın diye. Eşiği hiç görmemiş semboller RAM'e hiç girmez (anında budanır)."""
import sys, json, pickle, time, os
sys.path.insert(0, "/home/gokhan")
import pit_universe as pu

START, END = "2020-05-01", "2026-08-20"     # backtest başına (2021-05-01) 200+ bar tampon
CKPT = pu.FRAMES_PKL + ".ckpt"
CHUNK = 500

pool = json.load(open(pu.POOL_JSON))["pool"]

frames, done, stat0 = {}, set(), {}
if os.path.exists(CKPT):
    with open(CKPT, "rb") as f:
        st = pickle.load(f)
    frames, done, stat0 = st["frames"], set(st["done"]), st.get("stat", {})
    print(f"↩️  checkpoint: {len(done)} sembol işlenmiş, {len(frames)} tutulmuş", flush=True)

todo = [s for s in pool if s not in done]
print(f"havuz {len(pool)} · kalan {len(todo)} · pencere {START}→{END} · "
      f"eşik ${pu.MIN_DOLLAR_VOL/1e6:.0f}M 20g-ADV", flush=True)

limiter = pu.RateLimiter(rpm=240.0, rpm_min=120.0, rpm_max=290.0)
agg = dict(stat0)
t0 = time.time()
for i in range(0, len(todo), CHUNK):
    part = todo[i:i + CHUNK]
    fr, st = pu.download_pool(part, START, END, workers=6, batch=CHUNK, pause=0.0,
                              keep_floor=pu.MIN_DOLLAR_VOL, verbose=True, limiter=limiter)
    frames.update(fr); done.update(part)
    for k, v in st.items():
        if isinstance(v, (int, float)):
            agg[k] = agg.get(k, 0) + v
    with open(CKPT, "wb") as f:
        pickle.dump({"frames": frames, "done": sorted(done), "stat": agg}, f, protocol=4)
    el = time.time() - t0
    frac = (i + len(part)) / max(1, len(todo))
    print(f"  ▸ TOPLAM {len(done)}/{len(pool)}  tutulan={len(frames)}  "
          f"geçen {el/60:.0f}dk  kalan ~{el/max(frac,1e-9)*(1-frac)/60:.0f}dk", flush=True)

print(f"\nBİTTİ {(time.time()-t0)/60:.0f}dk  tutulan={len(frames)}  stat={agg}", flush=True)
with open(pu.FRAMES_PKL, "wb") as f:
    pickle.dump({"frames": frames, "stat": agg, "start": START, "end": END}, f, protocol=4)
print(f"kaydedildi {pu.FRAMES_PKL}  {os.path.getsize(pu.FRAMES_PKL)/1e6:.0f} MB", flush=True)
if os.path.exists(CKPT):
    os.remove(CKPT)

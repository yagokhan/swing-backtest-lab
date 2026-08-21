"""pit_lab.py — Survivorship bias deneyi: statik evren vs Point-in-Time evren.

ÜÇ KOL (iki etkiyi AYIRMAK için — tek koşuyla ölçülürse birbirine karışır)
--------------------------------------------------------------------------
  BAZ      : bugünkü Qulla-21. Statik sp500_ndx (373 sembol, BUGÜNÜN üyeleri).
             Sadakat çıpası: ag.EXPECTED ile birebir tutmalı.
  PIT-SAG  : Point-in-Time dolar-hacmi evreni, ama YALNIZ bugün hâlâ yaşayanlar.
             BAZ→PIT-SAG farkı = EVREN TANIMI değişiminin etkisi.
  PIT-TAM  : aynı PIT evreni + delist olmuş/satın alınmış ölüler dahil.
             PIT-SAG→PIT-TAM farkı = SAF SURVIVORSHIP BIAS.

Yani "hayatta kalma yanılgısı bize ne kadara mal oluyor?" sorusunun cevabı
üçüncü koldaki farktır; ikinci kol onu evren değişikliğinden temizler.

SABİT TUTULANLAR (karışan değişken olmasın diye)
------------------------------------------------
  • Motor: altguard_lab.GKX (Aday 3) — HİÇ değişmez, alt sınıf bile yok.
    Evren tamamen market["watchlist"] üzerinden enjekte edilir.
  • A200 piyasa freni: her üç kolda da aynı statik breadth.pkl'den okunur.
    Yeni evrenden yeniden hesaplansaydı rejim freni de değişir, sonuç
    yorumlanamaz hâle gelirdi.
  • Takvim, sermaye, slot sayısı, giriş/çıkış kuralları: aynı.

CANLI SİSTEME DOKUNMAZ: defter, state, qulla_paper — hiçbiri okunmaz/yazılmaz.
"""
import argparse
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/gokhan")
os.chdir("/home/gokhan")
import swing2_backtest as s
import altguard_lab as ag
import pit_universe as pu

ETF_PKL = f"{pu.CACHE_DIR}/pit_etfs.pkl"
OUT_JSON = "/home/gokhan/swing2_out/pit_results.json"
START, END = "2020-05-01", "2026-08-20"
ALIVE_TOL = 10          # son bar END'e bu kadar işgününden yakınsa "yaşıyor"

# PENCERE HİZALAMASI — kolların kıyaslanabilir olmasının ön şartı.
# ag.MARKET (sabit cache) 2026-07-01'de bitiyor, taze PIT indirmesi 2026-08-20'de.
# ag.WINS'teki boş bitiş ("") "takvimin sonuna kadar" demek → PIT kollarına 35
# işlem günü fazla verirdi ve fark evrenden mi takvimden mi geldiği anlaşılmazdı.
# Bu yüzden boş bitişler AÇIKÇA ortak son güne sabitlenir.
WIN_END = "2026-07-01"


def aligned_wins(wins):
    return [(lab, st, (en or WIN_END)) for lab, st, en in wins]


# =========================================================================
# DELİST ÇÖZÜMÜ — deneyin geçerliliği buna bağlı
# =========================================================================
# Baz motor, satırı NaN olan pozisyonu atlar (`if pd.isna(low) or pd.isna(high):
# continue`) ve pencere sonunda son geçerli kapanıştan kapatır. Tüm evren
# yaşıyorken bu hiç önemli değildi. Ölüler evrene girince İKİ YÖNDE birden
# bozuyor:
#   • Hayalet slot: SIVB Mart 2023'te ölür, pozisyon 2026'ya kadar slot işgal
#     eder → PIT-TAM'a haksız nakit-sürüklemesi cezası.
#   • Geç çıkış: satın alma da iflas da "son fiyattan sat" gibi işlenir.
#
# Doğru model: hisse işlem görmeyi bırakınca ÇIKMIŞSINDIR. Kural nedenseldir —
# yalnız geçmişe bakar: K seans üst üste bar yoksa son geçerli kapanıştan çık.
# "Gelecekte bar var mı" diye bakmak look-ahead olurdu, kullanılmıyor.
#
# HAIRCUT = iflas/satın alma belirsizliğinin duyarlılık aralığı:
#   0.00 → son fiyattan nakde çık (satın alma senaryosu, İYİMSER uç)
#   1.00 → hissedar sıfırlanır (iflas senaryosu, KÖTÜMSER uç)
# Gerçek cevap ikisinin arasındadır; ikisini de koşup aralık raporlanır.
# HAIRCUT_MODE="auto": iflası satın almadan fiyat davranışıyla ayırır.
#   • Satın alma PRİMLE biter → son fiyat 252g zirvesine yakın (BKI −%2, ATVI −%1).
#   • İflas ÇÖKÜŞLE biter → son fiyat zirveden çok aşağıda VE son günlerde sert
#     düşüş var (SIVB: zirveden −%77, son 5 günde −%60; FRC: −%98).
# Ölçüt yalnız GEÇMİŞ barlara bakar. FMP'de güvenilir M&A geçmişi yok
# (mergers-acquisitions yalnız son 100 kayıt, arama 402), bu yüzden veri yerine
# ölçülebilir bir imza kullanılıyor. Üç kol da raporlanır: %0 / auto / %100.
DD_WIPE = -0.60         # 252g zirvesinden düşüş bunun altındaysa iflas adayı
CRASH5_WIPE = -0.30     # VE son 5 günde bu kadar düştüyse → hissedar sıfırlanır


class PITBacktester(ag.GKX):
    DELIST_GAP = 5        # kaç seans bar yoksa "işlem görmüyor" sayılır
    HAIRCUT = 0.0         # 0..1, HAIRCUT_MODE="sabit" iken
    HAIRCUT_MODE = "sabit"    # "sabit" | "auto"

    def _haircut_for(self, closes):
        """Bu delist bir nakit çıkış mı yoksa sıfırlanma mı? (yalnız geçmiş barlar)"""
        if self.HAIRCUT_MODE != "auto":
            return self.HAIRCUT
        if len(closes) < 10:
            return 0.0
        last = float(closes.iloc[-1])
        peak = float(closes.iloc[-252:].max())
        dd = last / peak - 1.0 if peak > 0 else 0.0
        c5 = last / float(closes.iloc[-6]) - 1.0 if float(closes.iloc[-6]) > 0 else 0.0
        return 1.0 if (dd <= DD_WIPE and c5 <= CRASH5_WIPE) else 0.0

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._nan_run = {}
        self.delist_log = []          # (tarih, sembol, son_fiyat, pnl_pct)

    def _manage(self, date):
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            if date == pos.entry_date:
                continue
            row = self.data[sym].loc[date]
            if pd.isna(row["Close"]):
                k = self._nan_run.get(sym, 0) + 1
                self._nan_run[sym] = k
                if k >= self.DELIST_GAP:
                    closes = self.data[sym]["Close"].loc[:date].dropna()
                    if len(closes):
                        hc = self._haircut_for(closes)
                        px = float(closes.iloc[-1]) * (1.0 - hc)
                        self.delist_log.append(
                            (str(date.date()), sym, round(float(closes.iloc[-1]), 2),
                             round((px / pos.entry - 1) * 100, 1),
                             "sıfırlandı" if hc >= 0.999 else "nakit"))
                        # Bölünmüş çıkışta bacaklar tek tek kapanır; _close_leg pozisyonu
                        # SİLMEZ. Ardından _close çağırmak sıfır-hisseli sahte bir işlem
                        # kaydı (ve komisyon kadar nakit sızıntısı) üretirdi — bu yüzden
                        # bacaklı ve bacaksız yollar ayrı.
                        legs = getattr(pos, "legs", None)
                        if legs:
                            for leg in legs:
                                if leg["shares"] > 0:
                                    self._close_leg(sym, pos, leg, date, px, "DELIST", slip=0.0)
                            self.positions.pop(sym, None)
                        else:
                            self._close(sym, date, px, "DELIST", slip=0.0)
            else:
                self._nan_run[sym] = 0
        super()._manage(date)


# ------------------------------------------------------------------ altyapı
def load_etfs(force=False):
    """SPY + sektör ETF'leri (havuzdan dışlandılar; motor bunları ayrıca ister)."""
    if os.path.exists(ETF_PKL) and not force:
        return pickle.load(open(ETF_PKL, "rb"))
    syms = ["SPY"] + sorted(set(s.SECTOR_MAP.values()))
    key = pu._key()
    lim = pu.RateLimiter(rpm=90)
    out = {}
    for sym in syms:
        tag, df = pu._download_one(sym, key, START, END, keep_floor=0.0, limiter=lim)
        if df is None:
            raise pu.FMPError(f"{sym} indirilemedi ({tag}) — ETF'siz devam edilemez")
        out[sym] = df
    pickle.dump(out, open(ETF_PKL, "wb"), protocol=4)
    return out


def load_frames(allow_ckpt=True):
    """Tamamlanmış havuz; yoksa (indirme sürüyorsa) checkpoint — prova koşuları için."""
    if os.path.exists(pu.FRAMES_PKL):
        d = pickle.load(open(pu.FRAMES_PKL, "rb"))
        return d["frames"], d.get("stat", {})
    ck = pu.FRAMES_PKL + ".ckpt"
    if allow_ckpt and os.path.exists(ck):
        d = pickle.load(open(ck, "rb"))
        print(f"⚠️ TAMAMLANMAMIŞ checkpoint kullanılıyor ({len(d['done'])} sembol işlenmiş) "
              f"— sonuçlar NİHAİ DEĞİL", flush=True)
        return d["frames"], d.get("stat", {})
    raise SystemExit(f"{pu.FRAMES_PKL} yok — önce pit_download.py")


def classify_alive(frames, end=END, tol=ALIVE_TOL):
    """Son barı END'e yakın olan = yaşıyor; erken biten = delist/satın alınmış."""
    cut = pd.Timestamp(end) - pd.tseries.offsets.BDay(tol)
    alive, dead = set(), set()
    for sym, df in frames.items():
        (alive if df.index[-1] >= cut else dead).add(sym)
    return alive, dead


def peak_adv_map(frames, window=pu.ADV_WINDOW):
    """{sym: serinin gördüğü en yüksek N-günlük ortalama dolar hacmi}"""
    out = {}
    for s, df in frames.items():
        out[s] = pu._peak_adv(df["Close"].to_numpy(dtype=float),
                              df["Volume"].to_numpy(dtype=float), window=window)
    return out


def build_baz_plus_dead(frames, etfs, cfg, dead, pct=25, verbose=True):
    """BAZ evreni + O DÖNEM ENDEKSTE OLUP ÖLENLER — evren tanımı DEĞİŞMEDEN saf yanlılık.

    PIT-SAG/PIT-TAM kolları evreni 373'ten binlere çıkarıyor; bu tek başına
    sonucu domine ediyor ve survivorship etkisini gömüyor. Bu kol ise mevcut
    havuza DOKUNMAZ, yalnız 2021-2026 arasında ölmüş BÜYÜK isimleri ekler —
    yani "Qulla-21 gerçekten koştuğu evrende ne kadar şişmişti?" sorusu.

    "Büyük" ölçütü verisel: mevcut 373'lük havuzun tepe-ADV dağılımının pct.
    yüzdeliği. Böylece eklenen ölüler, havuzun zaten taşıdığı likidite sınıfında
    olur — küçük spekülatif çöp eklenmez.

    İzleme listesi BAZ ile AYNI yoldan kurulur (legacy_dv_gate), üstüne yalnız
    "o gün işlem görmüş" şartı eklenir; bu şart olmadan ölü bir isim öldükten
    sonraki ~20 gün boyunca kısmi ortalamayla kapıdan geçebilirdi."""
    base_pool = [s for s in cfg.rs_pool if s in frames]
    adv = peak_adv_map(frames)
    ref = [adv[s] for s in base_pool if adv.get(s, 0) > 0]
    thr = float(np.percentile(ref, pct)) if ref else 0.0
    big_dead = sorted(s for s in dead if adv.get(s, 0.0) >= thr)
    cover = len(base_pool) / max(1, len(cfg.rs_pool))
    if cover < 0.95:
        print(f"  ⚠️ BAZ havuzu kapsamı %{100*cover:.0f} — indirme tamamlanmamış olabilir",
              flush=True)
    pool = sorted(set(base_pool) | set(big_dead))

    if verbose:
        print(f"  BAZ havuzu {len(base_pool)}/{len(cfg.rs_pool)} kapsandı · "
              f"eşik = P{pct} tepe-ADV ${thr/1e6:.0f}M · eklenen ölü {len(big_dead)}",
              flush=True)
        print(f"  eklenen ölülerden bazıları: {big_dead[:14]}", flush=True)

    use = {k: frames[k] for k in pool}
    cal = pd.DatetimeIndex(etfs["SPY"].index)
    close, vol = pu.to_panel(use, cal)
    gate = pu.legacy_dv_gate(close, vol, cfg.rs_dollar_vol_floor)
    traded = (close.notna() & vol.notna()).shift(1).astype(object).where(
        lambda x: x.notna(), False).astype(bool)
    rs = pu.rs_matrix(close, weights=cfg.rs_weights, skip=cfg.rs_skip, windows=cfg.rs_windows)
    wl = pu.build_watchlist_fast(rs, gate & traded, n=cfg.rs_n)

    union = sorted(set().union(*wl.values())) if wl else []
    cfg2 = ag.copy.deepcopy(cfg)
    cfg2.universe = tuple(union); cfg2.rs_pool = tuple(union)
    market = s.build_market_from_frames({**{k: use[k] for k in union}, **etfs}, cfg2, today=END)
    market["watchlist"] = {d: wl.get(d, set()) for d in market["calendar"]}
    return market, cfg2, {"pool": len(pool), "union": len(union),
                          "base_covered": len(base_pool), "added_dead": len(big_dead),
                          "adv_threshold_musd": round(thr / 1e6, 1),
                          "dead_names": big_dead[:60]}


# ------------------------------------------------------- PIT evren + market
def build_pit_market(frames, etfs, cfg, only=None, n=50, verbose=True):
    """PIT maskesi + RS ile günlük izleme listesi üret, sonra YALNIZ listeye hiç
    girmiş sembollerin göstergelerini hesapla.

    Sadece izleme listesine girenlerin işlenmesi bir kısayol DEĞİL: motor
    _in_watchlist kapısı yüzünden zaten yalnız onlara pozisyon açabilir; listeye
    hiç girmemiş sembol backtest'i hiçbir şekilde etkileyemez. 31 bin sembolün
    göstergesini hesaplamak yerine ~10³ sembol → dakikalar yerine saniyeler."""
    use = frames if only is None else {k: v for k, v in frames.items() if k in only}
    spy = etfs["SPY"]
    cal = pd.DatetimeIndex(spy.index)

    t0 = time.time()
    close, vol = pu.to_panel(use, cal)
    mask = pu.pit_mask(close, vol)                      # tamamı shift(1) → causal
    rs = pu.rs_matrix(close, weights=cfg.rs_weights, skip=cfg.rs_skip, windows=cfg.rs_windows)
    wl = pu.build_watchlist_fast(rs, mask, n=n)
    t_wl = time.time() - t0

    union = sorted(set().union(*wl.values())) if wl else []
    if verbose:
        elig = int(mask.sum(axis=1).mean())
        print(f"  PIT evreni: havuz {len(use)} · ort. günlük uygun {elig} · "
              f"top-{n} birleşimi {len(union)} sembol · {t_wl:.0f}s", flush=True)

    cfg2 = ag.copy.deepcopy(cfg)
    cfg2.universe = tuple(union)
    cfg2.rs_pool = tuple(union)
    frames_all = {**{k: use[k] for k in union}, **etfs}
    market = s.build_market_from_frames(frames_all, cfg2, today=END)
    market["watchlist"] = {d: wl.get(d, set()) for d in market["calendar"]}
    return market, cfg2, {"pool": len(use), "union": len(union),
                          "elig_avg": int(mask.sum(axis=1).mean())}


# ------------------------------------------------------------------ koşular
def run_window(market, cfg, label, start, end, haircut=0.0, mode="sabit"):
    c = ag.copy.deepcopy(cfg)
    c.start_date, c.end_date = start, (end or None)
    bt = PITBacktester(c, market=market)
    bt.HAIRCUT = float(haircut); bt.HAIRCUT_MODE = mode
    bt.run()
    m = bt.metrics()
    dd = float(m["max_dd"])
    return {"win": label, "roi": round(float(m["roi"]), 1), "n": int(m["trades"]),
            "mdd": round(dd, 1), "calmar": round(float(m["roi"]) / abs(dd), 2) if dd else 0.0,
            "pf": round(float(m["profit_factor"]), 2),
            "win_rate": round(float(m["win_rate"]), 1),
            "alpha": round(float(m["alpha"]), 1),
            "delist_n": len(bt.delist_log)}, bt


def arm_baz():
    ag.load_data()
    return ag.MARKET, ag.base_cfg()


# =========================================================================
# JITTER — kanon standardı: tek başlangıç tarihine dayanan sonuç kabul edilmez
# =========================================================================
# [[swing2-tahsis-deney]] ve [[swing2-yogunlasma-deneyi]] derslerinin ikisi de
# aynı: manşet rakam bir-iki bitişik başlangıçta var olup jitter'da buharlaşabilir.
# Burada ölçtüğümüz bir "aday" değil bir BÜYÜKLÜK, ama aynı disiplin geçerli —
# yanlılık farkı başlangıç tarihine göre savruluyorsa büyüklük raporlanamaz.
JITTER_STARTS = ["2021-05-01", "2021-05-11", "2021-05-21", "2021-06-01", "2021-06-11"]


def run_jitter(frames, etfs, dead, results, verbose=True):
    """BAZ-kontrol vs BAZ+ÖLÜ farkını 5 farklı başlangıçta ölç."""
    print(f"\n=== JITTER ({len(JITTER_STARTS)} başlangıç) ===", flush=True)
    mk_c, cfg_c, _ = build_baz_plus_dead(frames, etfs, ag.base_cfg(), set(), verbose=False)
    mk_d, cfg_d, _ = build_baz_plus_dead(frames, etfs, ag.base_cfg(), dead, verbose=False)
    rows = []
    for st in JITTER_STARTS:
        rc, _ = run_window(mk_c, cfg_c, "jit", st, WIN_END, haircut=0.0)
        rd, _ = run_window(mk_d, cfg_d, "jit", st, WIN_END, haircut=0.0, mode="auto")
        ri, _ = run_window(mk_d, cfg_d, "jit", st, WIN_END, haircut=1.0)
        row = {"start": st, "kontrol_roi": rc["roi"], "olu_roi": rd["roi"],
               "iflas_roi": ri["roi"], "fark": round(rd["roi"] - rc["roi"], 1),
               "fark_iflas": round(ri["roi"] - rc["roi"], 1),
               "kontrol_calmar": rc["calmar"], "olu_calmar": rd["calmar"]}
        rows.append(row)
        if verbose:
            print(f"  {st}  kontrol {rc['roi']:7.1f}%  +ölü {rd['roi']:7.1f}%  "
                  f"fark {row['fark']:+7.1f}p   (iflas ucu {row['fark_iflas']:+7.1f}p)",
                  flush=True)
    f = [r["fark"] for r in rows]
    fi = [r["fark_iflas"] for r in rows]
    summary = {"fark_min": min(f), "fark_max": max(f),
               "fark_ort": round(sum(f) / len(f), 1),
               "fark_iflas_ort": round(sum(fi) / len(fi), 1),
               "hepsi_negatif": all(x < 0 for x in f)}
    print(f"  → yanlılık {summary['fark_ort']:+.1f}p ortalama "
          f"(aralık {summary['fark_min']:+.1f}..{summary['fark_max']:+.1f}p) · "
          f"5/5 negatif: {summary['hepsi_negatif']}", flush=True)
    results["jitter"] = {"rows": rows, "summary": summary}
    del mk_c, mk_d
    import gc; gc.collect()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--glitch-max", type=int, default=1,
                    help="bu kadar gidiş-dönüş sıçramasını AŞAN sembol atılır (-1 = süzgeç kapalı)")
    ap.add_argument("--quick", action="store_true", help="yalnız 5y penceresi")
    ap.add_argument("--jitter", action="store_true", help="+ 5 başlangıçlı jitter")
    a = ap.parse_args()

    ag.load_data()                          # BR (A200) + baz market (çıpa)
    etfs = load_etfs()
    frames_raw, dstat = load_frames()
    print(f"indirilen havuz: {len(frames_raw)} sembol", flush=True)

    if a.glitch_max >= 0:
        frames, dropped, gmap = pu.drop_glitchy(frames_raw, max_roundtrip=a.glitch_max)
    else:
        frames, dropped, gmap = frames_raw, set(), {}
    alive, dead = classify_alive(frames)
    print(f"süzgeç sonrası {len(frames)} · yaşayan {len(alive)} · "
          f"delist/satın alınmış {len(dead)}", flush=True)

    wins = aligned_wins(ag.WINS[:1] if a.quick else ag.WINS)
    print(f"pencereler ortak son güne hizalandı: {WIN_END}", flush=True)
    results = {"meta": {"pool_raw": len(frames_raw), "pool_used": len(frames),
                        "glitch_dropped": len(dropped), "glitch_max": a.glitch_max,
                        "alive": len(alive), "dead": len(dead),
                        "dl_stat": {k: v for k, v in dstat.items() if isinstance(v, (int, float))},
                        "n": a.n, "min_price": pu.MIN_PRICE,
                        "min_dollar_vol": pu.MIN_DOLLAR_VOL,
                        "adv_window": pu.ADV_WINDOW, "min_history": pu.MIN_HISTORY,
                        "delist_gap": PITBacktester.DELIST_GAP}, "arms": {}}

    # Market'ler GRUP GRUP kurulur ve grup bitince serbest bırakılır. İkisini
    # aynı anda tutmak ~3 GB × 2 demek (ölçüldü: 741 hisse = 0,86 GB) — gereksiz
    # risk. PIT-TAM üç haircut kolunda da aynı market'i kullandığı için bir kez
    # kurulup üç kez koşuluyor.
    GROUPS = [
        ("BAZ",       None,   [("BAZ", 0.0, "sabit")]),
        # KONTROL: BAZ+ÖLÜ ile AYNI yoldan (taze indirme, 2020-05-01 takvimi,
        # vektörel izleme listesi) ama ölü EKLENMEDEN. BAZ+ÖLÜ bununla
        # kıyaslanır — doğrudan BAZ ile değil. Aradaki fark yalnız veri
        # kaynağı/takvim farkını gösterir; o farkı ölü etkisine yazmamak için.
        ("BAZ-kontrol", "bazc", [("BAZ-kontrol", 0.0, "sabit")]),
        # ASIL SORU: evren tanımı sabit, yalnız ölüler ekleniyor
        ("BAZ+ÖLÜ",   "bazd", [("BAZ+ÖLÜ-nakit", 0.0, "sabit"),
                               ("BAZ+ÖLÜ-auto",  0.0, "auto"),
                               ("BAZ+ÖLÜ-iflas", 1.0, "sabit")]),
        ("PIT-SAG",   "sag",  [("PIT-SAG", 0.0, "sabit")]),
        ("PIT-TAM",   "tam",  [("PIT-TAM-nakit", 0.0, "sabit"),    # iyimser uç
                               ("PIT-TAM-auto",  0.0, "auto"),     # gerçekçi
                               ("PIT-TAM-iflas", 1.0, "sabit")]),  # kötümser uç
    ]

    ARMS = []
    for gname, kind, arms in GROUPS:
        print(f"\n=== {gname} evreni kuruluyor ===", flush=True)
        if kind is None:
            market, cfg = arm_baz()
            info = {"pool": len(market["data"]), "union": len(market["data"])}
        elif kind == "bazc":
            market, cfg, info = build_baz_plus_dead(frames, etfs, ag.base_cfg(), set())
        elif kind == "bazd":
            market, cfg, info = build_baz_plus_dead(frames, etfs, ag.base_cfg(), dead)
        else:
            market, cfg, info = build_pit_market(
                frames, etfs, ag.base_cfg(), only=(alive if kind == "sag" else None), n=a.n)
        for arm, hc, mode in arms:
            ARMS.append((arm, market, cfg, hc, mode, info))
        _run_group(ARMS[-len(arms):], wins, dead, results)
        ARMS = ARMS[:-len(arms)]
        if kind is not None:
            del market
            import gc; gc.collect()

    if a.jitter:
        run_jitter(frames, etfs, dead, results)

    json.dump(results, open(OUT_JSON, "w"), indent=1, default=float)
    print(f"\nkaydedildi {OUT_JSON}", flush=True)


def _run_group(arms, wins, dead, results):
    for arm, market, cfg, hc, mode, info in arms:
        print(f"\n--- {arm} (haircut {'auto' if mode=='auto' else '%%%.0f' % (hc*100)}) ---", flush=True)
        rows, dlog = [], []
        for label, st, en in wins:
            r, bt = run_window(market, cfg, label, st, en, haircut=hc, mode=mode)
            rows.append(r)
            if label == wins[0][0]:
                dlog = bt.delist_log
                traded_dead = sorted({t.symbol for t in bt.trades} & set(dead))
                per_dead = {}
                for t in bt.trades:
                    if t.symbol in dead:
                        e = per_dead.setdefault(t.symbol, {"pnl": 0.0, "n": 0, "worst": 0.0,
                                                           "first": str(t.entry_date.date()),
                                                           "last": str(t.exit_date.date())})
                        e["pnl"] += float(t.pnl); e["n"] += 1
                        e["worst"] = min(e["worst"], float(t.pnl_pct))
                        e["last"] = str(t.exit_date.date())
                for v in per_dead.values():
                    v["pnl"] = round(v["pnl"], 1); v["worst"] = round(v["worst"], 1)
                worst_trades = sorted(bt.trades, key=lambda t: t.pnl)[:15]
                results.setdefault("_forensic", {})[arm] = {
                    "delist_exits": dlog,
                    "traded_dead_n": len(traded_dead),
                    "dead_detail": dict(sorted(per_dead.items(), key=lambda kv: kv[1]["pnl"])[:25]),
                    "dead_pnl": round(sum(t.pnl for t in bt.trades if t.symbol in dead), 1),
                    "total_pnl": round(sum(t.pnl for t in bt.trades), 1),
                    "worst_trades": [{"sym": t.symbol, "in": str(t.entry_date.date()),
                                      "out": str(t.exit_date.date()), "pnl": round(float(t.pnl), 0),
                                      "pct": round(float(t.pnl_pct), 1), "tag": str(t.outcome),
                                      "olu": t.symbol in dead} for t in worst_trades]}
            print(f"  {label:12s} ROI {r['roi']:7.1f}%  n={r['n']:4d}  MaxDD {r['mdd']:6.1f}%  "
                  f"Calmar {r['calmar']:5.2f}  PF {r['pf']:4.2f}  delist={r['delist_n']:3d}",
                  flush=True)
        results["arms"][arm] = {"info": info, "haircut": hc, "mode": mode, "windows": rows}

        if arm == "BAZ":
            exp = ag.EXPECTED[:len(rows)]
            ok = all(abs(r["roi"] - e[0]) < 0.05 and r["n"] == e[1] for r, e in zip(rows, exp))
            print(f"  sadakat çıpası: {'✅ BAZ == EXPECTED' if ok else '❌ ÇIPA TUTMADI'}", flush=True)
            results["arms"][arm]["fidelity"] = bool(ok)
            if not ok:
                raise SystemExit("BAZ çıpası tutmadı — deney geçersiz, durduruldu.")


if __name__ == "__main__":
    main()

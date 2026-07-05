#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""👑 Qulla-21 canlı paper-track — GERÇEK DEFTER (kalıcı durum, geçmiş kilitli).

Test edilen yöntemin BİREBİR aynısı: RS top-50 sistematik evren (sp500+ndx) +
qswing 63g kırılım girişi + split çıkış (%60 +2R hedef / %40 21-EMA runner — 60/40, 2026-07-02).
$10k · %7.5/slot (combo) · 20-slot · bileşik.

⭐ ADAY 3 "EN DENGELİ" (2026-07-05, kullanıcı kararı): bazdan İKİ fark —
  1) SIRALAMA: kalabalık günde denge karışımı = puan/100 + ATR%/10 (blend10)
  2) FREN: SPY>SMA200'e EK A200≥%50 (havuzun en az yarısı kendi SMA200 üstünde, VE bağlacı)
Defter kullanıcı isteğiyle AYNI çapadan (START) Aday-3 konfigüle yeniden kuruldu
(bootstrap); eski baz defter .bak.20260705'te. Batarya kanıtı: /adaylar ve /lab §12-12b.

DEFTER MİMARİSİ (önceki "durumsuz replay" değiştirildi):
  • İlk çalıştırma → defter yoksa backtest ile SABİT çapa START → bugün BİR KEZ doldurulur
    (bootstrap), sonra DONDURULUR.
  • Sonraki her gün → defterdeki nakit/pozisyon/işlemler motora yüklenir, YALNIZ yeni günler
    işlenir (bt._step). Geçmiş bir daha hesaplanmaz → FMP veri revizyonu (split/temettü
    geri-ayar) artık geçmişi DEĞİŞTİREMEZ; açık pozisyon GERÇEKTEN satılana kadar düşmez.
  • Eşdeğerlik kanıtı: veri sabitken tek-bootstrap(T) == bootstrap(t)+artımlı(T) (deterministik
    motor; bkz. scratch test). Defter ~/.swing_paper_qulla_ledger.json (tek doğruluk kaynağı);
    ~/.swing_paper_qulla.json sadece dashboard/komut-botu önbelleği (write_state).
  • Defteri YALNIZ gerçek gönderim ilerletir: run_qulla hesaplar, commit_ledger(r) diske yazar
    (kuru test/dashboard yenilemesi defteri ilerletmez).
  • Piyasa verisi ARTIMLI depoda (load_market_incremental → ~/.swing_daily_store.pkl): 5y her gün
    indirilmez; yalnız son günden bu yana yeni barlar çekilip eklenir, göstergeler depodan taze hesaplanır
    (split → o sembol tam yenilenir; haftalık tam yenileme güvenlik ağı).

CLI:  python3 qulla_paper.py [--asof YYYY-MM-DD]   (salt-okunur simülasyon; commit etmez)
"""
import sys, os, json, html
import pandas as pd
import swing2_backtest as s

# SABİT çapa: paper-trade'in "başladığı" gün. 2026-06-26'da kullanıcı isteğiyle TAM 30 gün
# öncesine (2026-05-27) çekildi ve defter SIFIRDAN yeni (ledger) yöntemiyle kuruldu.
# Defter buradan BİRİKİR; bir kez işlenen gün kilitlenir (geçmiş bir daha değişmez).
START = "2026-05-27"
POOL = s.UNIVERSE_PRESETS["sp500_ndx"]      # ~373 havuz → günlük RS top-50
INITIAL = 10_000.0

# Dashboard/komut-botu önbelleği (paper_trader uyumlu durum snapshot'ı)
PAPER_QULLA = os.path.expanduser("~/.swing_paper_qulla.json")
# GERÇEK DEFTER (tek doğruluk kaynağı): bir kez işlenen gün kilitlenir, geçmiş bir daha
# değişmez. İlk çalıştırmada backtest ile START→bugün doldurulur (bootstrap), sonra ARTIMLI
# ilerler: her gün yalnız yeni günler işlenir, açık pozisyonlar gerçekten satılana kadar düşmez.
PAPER_QULLA_LEDGER = os.path.expanduser("~/.swing_paper_qulla_ledger.json")
# ARTIMLI HAM VERİ DEPOSU: 5y'yi HER GÜN indirme. Ham OHLCV diskte birikir; her tarama yalnız
# son günden bu yana YENİ barları çeker, ekler, kaydeder; göstergeleri depodan taze hesaplar.
# Split → o sembol tam yenilenir; haftada bir tam yenileme (sessiz yeniden-ayar güvenlik ağı).
DAILY_STORE = os.path.expanduser("~/.swing_daily_store.pkl")


def _cfg(asof=None):
    c = s.Config()
    c.entry_mode = "qswing_breakout"; c.qswing_breakout_lb = 63
    c.exit_mode = "split"                  # %60 +2R hedef / %40 21-EMA runner
    c.split_a = "target"; c.split_a_param = 2.0
    c.split_b = "ema21";  c.split_b_param = 0.0
    # ⭐ 60/40 (2026-07-02): +2R bacağına %60 — lab 5/5 walk-forward penceresinde bazı geçti
    # (/lab bölüm 2b/4). Defter kullanıcı isteğiyle GEÇMİŞE DÖNÜK yeniden kuruldu (bootstrap,
    # START'tan itibaren combo+60/40 tek konfig); eski 50/50 defter .bak.20260702-0954'te.
    c.split_ratio = 0.6
    c.initial_capital = INITIAL; c.compounding = True
    # 🔓 COMBO (2026-07-01): cash-drag düzeltmesi — poz %5→%7.5 + runner slotu boşalt.
    # Artımlı defter YALNIZ yeni günleri işler → kilitli geçmiş DEĞİŞMEZ; combo bugünden ileri geçerli.
    c.max_positions = 20; c.max_position_pct = 0.075
    c.free_runner_slots = True
    c.use_earnings = False
    c.price_source = "fmp"; c.period = "5y"; c.per_ticker_download = False
    c.use_rs_universe = True; c.rs_pool = POOL; c.rs_n = 50; c.universe = POOL
    c.liquidate_at_end = False         # canlı snapshot: açık pozisyonları kapatma
    c.start_date = START; c.end_date = asof or ""
    return c


# =========================================================================
# ⭐ ADAY 3 MOTORU — baz motordan iki fark: denge sıralaması + A200 piyasa freni.
# _step gövdesi bataryadaki (combo_battery3 KX) blend yolunun BİREBİR kopyası;
# eşdeğerlik sabit cache'te 5 pencere batarya sonuçlarıyla doğrulanır (canlıya
# alma ön şartı). A200 canlıda statik pkl yerine motor verisinden hesaplanır —
# formül build_infra ile aynı: (Close>SMA200) sembol başına (NaN→False, çünkü
# tüm çerçeveler SPY takvimine hizalı), gün ortalaması ×100.
# =========================================================================
class DengeBacktester(s.Swing2Backtester):
    A200_MIN = 50.0

    def _a200(self, date):
        if not hasattr(self, "_a200_series"):
            uni = set(self.cfg.universe)
            cols = {sym: (df["Close"] > df["SMA200"]).astype("float32")
                    for sym, df in self.data.items() if sym in uni}
            self._a200_series = pd.DataFrame(cols).mean(axis=1) * 100.0
        try:
            v = self._a200_series.get(date)
        except Exception:
            v = None
        return float(v) if v is not None and not pd.isna(v) else None

    def _common(self, date):
        c = super()._common(date)
        if c.get("spy_above_sma200"):
            v = self._a200(date)
            if v is not None:
                c["spy_above_sma200"] = bool(v >= self.A200_MIN)
        return c

    def _rank_key(self, qscore, row):
        a = row.get("ATR_PCT")
        a = float(a) if a is not None and not pd.isna(a) else 0.0
        return qscore / 100.0 + a / 10.0

    def _step(self, date):
        cfg = self.cfg
        self._manage(date)
        common = self._common(date)
        if (common["spy_above_sma200"] and not self._vol_regime_locked(common)
                and self._slot_count() < cfg.max_positions and self.cash >= self._size(date)):
            cands = []
            spy_ret60 = self.spy.loc[date, "RET60"]
            for sym, df in self.data.items():
                if sym in self.positions: continue
                if not self._in_watchlist(sym, date): continue
                row = df.loc[date]
                if (pd.isna(row["Close"]) or pd.isna(row["SMA200"]) or row["Close"] <= row["SMA200"]
                        or row["Close"] <= row["SMA50"] or row["Close"] <= row["SMA20"]
                        or pd.isna(row["SLOPE200"]) or row["SLOPE200"] <= 0): continue
                plan = s.compute_trade_plan(row, cfg)
                dist = (row["Close"] - row["SMA20"]) / row["SMA20"]
                rs = self._qswing_entry_ok(row, spy_ret60)
                if rs is None: continue
                _risk = plan["entry"] - plan["stop"]
                _rec = {"rs": rs,
                        "dist_52h_pct": (row["Close"] / row["HIGH52"] - 1) * 100,
                        "dist_sma20_pct": dist * 100,
                        "risk_pct": (_risk / plan["entry"] * 100) if plan["entry"] else None}
                qscore, _ = s._qswing_priority_score(_rec)
                if cfg.qswing_min_score > 0 and qscore < cfg.qswing_min_score: continue
                cands.append((self._rank_key(qscore, row), -dist, sym, row, plan))
            cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
            for total, _nd, sym, row, plan in cands:
                if self._slot_count() >= cfg.max_positions or self.cash < self._size(date): break
                self._open(sym, date, row, plan, total)
        self.equity_curve.append((date, self._equity(date)))


# =========================================================================
# ARTIMLI HAM VERİ DEPOSU — "kaydet, yeni günleri ekle, hesapla" (5y her gün indirilmez)
# =========================================================================
def _load_store(path=DAILY_STORE):
    import pickle
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as fh:
            return pickle.load(fh)
    except Exception as e:
        print(f"[veri deposu okunamadı, sıfırdan kurulacak] {e}", flush=True)
        return None


def _save_store(store, path=DAILY_STORE):
    import pickle
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump(store, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def _tickers_for(cfg):
    """download_and_align_data ile AYNI sembol kümesi: evren + benchmark + sektör ETF'leri."""
    etfs = sorted({s.SECTOR_MAP[x] for x in cfg.universe if x in s.SECTOR_MAP})
    return list(dict.fromkeys(list(cfg.universe) + [cfg.benchmark] + etfs))


def load_market_incremental(asof=None, full_refresh_days=7):
    """Ham günlük veri DEPOSUNDAN piyasa kur; yalnız YENİ günleri indir.
      • Depo yok / sembol eksik / >`full_refresh_days` gün geçmiş → TAM yenileme (5y bir kez).
      • Aksi → son depo gününden (DAHİL) bugüne yeni barları çek, ekle (keep=last → dünün
        yarım barı kapanışa düzelir). Sınırda büyük oran sıçraması = split → o sembol tam yenilenir.
      • Sonra göstergeler depodaki tam seriden TAZE hesaplanır (s.build_market_from_frames)."""
    cfg = _cfg(asof)
    tickers = _tickers_for(cfg)
    key = s._fmp_key()
    if not key:
        raise SystemExit("FMP_API_KEY yok (~/.portfolio_keys.json veya env).")
    today = pd.Timestamp.now().normalize()
    asof_ts = pd.Timestamp(asof).normalize() if asof else today
    end_str = asof_ts.strftime("%Y-%m-%d")
    _w = 6 if len(tickers) > 150 else cfg.download_workers

    store = _load_store()
    need_full = store is None
    if store is not None:
        if not set(tickers).issubset(set(store["frames"])):
            need_full = True
        last_full = pd.Timestamp(store.get("last_full", store["last_date"]))
        if (today - last_full).days >= full_refresh_days:
            need_full = True

    if need_full:
        full_start = s._period_to_start(cfg.period, cfg.warmup_calendar_buffer)
        print(f"[veri deposu] TAM yenileme (5y): {len(tickers)} sembol · {full_start}→{end_str}", flush=True)
        frames = s.fetch_daily_fmp(tickers, key, full_start, end_str, workers=_w)
        frames = {t: v for t, v in frames.items() if v is not None and len(v)}
        if not frames:
            raise SystemExit("FMP indirme başarısız (anahtar/plan/ağ).")
        store = {"frames": frames, "last_date": end_str, "last_full": end_str}
        _save_store(store)
    else:
        last = pd.Timestamp(store["last_date"])
        # Tazele: YENİ gün var VEYA depodaki son bar BUGÜN (gün-içi güncellenir → 15:45 taze almalı).
        if asof_ts > last or last >= today:
            inc_start = min(last, asof_ts).strftime("%Y-%m-%d")   # son günü DAHİL et → yarım bar kapanışa düzelir
            print(f"[veri deposu] artımlı: {inc_start}→{end_str} ({len(tickers)} sembol)", flush=True)
            newf = s.fetch_daily_fmp(tickers, key, inc_start, end_str, workers=_w)
            splits = []
            for t in tickers:
                nd = newf.get(t)
                if nd is None or not len(nd):
                    continue
                old = store["frames"].get(t)
                if old is None or not len(old):
                    store["frames"][t] = nd; continue
                lc = float(old["Close"].iloc[-1]); fn = float(nd["Close"].iloc[0])
                if lc > 0 and not (0.6 <= fn / lc <= 1.4):   # split/yeniden-ayar şüphesi
                    splits.append(t); continue
                comb = pd.concat([old, nd])
                store["frames"][t] = comb[~comb.index.duplicated(keep="last")].sort_index()
            if splits:
                print(f"[veri deposu] split şüphesi → tam yenilenen: {', '.join(splits[:12])}"
                      + (" ..." if len(splits) > 12 else ""), flush=True)
                fs = s._period_to_start(cfg.period, cfg.warmup_calendar_buffer)
                ref = s.fetch_daily_fmp(splits, key, fs, end_str, workers=_w)
                for t, v in ref.items():
                    if v is not None and len(v):
                        store["frames"][t] = v
            # KORUMA: eşzamanlı (çok-işçili) fetch FMP rate-limit'te SEMBOL BUDAYABİLİR
            # (özellikle pivot SPY) → depo sessizce donar, defter ilerlemez. Benchmark'ı
            # tek-işçiyle güvenilir tazele + geride kalanları kurtar (yoksa net UYARI bas).
            _incremental_repair(store, tickers, cfg, key, inc_start, end_str)
            # last_date = gerçek son SPY barı (FMP'de henüz olmayan günü "var" sanma)
            spy_df = store["frames"].get(cfg.benchmark)
            new_last = (spy_df.index[-1] if spy_df is not None and len(spy_df) else last)
            if asof_ts > last and new_last <= last:
                print(f"[veri deposu] ⚠️ beklenen yeni güne rağmen benchmark ({cfg.benchmark}) "
                      f"{last.date()}'ten ilerlemedi — FMP'de henüz yeni bar yok ya da çekim "
                      f"başarısız; defter bugün ilerlemeyecek (eski veriyle yayın YAPMA).", flush=True)
            store["last_date"] = new_last.strftime("%Y-%m-%d")
            _save_store(store)
        else:
            print(f"[veri deposu] güncel (son bar {store['last_date']} < asof, tam gün) → indirme yok", flush=True)

    # Depodaki ham seriden göstergeleri TAZE hesapla (asof'ta geleceği kes) + RS watchlist EKLE
    market = s.build_market_from_frames(store["frames"], cfg, today=asof_ts)
    return s.attach_watchlist(market, cfg)   # KRİTİK: RS top-50 kapısı (yoksa yanlış evren)


def _incremental_repair(store, tickers, cfg, key, inc_start, end_str):
    """Artımlı çekim KORUMASI — sessiz depo donmasını önler.

    Çok-işçili eşzamanlı fetch (FMP ücretsiz tier) yoğun anda (15:45 ET) bazı sembolleri
    BUDAYABİLİR: yanıt yalnız sınır gününü döndürür → o sembol ilerlemez. Pivot SPY budanırsa
    depo `last_date`'i (= SPY son barı) yerinde kalır, defterin 'yeni gün' listesi boşalır,
    sistem HATASIZ ama ESKİ veriyle yayın yapar. Bu koruma iki adımda onarır:
      1) benchmark'ı (SPY) HER ZAMAN tek-işçiyle (workers=1, rate-limit'e takılmaz) yeniden
         çekip birleştirir — pivot mutlaka taze olmalı.
      2) benchmark'ın son barının GERİSİNDE kalan (budanmış) sembolleri tespit edip düşük
         eşzamanlılıkla tazeler; kurtulamayanlar için net UYARI basar.
    Normal günde (bulk fetch sağlam) geride kalan olmaz → ek maliyet yalnız 1 SPY çağrısı."""
    bench = cfg.benchmark
    # 1) benchmark'ı sıralı (güvenilir) yeniden çek + birleştir
    bf = s.fetch_daily_fmp([bench], key, inc_start, end_str, workers=1).get(bench)
    if bf is not None and len(bf):
        old = store["frames"].get(bench)
        comb = pd.concat([old, bf]) if (old is not None and len(old)) else bf
        store["frames"][bench] = comb[~comb.index.duplicated(keep="last")].sort_index()
    spy_df = store["frames"].get(bench)
    if spy_df is None or not len(spy_df):
        return
    spy_last = spy_df.index[-1]
    # 2) benchmark'ın son barına ulaşamamış sembolleri bul. KISA boşluk (≤7 takvim günü) =
    #    eşzamanlı fetch budaması → onarılabilir. UZUN boşluk = muhtemelen delisted/halt
    #    (FMP'de güncel bar yok) → onarım denenmez, her gece gürültü üretmez.
    def _gap(t):
        df = store["frames"].get(t)
        if df is None or not len(df):
            return 10 ** 6
        return (spy_last - df.index[-1]).days
    truncated = [t for t in tickers if t != bench and 0 < _gap(t) <= 7]
    dead = [t for t in tickers if t != bench and _gap(t) > 7]
    if not truncated:
        if dead:
            print(f"[veri deposu] not: {len(dead)} sembol uzun süredir güncel değil "
                  f"(muhtemelen delisted/halt, evren dışı): {', '.join(sorted(dead)[:12])}"
                  + (" ..." if len(dead) > 12 else ""), flush=True)
        return
    print(f"[veri deposu] KORUMA: {len(truncated)} sembol benchmark'ın ({spy_last.date()}) "
          f"gerisinde (budanma şüphesi) → tek-işçiyle tazeleniyor: {', '.join(truncated[:12])}"
          + (" ..." if len(truncated) > 12 else ""), flush=True)
    rf = s.fetch_daily_fmp(truncated, key, inc_start, end_str, workers=1)
    for t, nd in rf.items():
        if nd is None or not len(nd):
            continue
        old = store["frames"].get(t)
        if old is None or not len(old):
            store["frames"][t] = nd; continue
        lc = float(old["Close"].iloc[-1]); fn = float(nd["Close"].iloc[0])
        if lc > 0 and not (0.6 <= fn / lc <= 1.4):   # split şüphesi → dokunma (haftalık tam yenileme halleder)
            continue
        comb = pd.concat([old, nd])
        store["frames"][t] = comb[~comb.index.duplicated(keep="last")].sort_index()
    still = [t for t in truncated if _gap(t) > 0]
    if still:
        print(f"[veri deposu] ⚠️ KORUMA sonrası hâlâ geride: {len(still)} sembol "
              f"({', '.join(still[:12])}{' ...' if len(still) > 12 else ''}) — bu semboller "
              f"{spy_last.date()} barı olmadan değerlenecek/işlenecek.", flush=True)


# =========================================================================
# DEFTER (LEDGER) — Position/Trade tam-sadakat serileştirme + diske yaz/oku
# =========================================================================
def _pos_to_d(p):
    """Açık pozisyonu motora birebir geri yüklenebilir dict'e çevir (tüm alanlar)."""
    return {"symbol": p.symbol, "entry_date": str(pd.Timestamp(p.entry_date).date()),
            "entry": p.entry, "stop": p.stop, "target": p.target,
            "shares": p.shares, "cost": p.cost, "score": p.score,
            "risk0": p.risk0, "partial_done": bool(p.partial_done),
            "atr_peak": p.atr_peak,
            "legs": [dict(l) for l in (p.legs or [])]}


def _d_to_pos(d):
    return s.Position(symbol=d["symbol"], entry_date=pd.Timestamp(d["entry_date"]),
                      entry=d["entry"], stop=d["stop"], target=d["target"],
                      shares=d["shares"], cost=d["cost"], score=d["score"],
                      risk0=d["risk0"], partial_done=d.get("partial_done", False),
                      legs=[dict(l) for l in d.get("legs", [])],
                      atr_peak=d.get("atr_peak", 0.0))


def _trade_to_d(t):
    return {"symbol": t.symbol, "entry_date": str(pd.Timestamp(t.entry_date).date()),
            "exit_date": str(pd.Timestamp(t.exit_date).date()), "entry": t.entry,
            "exit": t.exit, "shares": t.shares, "pnl": t.pnl, "pnl_pct": t.pnl_pct,
            "outcome": t.outcome, "score": t.score, "sector": t.sector}


def _d_to_trade(d):
    return s.Trade(symbol=d["symbol"], entry_date=pd.Timestamp(d["entry_date"]),
                   exit_date=pd.Timestamp(d["exit_date"]), entry=d["entry"], exit=d["exit"],
                   shares=d["shares"], pnl=d["pnl"], pnl_pct=d["pnl_pct"],
                   outcome=d["outcome"], score=d["score"], sector=d.get("sector", "—"))


def load_ledger(path=PAPER_QULLA_LEDGER):
    """Defteri oku; yoksa None (→ bootstrap gerekir)."""
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def _build_ledger(bt, last_date):
    """Motorun güncel durumundan defter dict'i üret (yazılmaya hazır, henüz diske yazmaz)."""
    return {"start": START, "initial": INITIAL,
            "last_date": str(pd.Timestamp(last_date).date()),
            "cash": bt.cash,
            "positions": [_pos_to_d(p) for p in bt.positions.values()],
            "trades": [_trade_to_d(t) for t in bt.trades],
            "equity_curve": [[str(pd.Timestamp(dt).date()), v] for dt, v in bt.equity_curve]}


def commit_ledger(r):
    """run_qulla sonucundaki defteri ATOMİK diske yaz. Yalnız gerçek gönderimde çağrılmalı
    (kuru test/dashboard yenilemesi defteri İLERLETMEZ)."""
    led = r.get("_ledger"); path = r.get("_ledger_path", PAPER_QULLA_LEDGER)
    if led is None:
        return
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(led, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _fix_split_scale(bt):
    """BÖLÜNME KORUMASI — kilitli pozisyonu yenilenen veri ölçeğine getir (CRWD 4:1, 02.07.2026).

    Depo bölünmeyi yakalayıp SERİYİ geriye dönük ayarlıyor ama defterdeki açık pozisyon eski
    ölçekte kalıyordu → sahte dev zarar + hedef/stop erişilmez. Burada her açık pozisyonun giriş
    fiyatı, verinin giriş günündeki (ayarlı) kapanışıyla karşılaştırılır; oran depo dedektörüyle
    aynı eşiğin (0.6-1.4) dışındaysa pozisyon ölçeklenir: fiyat alanları ÷oran, adetler ×oran —
    MALİYET DEĞİŞMEZ. Oran temiz tam-sayı bölünmeye (4:1, 1:5...) %8 tolerans içinde oturuyorsa
    tam orana yuvarlanır (girişteki 15:45-kapanış farkı korunur), oturmuyorsa gözlenen oran."""
    for sym, p in list(bt.positions.items()):
        df = bt.data.get(sym)
        if df is None or not len(df):
            continue
        ed = pd.Timestamp(p.entry_date).normalize()
        sub = df.loc[:ed]
        if not len(sub):
            continue
        close_ed = float(sub["Close"].iloc[-1])
        if close_ed <= 0 or p.entry <= 0:
            continue
        f = p.entry / close_ed
        if 0.6 <= f <= 1.4:
            continue
        big = f if f > 1 else 1.0 / f
        k = round(big)
        ratio = (float(k) if k >= 2 and abs(big - k) <= 0.08 * k else big)
        if f < 1:
            ratio = 1.0 / ratio
        old_entry, old_shares = p.entry, p.shares
        p.entry /= ratio; p.stop /= ratio; p.target /= ratio
        p.risk0 /= ratio; p.atr_peak /= ratio
        p.shares *= ratio
        for leg in (p.legs or []):
            leg["shares"] = leg.get("shares", 0.0) * ratio
            if leg.get("peak"):
                leg["peak"] = leg["peak"] / ratio
        print(f"[defter] {sym} bölünme ayarı ×{ratio:g}: {old_shares:.3f}×${old_entry:.2f} → "
              f"{p.shares:.3f}×${p.entry:.2f} (maliyet korunur)", flush=True)


def run_qulla(asof=None, market=None, ledger_path=PAPER_QULLA_LEDGER):
    """Defter-tabanlı ilerletme. İlk kez defter yoksa backtest ile START→asof bir kez doldurur
    (bootstrap); sonra ARTIMLI: defteri motora yükler, YALNIZ yeni günleri işler (geçmiş kilitli).
    Sonuç dict'i r["_ledger"]'da güncel defteri taşır — commit_ledger(r) ile kalıcılaşır.
    Döner: bugün açılan/çıkan + açık pozisyonlar + özet (eski biçimle birebir uyumlu)."""
    cfg = _cfg(asof)                       # cfg.start_date = START (sabit çapa), end_date = asof
    if market is None:
        # ARTIMLI ham veri deposu → 5y her gün indirilmez (yalnız yeni günler çekilir).
        market = load_market_incremental(asof)
    bt = DengeBacktester(cfg, market=market)   # ⭐ Aday 3: denge sıralaması + A200 freni
    cal = bt.calendar
    asof_ts = pd.Timestamp(asof).normalize() if asof else cal[-1]

    led = load_ledger(ledger_path)
    if led is None:
        # İLK KEZ (bootstrap): defteri backtest ile START→asof bir kez doldur, sonra dondur.
        bt.run()
    else:
        # ARTIMLI: defterdeki durumu motora yükle → YALNIZ yeni günleri işle (geçmiş DEĞİŞMEZ).
        bt.cash = led["cash"]
        bt.positions = {d["symbol"]: _d_to_pos(d) for d in led["positions"]}
        bt.trades = [_d_to_trade(t) for t in led["trades"]]
        bt.equity_curve = [(pd.Timestamp(dt), v) for dt, v in led["equity_curve"]]
        _fix_split_scale(bt)   # BÖLÜNME KORUMASI: seri yenilendiyse pozisyonu aynı ölçeğe getir
        last_done = pd.Timestamp(led["last_date"]).normalize()
        new_dates = [d for d in cal if last_done < d <= asof_ts]
        for date in new_dates:
            bt._step(date)
    if not bt.equity_curve:
        raise SystemExit("Qulla defteri: işlenecek gün yok (warmup/asof aralığı boş).")

    m = bt.metrics()
    eq = m["equity"]
    last = eq.index[-1]

    opened = [p for p in bt.positions.values()
              if pd.Timestamp(p.entry_date).normalize() == last]
    exited = [t for t in bt.trades
              if pd.Timestamp(t.exit_date).normalize() == last]

    cost_equity = bt.cash + sum(p.shares * p.entry for p in bt.positions.values())
    realized = sum(t.pnl for t in bt.trades)

    # rejim + evren bağlamı (tarama özeti için)
    def _spy(col):
        try:
            v = bt.spy.loc[last, col]
            return float(v) if not pd.isna(v) else None
        except Exception:
            return None
    spy_close, spy_sma200, spy_ret60 = _spy("Close"), _spy("SMA200"), _spy("RET60")
    spy_gate = bool(spy_close and spy_sma200 and spy_close > spy_sma200)
    a200 = bt._a200(last)                          # havuz genişliği (Aday 3 freni)
    regime_open = spy_gate and (a200 is None or a200 >= bt.A200_MIN)
    wl = market.get("watchlist") or {}
    watch_n = len(wl.get(last, set()))

    return {
        "asof": last.strftime("%Y-%m-%d"),
        "opened": opened, "exited": exited,
        "positions": list(bt.positions.values()),
        "cash": bt.cash, "cost_equity": cost_equity,
        "mkt_equity": bt._equity(last),
        "realized": realized,
        "roi": m["roi"], "spy_roi": m["spy_roi"], "alpha": m["alpha"],
        "win_rate": m["win_rate"], "profit_factor": m["profit_factor"],
        "max_dd": m["max_dd"], "n_closed": len(bt.trades),
        "closed_all": list(bt.trades),
        "started": START,
        "market": market, "regime_open": regime_open, "a200": a200,
        "spy_close": spy_close, "spy_ret60": spy_ret60, "watch_n": watch_n,
        "rs_n": cfg.rs_n, "pool_n": len([s for s in POOL]),
        # GÜNCEL DEFTER (henüz diske yazılmadı) — commit_ledger(r) ile kalıcılaşır.
        "_ledger": _build_ledger(bt, last), "_ledger_path": ledger_path,
    }


def qulla_summary(r):
    """Günlük tarama özeti (HTML) — Qulla-21'in bugünkü girişleri."""
    flag = "🟢 AÇIK" if r["regime_open"] else "🔴 KAPALI"
    n = len(r["opened"])
    spc = f"${r['spy_close']:.2f}" if r["spy_close"] else "—"
    a2 = f" · A200 %{r['a200']:.0f}" if r.get("a200") is not None else ""
    L = [f"<b>👑 Qulla-21 Tarayıcı ({r['asof']})</b>",
         f"🕒 15:45 ET · Rejim: {flag} · SPY {spc}{a2} · havuz {r['pool_n']} → RS top-{r['rs_n']}"]
    if not r["regime_open"]:
        L.append("\n⚠️ <b>Rejim KAPALI</b> (SPY&lt;SMA200 ya da A200&lt;%50) → yeni alım YOK; "
                 "açık pozisyonların çıkışları normal işler.")
    L.append(f"\n🚀 <b>BUGÜN GİRİŞ: {n}</b>" +
             (" — aşağıda grafik+detay 👇" if n else " (bugün yeni Qulla-21 sinyali yok)"))
    if n:
        L.append("🏆 " + " · ".join(html.escape(p.symbol) for p in r["opened"]))
    L.append("\n<i>Yöntem (Aday 3 · En dengeli): RS top-50 sistematik evren + 63g kırılım girişi · "
             "split çıkış (%60 +2R hedef / %40 21-EMA runner) · denge sıralaması (kalite+hareket) · "
             "A200≥%50 piyasa freni. Sinyal 15:45 anlık fiyatına göre. Eğitim amaçlı kağıt-trade.</i>")
    return "\n".join(L)


def chart_cands(r):
    """Bugün açılan Qulla pozisyonları için draw_chart uyumlu aday dict'leri."""
    market = r["market"]; asof = pd.Timestamp(r["asof"])
    spy60 = r.get("spy_ret60") or 0.0
    out = []
    for p in r["opened"]:
        df = market["data"].get(p.symbol)
        if df is None or not len(df):
            continue
        sub = df[df.index <= asof]
        if not len(sub):
            continue
        row = sub.iloc[-1]
        h63 = row.get("HIGH_PRIOR_63"); r60 = row.get("RET60"); atr = row.get("ATR")
        rs = (float(r60) - spy60) if (r60 == r60 and r60 is not None) else 0.0
        risk_pct = ((p.entry - p.stop) / p.entry * 100) if (p.stop and p.entry) else None
        out.append({
            "symbol": p.symbol, "status": "KIRILIM (63g)",
            "entry": round(p.entry, 2),
            "stop": round(p.stop, 2) if p.stop else round(p.entry * 0.9, 2),
            "partial_target": round(p.target, 2) if p.target else None,
            "high40": round(float(h63), 2) if (h63 == h63 and h63 is not None) else None,
            "breakout_lb": 63, "rs": round(rs, 1),
            "atr": round(float(atr), 2) if (atr == atr and atr is not None) else None,
            "risk_pct": round(risk_pct, 1) if risk_pct else None,
        })
    return out


def chart_caption(c):
    """Qulla-21 grafik aday açıklaması (HTML; &lt; HTML-güvenli)."""
    e = html.escape
    cap = (f"<b>{e(c['symbol'])}</b> · 🚀 KIRILIM (63g)\n"
           f"🎯 Giriş <code>${c['entry']}</code> · Stop <code>${c['stop']}</code>"
           + (f" (risk %{c['risk_pct']})" if c.get('risk_pct') else "") + "\n"
           f"📈 63g tepe <code>${c.get('high40','—')}</code> aşıldı · RS <b>+{c['rs']}</b>\n"
           f"📤 Çıkış (split): %60 <b>+2R</b> <code>${c.get('partial_target','—')}</code> hedef · "
           f"kalan yarı <b>kapanış &lt; 21-EMA</b> runner (ATR <code>${c.get('atr','—')}</code>)")
    return cap


def state_dict(r):
    """Dashboard için paper_trader uyumlu durum dict'i (Position/Trade → dict)."""
    def pos_d(p):
        d = {"symbol": p.symbol, "entry_date": str(pd.Timestamp(p.entry_date).date()),
             "entry": round(p.entry, 4), "entry_fill": round(p.entry, 4),
             "shares": round(p.shares, 6),
             "stop": round(p.stop, 4) if p.stop else None,
             "target": round(p.target, 4) if p.target else None,
             "score": p.score, "last_date": r["asof"],
             "alloc": round(p.shares * p.entry, 2),
             "cost": round(p.cost, 4)}      # gerçek maliyet bazı (komisyon dahil) → K/Z tutarlılığı
        legs = [l for l in (p.legs or []) if l["shares"] > 0]
        if legs:
            d["legs"] = [{"rule": l["rule"], "shares": round(l["shares"], 6),
                          "cost": round(l["cost"], 4)} for l in legs]
        return d

    def tr_d(t):
        return {"symbol": t.symbol, "entry_date": str(pd.Timestamp(t.entry_date).date()),
                "exit_date": str(pd.Timestamp(t.exit_date).date()),
                "entry": round(t.entry, 4), "entry_fill": round(t.entry, 4),
                "exit": round(t.exit, 4), "shares": round(t.shares, 6),
                "pnl": round(t.pnl, 2), "pnl_pct": round(t.pnl_pct, 2),
                "outcome": str(t.outcome)}
    return {"start_capital": INITIAL, "per_position": 0, "max_positions": 20,
            "cash": round(r["cash"], 2), "variant": "qulla", "started": r.get("started", START),
            "positions": [pos_d(p) for p in r["positions"]],
            "closed": [tr_d(t) for t in r["closed_all"]]}


def write_state(r, path=PAPER_QULLA):
    """Qulla durumunu dashboard için JSON'a yaz (atomik)."""
    import json, os
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state_dict(r), fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _exit_plan(p):
    """Açık split pozisyonun kalan bacak planı (kapanış teyitli; &lt; HTML-güvenli)."""
    rem = []
    for leg in (p.legs or []):
        if leg["shares"] <= 0:
            continue
        if leg["rule"] == "target":
            rem.append(f"+2R hedef <code>${p.target:.2f}</code>")
        elif leg["rule"] == "ema21":
            rem.append("kapanış &lt; 21-EMA")
        else:
            rem.append(html.escape(str(leg["rule"])))
    return " · ".join(rem) if rem else "çıkış tamamlandı"


def qulla_message(r, tag="👑 Qulla-21"):
    """Gün-sonu mesajı (HTML) — eod_message biçimiyle uyumlu.
    Aynı gün hem çıkıp hem yeni kırılımla tekrar giren sembol (ör. eski poz +2R kâr aldı
    ve aynı bar taze 63g kırılımı verdi) AÇILAN + ÇIKILAN'da çift görünmesin diye tek
    '↻ TEKRAR GİRİŞ' satırında birleştirilir. Realize toplamlar her bölümde kendi
    kalemlerini toplar; kümülatif realize (📊 Durum) tüm işlemleri kapsar → değişmez."""
    asof = r["asof"]
    L = [f"<b>📓 Kağıt Portföy — {tag} — Gün Sonu ({asof})</b>"]
    opened, exited = r["opened"], r["exited"]
    reentry = {p.symbol for p in opened} & {t.symbol for t in exited}
    plain_opened = [p for p in opened if p.symbol not in reentry]
    plain_exited = [t for t in exited if t.symbol not in reentry]
    if plain_opened:
        L.append(f"\n<b>🟢 AÇILAN ({len(plain_opened)})</b>")
        for p in sorted(plain_opened, key=lambda x: -(x.score or 0)):
            alloc = p.shares * p.entry
            L.append(f"• <b>{html.escape(p.symbol)}</b> @ <code>${p.entry:.2f}</code> · "
                     f"${alloc:.0f} · {p.shares:.3f} adet · {_exit_plan(p)}")
    if plain_exited:
        tot = sum(t.pnl for t in plain_exited)
        L.append(f"\n<b>🔴 ÇIKILAN ({len(plain_exited)})</b> · realize K/Z "
                 f"<b>{'+' if tot>=0 else ''}{tot:.2f}$</b>")
        for t in sorted(plain_exited, key=lambda x: -x.pnl):
            em = "✅" if t.pnl >= 0 else "❌"
            L.append(f"{em} <b>{html.escape(t.symbol)}</b> {html.escape(str(t.outcome))} @ "
                     f"<code>${t.exit:.2f}</code> · giriş <code>${t.entry:.2f}</code> · "
                     f"<b>{'+' if t.pnl>=0 else ''}{t.pnl:.2f}$ ({t.pnl_pct:+.1f}%)</b>")
    if reentry:
        L.append(f"\n<b>↻ TEKRAR GİRİŞ ({len(reentry)})</b> · "
                 f"<i>eski poz kapandı, aynı gün yeni kırılımla tekrar girildi</i>")
        opd = {p.symbol: p for p in opened}
        for sym in sorted(reentry):
            p = opd[sym]
            exs = sorted((t for t in exited if t.symbol == sym), key=lambda x: -x.pnl)
            expnl = sum(t.pnl for t in exs)
            outs = " + ".join(html.escape(str(t.outcome)) for t in exs)
            em = "✅" if expnl >= 0 else "❌"
            alloc = p.shares * p.entry
            L.append(f"{em} <b>{html.escape(sym)}</b> kapandı ({outs}) "
                     f"<b>{'+' if expnl>=0 else ''}{expnl:.2f}$</b> → "
                     f"🟢 yeni kırılımla tekrar @ <code>${p.entry:.2f}</code> · "
                     f"${alloc:.0f} · {_exit_plan(p)}")
    if not opened and not exited:
        L.append("\n<i>Bugün açılan/çıkılan pozisyon yok.</i>")
    pf = r["profit_factor"]
    pf_s = f"{pf:.2f}" if pf != float("inf") else "∞"
    # PİYASA bazlı (dashboard/​/portfolio ile aynı): kapanış fiyatlı özsermaye.
    # Genel K/Z = realize + gerçekleşmemiş; maliyet bazı DEĞİL (açık kâr atlanmasın).
    mkt_eq = r["mkt_equity"]
    tot_pl = mkt_eq - INITIAL
    unreal = tot_pl - r["realized"]                # gerçekleşmemiş (komisyon dahil, tutarlı)
    L.append(f"\n<b>📊 Durum:</b> {len(r['positions'])} açık · "
             f"nakit <code>${r['cash']:.0f}</code> · özsermaye (piyasa) "
             f"<code>${mkt_eq:.0f}</code> · realize "
             f"<b>{'+' if r['realized']>=0 else ''}{r['realized']:.0f}$</b> · unrealize "
             f"<b>{'+' if unreal>=0 else ''}{unreal:.0f}$</b>")
    L.append(f"<b>Genel K/Z: {'+' if tot_pl>=0 else ''}{tot_pl:.0f}$ "
             f"({tot_pl/INITIAL*100:+.1f}%)</b> · SPY {r['spy_roi']:+.1f}% · "
             f"win %{r['win_rate']:.0f} · PF {pf_s} · MaxDD {r['max_dd']:.1f}%")
    L.append(f"<i>Yöntem (Aday 3 · En dengeli): RS top-50 + 63g kırılım + split (%60 +2R / %40 "
             f"21-EMA runner) + denge sıralaması (kalite+hareket) + A200≥%50 freni. "
             f"Başlangıç {r['started']} (backtest ile dolduruldu). Havuz güncel endeks → "
             f"kalıntı survivorship. Eğitim amaçlı kağıt-trade.</i>")
    return "\n".join(L)


def _cli():
    asof = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else None
    r = run_qulla(asof)
    txt = qulla_message(r)
    for a, b in (("<b>", ""), ("</b>", ""), ("<i>", ""), ("</i>", ""),
                 ("<code>", ""), ("</code>", ""), ("&lt;", "<")):
        txt = txt.replace(a, b)
    print(txt)
    tot = (r["cost_equity"] / INITIAL - 1) * 100
    print(f"\n[özet] {r['asof']} · açılan {len(r['opened'])} · çıkan {len(r['exited'])} · "
          f"açık {len(r['positions'])} · toplam {tot:+.1f}% (SPY {r['spy_roi']:+.1f}%) · "
          f"özsermaye(maliyet) ${r['cost_equity']:.0f}")


if __name__ == "__main__":
    _cli()

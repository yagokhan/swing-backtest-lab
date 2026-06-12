# -*- coding: utf-8 -*-
"""BİRLEŞİK uzun/kısa portföy — TEK nakit havuzu, rejim-anahtarlı iki defter.

  • UZUN defter = GERÇEK Swing2Backtester örneği (kendi _manage/_open/_close'u ile) —
    uzun mantık YENİDEN YAZILMADI; motorun kendisi koşar → yayımlanmış 15-hücre
    sonuçlarıyla birebir uyum YAPISAL olarak garanti (shorts-kapalı eşdeğerlik testi ile
    ayrıca kanıtlanır). Şampiyon konfig: qswing kırılım + BTC ATR20%>2.5 kilidi +
    HYBRID_TREND çıkış.
  • KISA defter = ShortBacktester mantığı (miras): ayna kırılım, yalnız ayı rejiminde,
    kilitSİZ (çöküşler yüksek-ATR günleridir), hibrit kapatma + funding.

Rejimler giriş tarafında doğal ayrık (uzun: BTC>SMA200 · kısa: BTC<SMA200) ama
pozisyonlar rejim değişiminde TAŞINIR (kendi çıkış kuralları yönetir) → geçişlerde iki
defter aynı anda açık olabilir. TEK NAKİT HAVUZU bunu kaldıraçsız sınırlar: her açılış
havuzdan teminat rezerve eder; havuz yetmezse açılış reddedilir (brüt ≤ %100).

Boyutlandırma iki defterde de BİRLEŞİK özsermayeden (%20/pozisyon, defter başına max 5).
"""
from __future__ import annotations

import pandas as pd

import swing2_backtest as s
from short_backtest import ShortBacktester, ShortParams


def champion_long_cfg(start_date: str = "", end_date: str = "") -> s.Config:
    """Uzun tarafın şampiyon kripto konfigi (run_crypto_backtests 'hybrid' hücresi + kilit 2.5)."""
    cfg = s.Config()
    cfg.benchmark = "BTCUSDT"; cfg.price_source = "binance"
    cfg.use_earnings = False
    cfg.commission_bps = 10.0
    cfg.high52_bars = 365
    cfg.warmup_bars = 380
    cfg.entry_mode = "qswing_breakout"
    cfg.exit_mode = "tp_grid"; cfg.tp_mode = "HYBRID_TREND"; cfg.ma_confirm_close = True
    cfg.partial_tp = False
    cfg.regime_atr_filter = True; cfg.regime_atr_threshold = 2.5
    cfg.entry_fill_mode = "close"
    cfg.start_date = start_date; cfg.end_date = end_date
    return cfg


class _LongBook(s.Swing2Backtester):
    """Motorun uzun defteri — özsermayeye kısa defterin değeri eklenir (ortak havuz boyutlandırması)."""
    def __init__(self, cfg, market, short_marks_fn):
        super().__init__(cfg, market=market)
        self._short_marks = short_marks_fn

    def _equity(self, date):
        return super()._equity(date) + self._short_marks(date)


class CombinedBacktester(ShortBacktester):
    def __init__(self, market: dict, short_p: ShortParams, long_cfg: s.Config | None = None,
                 allow_long: bool = True, allow_short: bool = True):
        super().__init__(market, short_p)
        self.allow_long, self.allow_short = allow_long, allow_short
        self.eng = _LongBook(long_cfg or champion_long_cfg(short_p.start_date, short_p.end_date),
                             market, self._short_marks)
        self.eng.cash = 0.0          # havuz TEK: self.cash; motor çağrıları sync'lenir

    # ---- ortak havuz muhasebesi -------------------------------------------
    def _short_marks(self, date):
        """Kısa defterin işaretlenmiş değeri (nakit HARİÇ): teminat + unrealize − funding."""
        tot = 0.0
        for pos in self.positions.values():
            df = self.data[pos.symbol]
            c = df.loc[date, "Close"] if date in df.index else float("nan")
            mark = pos.entry_fill if pd.isna(c) else float(c)
            tot += pos.margin + pos.shares * (pos.entry_fill - mark) - pos.funding
        return tot

    def _equity(self, date):
        """BİRLEŞİK özsermaye — kısa defterin boyutlandırması da bunu görür (miras _open)."""
        self.eng.cash = self.cash
        return s.Swing2Backtester._equity(self.eng, date) + self._short_marks(date)

    def _eng(self, fn, *a):
        """Motor çağrısı: havuz nakdini motora ver, sonucu geri al (tek hesap)."""
        self.eng.cash = self.cash
        r = fn(*a)
        self.cash = self.eng.cash
        return r

    # ---- uzun girişler: motorun run() giriş bloğunun birebir portu ---------
    def _open_longs(self, date, common):
        ecfg = self.eng.cfg
        if (self.eng._vol_regime_locked(common)
                or len(self.eng.positions) >= ecfg.max_positions):
            return
        self.eng.cash = self.cash
        if self.eng.cash < self.eng._size(date):
            return
        spy_ret60 = self.eng.spy.loc[date, "RET60"]
        cands = []
        for sym, df in self.eng.data.items():
            if sym in self.eng.positions:
                continue
            row = df.loc[date]
            if (pd.isna(row["Close"]) or pd.isna(row["SMA200"]) or row["Close"] <= row["SMA200"]
                    or row["Close"] <= row["SMA50"] or row["Close"] <= row["SMA20"]
                    or pd.isna(row["SLOPE200"]) or row["SLOPE200"] <= 0):
                continue
            plan = s.compute_trade_plan(row, ecfg)
            dist = (row["Close"] - row["SMA20"]) / row["SMA20"]
            rs = self.eng._qswing_entry_ok(row, spy_ret60)
            if rs is None:
                continue
            _risk = plan["entry"] - plan["stop"]
            _rec = {"rs": rs,
                    "dist_52h_pct": (row["Close"] / row["HIGH52"] - 1) * 100,
                    "dist_sma20_pct": dist * 100,
                    "risk_pct": (_risk / plan["entry"] * 100) if plan["entry"] else None}
            qscore, _ = s._qswing_priority_score(_rec)
            if ecfg.qswing_min_score > 0 and qscore < ecfg.qswing_min_score:
                continue
            cands.append((qscore, -dist, sym, row, plan))
        cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
        for total, _nd, sym, row, plan in cands:
            if len(self.eng.positions) >= ecfg.max_positions or self.eng.cash < self.eng._size(date):
                break
            self.eng._open(sym, date, row, plan, total)
        self.cash = self.eng.cash

    # ---- ana döngü ----------------------------------------------------------
    def run(self):
        p = self.p
        cal = self.calendar
        start = p.warmup_bars
        if p.start_date:
            start = max(start, int(cal.searchsorted(pd.Timestamp(p.start_date))))
        end = len(cal)
        if p.end_date:
            end = int(cal.searchsorted(pd.Timestamp(p.end_date), side="right"))
        trading = cal[start:end]
        if not len(trading):
            raise SystemExit("Birleşik backtest: seçilen aralıkta bar yok.")
        for date in trading:
            # 1) çıkışlar — iki defter de KENDİ kurallarıyla, rejimden bağımsız yönetilir
            if self.allow_long:
                self._eng(self.eng._manage, date)
            if self.allow_short:
                ShortBacktester._manage(self, date)
            # 2) girişler — rejime göre tek taraf
            common = self.eng._common(date)
            if common["spy_above_sma200"]:
                if self.allow_long:
                    self._open_longs(date, common)
            elif self.allow_short and not self._vol_locked(date):
                for sym, close, rs in self._scan_entries(date):
                    if len(self.positions) >= p.max_positions:
                        break
                    self._open(sym, date, close, rs)
            self.equity_curve.append((date, self._equity(date)))
        # pencere sonu: iki defteri de son geçerli kapanıştan kapat (motorla aynı kural)
        last = trading[-1]
        if self.allow_long:
            self.eng.cash = self.cash
            for sym in list(self.eng.positions.keys()):
                closes = self.eng.data[sym]["Close"].loc[:last].dropna()
                px = float(closes.iloc[-1]) if len(closes) else self.eng.positions[sym].entry
                self.eng._close(sym, last, px, "EOD")
            self.cash = self.eng.cash
        self._force_cover_all(last)
        return self

    def metrics(self):
        m = super().metrics()                          # roi/dd/bench: havuz + birleşik eğri
        lt, st = self.eng.trades, self.trades
        wins = [t for t in lt if t.pnl > 0] + [t for t in st if t.pnl > 0]
        loss = [t for t in lt if t.pnl <= 0] + [t for t in st if t.pnl <= 0]
        gp, gl = sum(t.pnl for t in wins), abs(sum(t.pnl for t in loss))
        m.update({"trades": len(lt) + len(st), "long_trades": len(lt), "short_trades": len(st),
                  "long_pnl": sum(t.pnl for t in lt), "short_pnl": sum(t.pnl for t in st),
                  "win_rate": (len(wins) / (len(lt) + len(st)) * 100) if (lt or st) else 0.0,
                  "profit_factor": (gp / gl) if gl else float("inf")})
        return m

# -*- coding: utf-8 -*-
"""KISA (short) taraf backtester — uzun motorun AYNA mantığı, ayrı ve odaklı modül.

Uzun motora (swing2_backtest) DOKUNMAZ: aynı market sözlüğünü (download_and_align_data
çıktısı) tüketir, kısa-tarafa özgü indikatörleri (LOW52, LOW_PRIOR_N) kendi içinde ekler.

GİRİŞ (qswing kırılımının aynası — yalnız AYI rejiminde):
  • Rejim: BTC < SMA200 (boğada kısa açılmaz) · opsiyonel BTC ATR20% oynaklık kilidi
  • Sembol: Close < SMA200 & < SMA50 & < SMA20 · SLOPE200 < 0 (Aşama 4)
  • Kırılım: Close < önceki N-gün DİP'i (LOW_PRIOR_N) · 52H dibe yakın (Close ≤ mult×LOW52)
  • Momentum: 60g getiri BTC'nin ALTINDA (rs ≤ rs_max) ve negatif

ÇIKIŞ (kapanış teyitli — uzun şampiyonların aynası):
  • 'atr_cover': dip takibi; KAPANIŞ > dip + mult×ATR → tüm pozisyon kapat (şamdan aynası)
  • 'hybrid'  : %50 KAPANIŞ>EMA8 · %50 KAPANIŞ>EMA21 (HYBRID_TREND aynası, felaket stopu yok)

GERÇEK KISA MUHASEBESİ (ters-fiyat hilesi DEĞİL):
  pnl = adet×(giriş_dolum − kapatma_dolum) − komisyon(2 bacak) − funding
  Spot'ta kısa yok → perp varsayımı: funding maliyeti GÜNLÜK sabit bps (vars. 3bps/gün ≈
  yıllık ~%11, ayı piyasasında kısaların funding ÖDEDİĞİ varsayımıyla MUHAFAZAKÂR).
  Slippage ters yönde: giriş (sat) = close×(1−slip) · kapatma (al) = close×(1+slip).
  Teminat 1× (kaldıraçsız): pozisyon notyoneli nakitten rezerve edilir.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ShortParams:
    breakdown_lb: int = 40            # önceki N-gün dip kırılımı
    low52_bars: int = 365             # 52H dip penceresi (kripto yılı)
    near_low_mult: float = 1.333      # Close ≤ mult × LOW52 (uzun taraftaki 0.75×HIGH52'nin aynası)
    rs_max: float = 0.0               # 60g RS (sembol − BTC) tavanı; ≤ 0 = BTC'den zayıf
    exit_mode: str = "hybrid"         # 'hybrid' | 'atr_cover'
    atr_cover_mult: float = 2.5       # atr_cover: dip + mult×ATR üstünde kapanış → kapat
    regime_atr_filter: bool = False   # BTC oynaklık kilidi (uzun taraftakiyle aynı metrik)
    regime_atr_threshold: float = 2.5
    funding_bps_daily: float = 3.0    # perp funding maliyeti (bps/gün, pozisyon açıkken)
    initial_capital: float = 100_000.0
    max_positions: int = 5
    max_position_pct: float = 0.20
    commission_bps: float = 10.0      # bacak başına yüzde komisyon
    entry_slippage_bps: float = 8.0   # giriş (market SAT) — daha DÜŞÜK fiyata satarsın
    slippage_bps: float = 10.0        # kapanış-teyitli kapatma (market AL) — daha YÜKSEĞE alırsın
    start_date: str = ""
    end_date: str = ""
    warmup_bars: int = 380


@dataclass
class ShortPosition:
    symbol: str
    entry_date: pd.Timestamp
    entry: float                      # sinyal kapanışı
    entry_fill: float                 # slippage'lı gerçek satış fiyatı
    shares: float
    margin: float                     # rezerve teminat = shares × entry_fill
    trough: float                     # atr_cover: giriş sonrası en düşük Low
    funding: float = 0.0              # birikmiş funding maliyeti ($)
    legs: list = field(default_factory=list)   # hybrid: [{'rule','shares'}]
    rs: float = 0.0


@dataclass
class ShortTrade:
    symbol: str
    entry_date: object
    exit_date: object
    entry: float
    exit: float
    shares: float
    pnl: float
    pnl_pct: float
    outcome: str


def _prep(df, p: ShortParams):
    """Kısa-tarafa özgü kolonları ekle (kopya üzerinde; market dict'i değişmez).
    Kripto çerçevelerinde iç boşluk yok (7g/hafta) → reindex'li seride rolling güvenli."""
    d = df.copy()
    d["LOW52"] = d["Low"].rolling(p.low52_bars).min()
    d["LOW_PRIOR"] = d["Low"].rolling(p.breakdown_lb).min().shift(1)
    return d


class ShortBacktester:
    def __init__(self, market: dict, p: ShortParams):
        self.p = p
        self.spy = market["spy"]                      # = benchmark (kripto: BTCUSDT)
        self.calendar = market["calendar"]
        self.data = {s: _prep(df, p) for s, df in market["data"].items()}
        self.cash = p.initial_capital
        self.positions: dict[str, ShortPosition] = {}
        self.trades: list[ShortTrade] = []
        self.equity_curve = []
        self._comm = p.commission_bps / 1e4
        self._eslip = p.entry_slippage_bps / 1e4
        self._xslip = p.slippage_bps / 1e4

    # ---- piyasa bağlamı ---------------------------------------------------
    def _regime_bear(self, date):
        s = self.spy.loc[date]
        return (not pd.isna(s["SMA200"])) and s["Close"] < s["SMA200"]

    def _vol_locked(self, date):
        if not self.p.regime_atr_filter:
            return False
        v = self.spy.loc[date].get("ATR20_PCT")
        return v is not None and not pd.isna(v) and float(v) > self.p.regime_atr_threshold

    # ---- muhasebe ---------------------------------------------------------
    def _equity(self, date):
        eq = self.cash
        for pos in self.positions.values():
            df = self.data[pos.symbol]
            c = df.loc[date, "Close"] if date in df.index else float("nan")
            mark = pos.entry_fill if pd.isna(c) else float(c)
            eq += pos.margin + pos.shares * (pos.entry_fill - mark) - pos.funding
        return eq

    def _cover(self, sym, date, fill_base, frac, outcome):
        """Pozisyonun frac kadarını fill_base×(1+slip)'ten geri AL (kapat)."""
        pos = self.positions[sym]
        fill = fill_base * (1 + self._xslip)
        sh = pos.shares * frac
        gross = sh * (pos.entry_fill - fill)
        fees = sh * pos.entry_fill * self._comm + sh * fill * self._comm
        fpart = pos.funding * frac
        pnl = gross - fees - fpart
        mpart = pos.margin * frac
        self.cash += mpart + gross - sh * fill * self._comm - fpart   # giriş komisyonu açılışta ödendi
        self.trades.append(ShortTrade(sym, pos.entry_date, date, pos.entry_fill, fill, sh,
                                      pnl, (pos.entry_fill / fill - 1) * 100, outcome))
        pos.shares -= sh
        pos.margin -= mpart
        pos.funding -= fpart
        if pos.shares <= 1e-12:
            self.positions.pop(sym)

    # ---- günlük yönetim ----------------------------------------------------
    def _manage(self, date):
        p = self.p
        for sym in list(self.positions):
            pos = self.positions[sym]
            df = self.data[sym]
            if date not in df.index:
                continue
            row = df.loc[date]
            close, low = row["Close"], row["Low"]
            if pd.isna(close):
                continue
            pos.funding += pos.shares * pos.entry_fill * p.funding_bps_daily / 1e4
            if not pd.isna(low):
                pos.trough = min(pos.trough, float(low))
            if p.exit_mode == "atr_cover":
                atr = row["ATR"]
                if pd.isna(atr):
                    continue
                level = pos.trough + p.atr_cover_mult * float(atr)
                if close > level:                      # kapanış teyidi → tüm pozisyonu kapat
                    self._cover(sym, date, float(close), 1.0, "ATR")
            else:                                      # hybrid: %50 EMA8 · %50 EMA21 üstü kapanış
                e8, e21 = row.get("EMA8"), row.get("EMA21")
                for leg in pos.legs:
                    if leg["shares"] <= 0:
                        continue
                    ma = e8 if leg["rule"] == "ema8" else e21
                    if ma is None or pd.isna(ma) or close <= ma:
                        continue
                    frac = leg["shares"] / pos.shares
                    leg["shares"] = 0.0
                    self._cover(sym, date, float(close), frac, leg["rule"].upper())
                    if sym not in self.positions:
                        break

    def _scan_entries(self, date):
        p = self.p
        spy_r60 = self.spy.loc[date, "RET60"]
        sp = 0.0 if pd.isna(spy_r60) else float(spy_r60)
        out = []
        for sym, df in self.data.items():
            if sym in self.positions or date not in df.index:
                continue
            row = df.loc[date]
            c = row["Close"]
            if pd.isna(c):
                continue
            gates = (not pd.isna(row["SMA200"]) and c < row["SMA200"]
                     and not pd.isna(row["SMA50"]) and c < row["SMA50"]
                     and not pd.isna(row["SMA20"]) and c < row["SMA20"]
                     and not pd.isna(row["SLOPE200"]) and row["SLOPE200"] < 0)
            if not gates:
                continue
            lo52, lp, r60 = row["LOW52"], row["LOW_PRIOR"], row["RET60"]
            if pd.isna(lo52) or pd.isna(lp) or pd.isna(r60):
                continue
            rs = float(r60) - sp
            if not (c < lp and c <= p.near_low_mult * lo52 and r60 < 0 and rs <= p.rs_max):
                continue
            out.append((sym, float(c), rs))
        out.sort(key=lambda x: x[2])                   # en zayıf (en negatif RS) önce
        return out

    def _open(self, sym, date, close, rs):
        p = self.p
        eq = self._equity(date)
        budget = eq * p.max_position_pct
        if self.cash < budget or budget <= 0:
            return False
        fill = close * (1 - self._eslip)               # market SAT → aşağı kayar
        shares = budget / (fill * (1 + self._comm))    # teminat + giriş komisyonu = budget
        margin = shares * fill
        self.cash -= margin + shares * fill * self._comm
        pos = ShortPosition(sym, date, close, fill, shares, margin, trough=close, rs=rs)
        if p.exit_mode == "hybrid":
            pos.legs = [{"rule": "ema8", "shares": shares / 2},
                        {"rule": "ema21", "shares": shares - shares / 2}]
        self.positions[sym] = pos
        return True

    # ---- koşu ---------------------------------------------------------------
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
            raise SystemExit("Kısa backtest: seçilen aralıkta bar yok.")
        for date in trading:
            self._manage(date)
            if (self._regime_bear(date) and not self._vol_locked(date)
                    and len(self.positions) < p.max_positions):
                for sym, close, rs in self._scan_entries(date):
                    if len(self.positions) >= p.max_positions:
                        break
                    self._open(sym, date, close, rs)
            self.equity_curve.append((date, self._equity(date)))
        self._force_cover_all(trading[-1])
        return self

    def _force_cover_all(self, last):
        """Pencere sonu: kalan kısa pozisyonları son geçerli kapanıştan kapat (temiz muhasebe)."""
        for sym in list(self.positions):
            df = self.data[sym]
            c = df.loc[last, "Close"] if last in df.index else None
            if c is None or pd.isna(c):
                c = self.positions[sym].entry_fill
            self._cover(sym, last, float(c), 1.0, "EOD")

    def metrics(self):
        eq = pd.Series(dict(self.equity_curve)).sort_index()
        roi = (self.cash / self.p.initial_capital - 1) * 100
        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]
        gp, gl = sum(t.pnl for t in wins), abs(sum(t.pnl for t in losses))
        sc = self.spy["Close"]
        bench = (sc.loc[eq.index[-1]] / sc.loc[eq.index[0]] - 1) * 100 if len(eq) else 0.0
        return {"roi": roi, "bench_roi": float(bench), "alpha": roi - float(bench),
                "max_dd": float(((eq / eq.cummax() - 1) * 100).min()) if len(eq) else 0.0,
                "win_rate": (len(wins) / len(self.trades) * 100) if self.trades else 0.0,
                "trades": len(self.trades),
                "profit_factor": (gp / gl) if gl else float("inf"), "equity": eq}

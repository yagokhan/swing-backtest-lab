#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 GÖLGE GÜNLÜĞÜ BACKFILL + MODEL EĞİTİMİ (tek seferlik / gerektiğinde yeniden).

Veri deposundaki 5y ile TARİHSEL kırılım adayları üretir — motorun KENDİ kapılarıyla
birebir (DengeBacktester: SPY>SMA200 + A200≥%50 + vol-kilidi + RS top-50 watchlist +
Aşama-2 + _qswing_entry_ok 63g kırılım). Portföy durumu (slot/nakit/eldeki sembol)
BİLEREK dışarıda: sahte-kırılım sorusu sinyalin kendisine aittir, cüzdana değil.

Sonra ml_shadow_report ile AYNI özellikler + AYNI etiket kuralı (15g stop-önce=1 /
hedef-önce=0) uygulanır, purged walk-forward ile dürüstçe doğrulanır ve final model
~/.swing_ml/xgb_false_breakout.json'a yazılır (+ model_meta.json karnesi).

Bilinen sınırlar (rapor karnesinde de anılır):
  • evren = BUGÜNKÜ sp500_ndx listesi geçmişe uygulanır (hayatta-kalan yanlılığı);
  • giriş = plan T-Close (canlı 15:45 dolumundan ~bps farklı) → sınır vakalarında
    küçük etiket gürültüsü;
  • ardışık günlerde aynı sembolün tekrar sinyali korelasyonlu örnek üretir →
    değerlendirme bu yüzden ZAMAN-SIRALI ve purge'lü (rastgele split ASLA).

Kullanım: python3 ml_backfill.py [--no-train]  (log'u kurar; --no-train eğitimi atlar)
"""
import argparse
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

import ml_shadow_report as m
import qulla_paper as qp
import swing2_backtest as s

PURGE_DAYS = 21  # eğitim kesim tarihinden geriye atılan gün (etiket penceresi taşması)
FOLD_CUTS = ["2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01"]

XGB_PARAMS = dict(n_estimators=300, max_depth=3, learning_rate=0.05,
                  subsample=0.8, colsample_bytree=0.8, eval_metric="logloss")


# ---------------------------------------------------------------- sinyal toplama
def build_engine():
    """Depodan (İNDİRMESİZ) piyasayı kur; watchlist ŞART (yoksa RS kapısı çöker)."""
    cfg = qp._cfg()          # canlı Qulla-21/Aday-3 konfigi; end_date boş → tüm tarih
    store = qp._load_store()
    if not store:
        raise SystemExit("veri deposu yok — önce canlı sistemin store'u kurulmalı")
    market = s.build_market_from_frames(store["frames"], cfg)
    s.attach_watchlist(market, cfg)
    if not market.get("watchlist"):
        raise SystemExit("watchlist üretilemedi — RS kapısı olmadan backfill YANLIŞ olur")
    bt = qp.DengeBacktester(cfg, market=market)
    return bt, cfg, store["frames"]


def collect_signals(bt, cfg):
    """Her işlem günü için motor kapılarından geçen TÜM kırılım adayları
    (slot/nakit/eldeki-sembol hariç — bkz. modül docstring)."""
    out = []
    for date in bt.calendar[cfg.warmup_bars:]:
        common = bt._common(date)   # DengeBacktester: SPY>SMA200 VE A200>=%50
        if not common["spy_above_sma200"] or bt._vol_regime_locked(common):
            continue
        spy_ret60 = bt.spy.loc[date, "RET60"]
        for sym, df in bt.data.items():
            row = df.loc[date]
            if (pd.isna(row["Close"]) or pd.isna(row["SMA200"]) or row["Close"] <= row["SMA200"]
                    or row["Close"] <= row["SMA50"] or row["Close"] <= row["SMA20"]
                    or pd.isna(row["SLOPE200"]) or row["SLOPE200"] <= 0):
                continue
            if not bt._in_watchlist(sym, date):
                continue
            rs = bt._qswing_entry_ok(row, spy_ret60)
            if rs is None:
                continue
            plan = s.compute_trade_plan(row, cfg)
            entry, stop = plan["entry"], plan["stop"]
            if not entry or entry - stop <= 0:
                continue
            atr, h63 = row.get("ATR"), row.get("HIGH_PRIOR_63")
            out.append((date, {
                "symbol": sym, "entry": round(float(entry), 4),
                "stop": round(float(stop), 4),
                "partial_target": round(float(entry + 2.0 * (entry - stop)), 4),  # split A: +2R
                "atr": float(atr) if atr == atr else None,
                "rs": round(float(rs), 2),
                "risk_pct": round(float((entry - stop) / entry * 100), 2),
                "high40": float(h63) if h63 == h63 else None,
            }))
    return out


def backfill_log(signals, frames):
    """Sinyalleri gölge günlüğüne yaz (src=backfill; mevcut canlı satırlar korunur)."""
    recs = m._read_log()
    for r in recs:                       # eski şema göçü: src boşsa canlı satırdır
        r.setdefault("src", "") or r.update(src="live")
        if r["src"] == "live":
            r["taken"] = "1"             # canlı liste = fiilen açılan pozisyonlar
    seen = {(r["asof"], r["symbol"]) for r in recs}
    n = 0
    for date, cand in signals:
        asof = date.strftime("%Y-%m-%d")
        if (asof, cand["symbol"]) in seen:
            continue
        f = m.build_features(cand, frames, date)
        rec = {"asof": asof, "symbol": cand["symbol"], "entry": cand["entry"],
               "stop": cand["stop"], "target": cand["partial_target"],
               "taken": 0, "src": "backfill", "label": ""}
        rec.update({k: (round(v, 4) if v == v else "") for k, v in f.items()})
        recs.append(rec); n += 1
    m._write_log(recs)
    return n, recs


# ---------------------------------------------------------------- değerlendirme
def _auc(y, p):
    """Mann-Whitney AUC (bağlar ortalama-rank)."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    ranks = pd.Series(np.concatenate([pos, neg])).rank().values
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _fit(df):
    from xgboost import XGBClassifier
    mod = XGBClassifier(**XGB_PARAMS)
    mod.fit(df[m.FEATURES].apply(pd.to_numeric, errors="coerce"), df["label"].astype(int))
    return mod

def _proba(mod, df):
    return mod.predict_proba(df[m.FEATURES].apply(pd.to_numeric, errors="coerce"))[:, 1]


def walk_forward(df):
    """Purged walk-forward: kesimden PURGE_DAYS öncesi eğitimden atılır (etiket taşması)."""
    folds = []
    for i, cut in enumerate(FOLD_CUTS):
        cut_ts = pd.Timestamp(cut)
        t_end = pd.Timestamp(FOLD_CUTS[i + 1]) if i + 1 < len(FOLD_CUTS) else pd.Timestamp("2099-01-01")
        tr = df[df["asof_ts"] < cut_ts - pd.Timedelta(days=PURGE_DAYS)]
        te = df[(df["asof_ts"] >= cut_ts) & (df["asof_ts"] < t_end)]
        if len(tr) < 200 or len(te) < 50:
            continue
        p = _proba(_fit(tr), te)
        y = te["label"].astype(int).values
        k = max(1, len(te) // 5)
        order = np.argsort(-p)                       # p = P(sahte) yüksekten düşüğe
        folds.append({"cutoff": cut, "n_train": len(tr), "n_test": len(te),
                      "base_test": round(float(y.mean()), 3),
                      "auc": round(_auc(y, p), 3) if _auc(y, p) is not None else None,
                      "top20_false": round(float(y[order[:k]].mean()), 3),
                      "bottom20_false": round(float(y[order[-k:]].mean()), 3)})
    return folds


# ---------------------------------------------------------------- ana akış
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-train", action="store_true", help="yalnız log kur, eğitme")
    args = ap.parse_args()

    print("• motor kuruluyor (depodan, indirmesiz)…", flush=True)
    bt, cfg, frames = build_engine()
    print(f"  takvim {bt.calendar[0].date()} → {bt.calendar[-1].date()} · "
          f"{len(bt.data)} sembol · warmup {cfg.warmup_bars}", flush=True)

    print("• tarihsel sinyaller toplanıyor…", flush=True)
    signals = collect_signals(bt, cfg)
    print(f"  {len(signals)} aday-gün sinyali", flush=True)

    print("• gölge günlüğüne yazılıyor + etiketleniyor…", flush=True)
    n_new, _ = backfill_log(signals, frames)
    n_lab, recs = m.label_pending(frames)
    lab = [r for r in recs if r["label"] != ""]
    print(f"  +{n_new} yeni satır · +{n_lab} etiket → toplam {len(recs)} satır, {len(lab)} etiketli", flush=True)

    if args.no_train:
        return

    df = pd.DataFrame(lab)
    df["asof_ts"] = pd.to_datetime(df["asof"])
    df = df.sort_values("asof_ts")
    base = df["label"].astype(int).mean()
    print(f"• taban sahte-oranı: %{base*100:.1f} ({df['asof'].min()} → {df['asof'].max()})", flush=True)

    print("• purged walk-forward doğrulama…", flush=True)
    folds = walk_forward(df)
    for f in folds:
        print(f"  {f['cutoff']}: n_test={f['n_test']:4d} AUC={f['auc']} "
              f"taban=%{f['base_test']*100:.0f} → en-riskli%20'de sahte %{f['top20_false']*100:.0f} / "
              f"en-güvenli%20'de %{f['bottom20_false']*100:.0f}", flush=True)

    print("• final model TÜM etiketli veriyle eğitiliyor…", flush=True)
    mod = _fit(df)
    os.makedirs(m.ML_DIR, exist_ok=True)
    mod.save_model(m.MODEL_PATH)
    imp = {k: round(float(v), 4) for k, v in zip(m.FEATURES, mod.feature_importances_)}
    meta = {"trained_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "n_rows": len(recs), "n_labeled": len(lab), "base_rate": round(float(base), 3),
            "src_note": "backfill 5y + canlı gölge; bugünkü evren listesi geçmişe uygulandı",
            "label_rule": f"{m.HORIZON} iş günü: stop-önce=1, +2R-önce=0, dolmazsa kapanış<giriş",
            "folds": folds, "features": m.FEATURES, "importances": imp,
            "xgb_params": XGB_PARAMS}
    with open(m.META_PATH, "w") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print(f"  kaydedildi: {m.MODEL_PATH}\n  önem sırası: "
          + " · ".join(f"{k}={v}" for k, v in sorted(imp.items(), key=lambda x: -x[1])), flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 ML GÖLGE MODU — Sahte Kırılım (False Breakout) raporu.

Canlı sisteme DOKUNMAZ (salt-okur):
  girdi  : ~/.swing_lastscan_data.json  (22:45 taramasının yapısal çıktısı)
           ~/.swing_daily_store.pkl     (ham OHLCV deposu; indirme tetiklemez)
  model  : ~/.swing_ml/xgb_false_breakout.json  (XGBoost; yoksa rapor "veri toplama"
           modunda üretilir, skor sütunu boş kalır)
  çıktı  : dashboard_static/adaylar-ml.html     (dashboard /adaylar-ml rotası sunar)
           ~/.swing_ml/shadow_log.csv           (gölge günlüğü = gelecekteki eğitim seti;
           her aday-gün bir satır, etiket sonradan label_pending ile otomatik dolar)

Etiket tanımı (label): kırılım sonrası HORIZON iş günü içinde
  Low ≤ stop, hedeften ÖNCE  → 1 (SAHTE kırılım)
  High ≥ +2R hedef önce      → 0 (gerçek kırılım)
  ikisi aynı barda           → 1 (muhafazakâr)
  süre dolar, kapanış<giriş  → 1, aksi 0

Kullanım:
  python3 ml_shadow_report.py            # günlük akış: özellik çıkar + logla + etiketle + HTML
  python3 ml_shadow_report.py --train    # yeterli etiketli satır varsa modeli eğit+kaydet
"""
import argparse
import csv
import html
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

import qulla_paper as qp

SCAN_DATA  = os.path.expanduser("~/.swing_lastscan_data.json")
ML_DIR     = os.path.expanduser("~/.swing_ml")
MODEL_PATH = os.path.join(ML_DIR, "xgb_false_breakout.json")
SHADOW_LOG = os.path.join(ML_DIR, "shadow_log.csv")
META_PATH  = os.path.join(ML_DIR, "model_meta.json")  # eğitim/doğrulama özeti (ml_backfill.py yazar)
OUT_HTML   = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "dashboard_static", "adaylar-ml.html")

HORIZON = 15          # etiketleme ileri-bakış penceresi (iş günü)
MIN_TRAIN_ROWS = 60   # bundan az etiketli satırla model eğitilmez

# Model her zaman BU sırayla eğitilir/çağrılır — sıra değişirse model geçersiz olur.
FEATURES = ["vol_ratio", "atr_pct", "rs63_vs_spy", "brk_margin_pct",
            "range_pos", "ret5_pct", "rs_scan", "risk_pct"]

FEATURE_TR = {  # tablo başlığı + açıklama kartı
    "vol_ratio":      ("Hacim oranı",   "kırılım günü hacmi / 20 günlük ortalama hacim (≥1.5 = teyitli)"),
    "atr_pct":        ("ATR %",         "günlük ortalama hareket / giriş fiyatı — hissenin oynaklığı"),
    "rs63_vs_spy":    ("RS-63 vs SPY",  "son 63 gün getirisi − SPY getirisi (yüzde puan, göreceli güç)"),
    "brk_margin_pct": ("Kırılım payı %","giriş fiyatının 63g zirvesinin ne kadar üstünde olduğu"),
    "range_pos":      ("Kapanış gücü",  "kırılım barında (Kapanış−Düşük)/(Yüksek−Düşük); 1.0 = tepeden kapanış"),
    "ret5_pct":       ("5g momentum %", "son 5 işlem günü getirisi"),
    "rs_scan":        ("Tarayıcı RS",   "canlı tarayıcının kendi RS puanı"),
    "risk_pct":       ("Risk %",        "giriş→stop mesafesi (pozisyon riski)"),
}


# ---------------------------------------------------------------- veri katmanı
def load_candidates(path=SCAN_DATA):
    """Son taramanın yapısal aday listesi (buyable = o günün kırılım sinyalleri)."""
    with open(path) as fh:
        d = json.load(fh)
    return d.get("buyable", []) or [], d


def load_frames():
    """Ham OHLCV deposu — SALT-OKUR (indirme/güncelleme tetiklemez)."""
    store = qp._load_store()
    return (store or {}).get("frames", {})


def build_features(cand, frames, asof):
    """Tek aday için özellik vektörü. Veri eksikse NaN (XGBoost NaN'ı yönetir)."""
    f = {k: np.nan for k in FEATURES}
    entry = cand.get("entry") or np.nan
    f["atr_pct"]  = (cand.get("atr") or np.nan) / entry * 100.0
    f["rs_scan"]  = cand.get("rs", np.nan)
    f["risk_pct"] = cand.get("risk_pct", np.nan)
    hi = cand.get("high40")  # alan adı tarihsel; 63g kırılım referans seviyesi
    if hi:
        f["brk_margin_pct"] = (entry / hi - 1.0) * 100.0

    df = frames.get(cand["symbol"])
    spy = frames.get("SPY")
    if df is None or len(df) < 70:
        return f
    df = df[df.index <= asof]
    if len(df) < 70:
        return f
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    v20 = v.iloc[-21:-1].mean()
    if v20 and v20 > 0:
        f["vol_ratio"] = float(v.iloc[-1] / v20)
    rng = h.iloc[-1] - l.iloc[-1]
    if rng > 0:
        f["range_pos"] = float((c.iloc[-1] - l.iloc[-1]) / rng)
    f["ret5_pct"] = float((c.iloc[-1] / c.iloc[-6] - 1.0) * 100.0)
    r63 = (c.iloc[-1] / c.iloc[-64] - 1.0) * 100.0
    if spy is not None and len(spy) >= 70:
        sc = spy[spy.index <= asof]["Close"]
        if len(sc) >= 64:
            f["rs63_vs_spy"] = float(r63 - (sc.iloc[-1] / sc.iloc[-64] - 1.0) * 100.0)
    return f


# ---------------------------------------------------------------- model katmanı
def load_model(path=MODEL_PATH):
    """Eğitilmiş XGBoost sınıflandırıcı; henüz yoksa None (gölge/veri-toplama modu)."""
    if not os.path.exists(path):
        return None
    from xgboost import XGBClassifier
    m = XGBClassifier()
    m.load_model(path)
    return m

def score_candidates(model, rows):
    """rows[i]['p_false'] = P(sahte kırılım); 'conf' = 1−p (ML güven skoru)."""
    if model is None or not rows:
        return rows
    X = pd.DataFrame([r["features"] for r in rows])[FEATURES].astype(float)
    p = model.predict_proba(X)[:, 1]
    for r, pi in zip(rows, p):
        r["p_false"] = float(pi)
        r["conf"] = 1.0 - float(pi)
    return rows


# ---------------------------------------------------------------- gölge günlüğü
LOG_COLS = ["asof", "symbol", "entry", "stop", "target", "taken"] + FEATURES + ["src", "label"]

def _read_log():
    if not os.path.exists(SHADOW_LOG):
        return []
    with open(SHADOW_LOG, newline="") as fh:
        return list(csv.DictReader(fh))

def _write_log(recs):
    os.makedirs(ML_DIR, exist_ok=True)
    tmp = SHADOW_LOG + ".tmp"
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLS)
        w.writeheader()
        w.writerows(recs)
    os.replace(tmp, SHADOW_LOG)

def append_shadow_log(rows, asof):
    """Bugünün adaylarını eğitim günlüğüne ekle (aynı gün+sembol bir kez)."""
    recs = _read_log()
    seen = {(r["asof"], r["symbol"]) for r in recs}
    n = 0
    for r in rows:
        key = (asof, r["symbol"])
        if key in seen:
            continue
        # canlı buyable listesi = o gün fiilen AÇILAN pozisyonlar (r["opened"]) → taken=1
        rec = {"asof": asof, "symbol": r["symbol"],
               "entry": r["cand"].get("entry"), "stop": r["cand"].get("stop"),
               "target": r["cand"].get("partial_target"),
               "taken": 1, "src": "live", "label": ""}
        rec.update({k: (round(v, 4) if v == v else "") for k, v in r["features"].items()})
        recs.append(rec); n += 1
    if n:
        _write_log(recs)
    return n, recs

def label_pending(frames, recs=None):
    """Etiketi boş geçmiş satırları ileri-bakışla doldur (stop-first=sahte, hedef-first=gerçek)."""
    recs = _read_log() if recs is None else recs
    n = 0
    for rec in recs:
        if rec["label"] != "" or not rec.get("entry"):
            continue
        df = frames.get(rec["symbol"])
        if df is None:
            continue
        fwd = df[df.index > rec["asof"]].head(HORIZON)
        if fwd.empty:
            continue
        entry, stop, target = (float(rec["entry"]), float(rec["stop"] or 0), float(rec["target"] or 0))
        lab = None
        for _, bar in fwd.iterrows():
            hit_stop = stop and bar["Low"] <= stop
            hit_tgt  = target and bar["High"] >= target
            if hit_stop:            # aynı barda ikisi de → muhafazakâr: sahte
                lab = 1; break
            if hit_tgt:
                lab = 0; break
        if lab is None:
            if len(fwd) < HORIZON:  # pencere henüz dolmadı — bekle
                continue
            lab = 1 if fwd["Close"].iloc[-1] < entry else 0
        rec["label"] = lab; n += 1
    if n:
        _write_log(recs)
    return n, recs


def train_from_log(out=MODEL_PATH):
    """Etiketli gölge günlüğünden modeli eğit (yeterli veri birikince)."""
    recs = [r for r in _read_log() if r["label"] != ""]
    if len(recs) < MIN_TRAIN_ROWS:
        print(f"eğitim atlandı: {len(recs)} etiketli satır < {MIN_TRAIN_ROWS}")
        return None
    df = pd.DataFrame(recs)
    X = df[FEATURES].apply(pd.to_numeric, errors="coerce")
    y = df["label"].astype(int)
    from xgboost import XGBClassifier
    m = XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.05,
                      subsample=0.8, colsample_bytree=0.8, eval_metric="logloss")
    m.fit(X, y)
    os.makedirs(ML_DIR, exist_ok=True)
    m.save_model(out)
    print(f"model kaydedildi: {out}  ({len(recs)} satır, sahte oranı {y.mean():.2f})")
    return m


# ---------------------------------------------------------------- HTML raporu
def _fmt(v, nd=2, suf=""):
    if v is None or v != v:
        return "<span class='mut'>—</span>"
    return f"{v:.{nd}f}{suf}"

def render_html(rows, meta, model_ok, log_total, log_labeled, out=OUT_HTML):
    asof = meta.get("asof", "?"); ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    if model_ok:
        rows = sorted(rows, key=lambda r: r.get("conf", 0), reverse=True)
        banner = ""
    else:
        banner = ("<blockquote><b>Model henüz eğitilmedi — gölge/veri-toplama modu.</b> "
                  "Rapor her tarama sonrası aday özelliklerini günlüğe yazar; kırılımlar "
                  f"{HORIZON} iş günü içinde otomatik etiketlenir. {MIN_TRAIN_ROWS}+ etiketli satır "
                  "birikince <code>python3 ml_shadow_report.py --train</code> ile model kurulur, "
                  "skor sütunu o gün dolmaya başlar.</blockquote>")

    trs = []
    for r in rows:
        f = r["features"]; c = r.get("conf")
        bar = ""
        if c is not None:
            col = "var(--grn)" if c >= 0.6 else ("var(--amb)" if c >= 0.4 else "var(--red)")
            bar = (f"<div style='background:#1c2128;border-radius:4px;height:10px;min-width:90px'>"
                   f"<div style='width:{c*100:.0f}%;height:10px;border-radius:4px;background:{col}'></div></div>"
                   f"<span style='font-variant-numeric:tabular-nums'>{c*100:.0f}%</span>")
            bar = f"<div style='display:flex;gap:8px;align-items:center'>{bar}</div>"
        else:
            bar = "<span class='mut'>—</span>"
        trs.append(
            "<tr><td><b>{sym}</b>{tk}</td><td>{bar}</td><td>{pf}</td><td>{vr}</td><td>{ap}</td>"
            "<td>{rs}</td><td>{bm}</td><td>{rp}</td><td>{r5}</td><td>{rss}</td><td>{rk}</td></tr>".format(
                sym=html.escape(r["symbol"]), tk="",
                bar=bar, pf=_fmt(r.get("p_false"), 2),
                vr=_fmt(f.get("vol_ratio"), 2, "×"), ap=_fmt(f.get("atr_pct"), 1, "%"),
                rs=_fmt(f.get("rs63_vs_spy"), 1), bm=_fmt(f.get("brk_margin_pct"), 2, "%"),
                rp=_fmt(f.get("range_pos"), 2), r5=_fmt(f.get("ret5_pct"), 1, "%"),
                rss=_fmt(f.get("rs_scan"), 1), rk=_fmt(f.get("risk_pct"), 1, "%")))
    tbody = "\n".join(trs) or "<tr><td colspan='11' class='mut'>Bu taramada kırılım adayı yok.</td></tr>"

    model_line = ""
    if os.path.exists(META_PATH):
        try:
            mt = json.load(open(META_PATH))
            aucs = [f["auc"] for f in mt.get("folds", []) if f.get("auc") is not None]
            avg = f" · walk-forward AUC ort. <b>{sum(aucs)/len(aucs):.3f}</b> ({len(aucs)} pencere)" if aucs else ""
            warn = ""
            if aucs and sum(aucs) / len(aucs) < 0.55:
                warn = ("<blockquote>⚠️ <b>Kestirim gücü walk-forward'da ŞANS SEVİYESİNDE (AUC≈0.5).</b> "
                        "Skorlar deneysel/gölge amaçlıdır — alım-satım kararında KULLANMA. "
                        "Etiket ve özellik varyantları da denendi, hiçbiri geçmedi (model_meta.json).</blockquote>")
            model_line = (f"<div class='card'><b>Model karnesi</b> <span class='mut'>eğitim: {mt.get('trained_at','?')} · "
                          f"{mt.get('n_labeled','?')} etiketli örnek ({mt.get('src_note','')}) · "
                          f"taban sahte-oranı %{mt.get('base_rate',0)*100:.0f}{avg}. "
                          f"Doğrulama purged walk-forward (geleceğe bakmadan); ayrıntı <code>~/.swing_ml/model_meta.json</code>.</span></div>{warn}")
        except Exception:
            pass

    legend = "".join(f"<li><b>{FEATURE_TR[k][0]}</b> — {FEATURE_TR[k][1]}</li>" for k in FEATURES)
    page = f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🤖 ML Sahte Kırılım Analizi — Gölge Modu</title>
<style>
 :root{{--bg:#0d1117;--card:#161b22;--bd:#30363d;--fg:#e6edf3;--mut:#8b949e;--grn:#3fb950;--red:#f85149;--blu:#58a6ff;--amb:#d29922}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 system-ui,'Segoe UI',sans-serif}}
 .wrap{{max-width:1060px;margin:0 auto;padding:18px 20px 60px}}
 h1{{font-size:22px;margin:14px 0 4px}} .mut{{color:var(--mut)}} a{{color:var(--blu)}} .back{{font-size:13px}}
 .card{{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px 16px;margin:12px 0}}
 table{{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}}
 th,td{{border:1px solid var(--bd);padding:5px 8px;text-align:right;font-variant-numeric:tabular-nums}}
 th{{background:#1c2128;font-weight:600}} td:first-child,th:first-child{{text-align:left}}
 td:nth-child(2),th:nth-child(2){{text-align:left;min-width:150px}}
 .tblwrap{{overflow-x:auto}} ul{{margin:6px 0 6px 20px;padding:0}} li{{margin:5px 0}}
 blockquote{{border-left:3px solid var(--amb);margin:10px 0;padding:4px 14px;color:#d8c690;background:#1a1f17;border-radius:0 8px 8px 0}}
 code{{background:#1c2128;padding:1px 5px;border-radius:4px;font-size:12.5px}}
</style></head><body><div class="wrap">
<p class="back"><a href="/adaylar">← Adaylar</a> · <a href="/">Seans Masası</a> · <a href="/ml-rapor">📜 ML seferi — ne öğrendik? (basit anlatım)</a></p>
<h1>🤖 ML Sahte Kırılım Analizi <span class="mut" style="font-size:14px">gölge modu</span></h1>
<p class="mut">Tarama: <b>{html.escape(str(asof))}</b> · rapor üretimi: {ts} ·
rejim: {"🟢 alım açık" if meta.get("regime_open") else "🔴 fren devrede"} ·
<b>salt-okur</b> — canlı kararları ETKİLEMEZ.</p>
{banner}
<div class="card"><b>Nasıl okunur?</b> <span class="mut">ML güven = modelin "bu kırılım GERÇEK"
deme olasılığı (1 − P(sahte)). Yüksekten düşüğe sıralı. Listelenen semboller = bugünkü taramada
fiilen açılan pozisyonlar. Özellik sütunları modelin girdileri — kararın "neden"i.</span></div>
{model_line}
<div class="tblwrap"><table>
<tr><th>Sembol</th><th>ML güven</th><th>P(sahte)</th><th>Hacim oranı</th><th>ATR %</th>
<th>RS-63 vs SPY</th><th>Kırılım payı</th><th>Kapanış gücü</th><th>5g mom.</th><th>Tarayıcı RS</th><th>Risk %</th></tr>
{tbody}
</table></div>
<div class="card"><b>Özellik sözlüğü</b><ul>{legend}</ul></div>
<p class="mut" style="font-size:12.5px">Gölge günlüğü: {log_total} aday-gün kayıtlı,
{log_labeled} etiketli (eğitim eşiği {MIN_TRAIN_ROWS}). Model dosyası:
{"<code>~/.swing_ml/xgb_false_breakout.json</code> yüklü ✓" if model_ok else "yok — veri birikiyor"}.
Üretici: <code>ml_shadow_report.py</code> (cron, taramadan 10 dk sonra).</p>
</div></body></html>"""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(page)
    os.replace(tmp, out)
    return out


# ---------------------------------------------------------------- ana akış
def main():
    ap = argparse.ArgumentParser(description="ML gölge-mod sahte-kırılım raporu")
    ap.add_argument("--train", action="store_true", help="gölge günlüğünden modeli eğit")
    ap.add_argument("--out", default=OUT_HTML)
    args = ap.parse_args()

    if args.train:
        train_from_log()
        return

    cands, meta = load_candidates()
    asof = meta.get("asof", "")
    frames = load_frames()

    rows = [{"symbol": c["symbol"], "cand": c,
             "features": build_features(c, frames, asof)} for c in cands]

    n_new, _ = append_shadow_log(rows, asof)
    n_lab, recs = label_pending(frames)
    log_labeled = sum(1 for r in recs if r["label"] != "")

    model = load_model()
    rows = score_candidates(model, rows)

    out = render_html(rows, meta, model is not None, len(recs), log_labeled, out=args.out)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] adaylar-ml: {len(rows)} aday · "
          f"günlük +{n_new} yeni / +{n_lab} etiket ({log_labeled}/{len(recs)} etiketli) · "
          f"model={'VAR' if model else 'yok'} → {out}")


if __name__ == "__main__":
    main()

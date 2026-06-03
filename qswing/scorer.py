# -*- coding: utf-8 -*-
"""qswing — Aşama 2 skoru, 5-kapı pre-flight çeklist, net duruş."""
from __future__ import annotations
from typing import Dict


def stage2_score(m: Dict) -> Dict:
    """0–5 puan; her kriter 1 puan."""
    crit = [
        ("price_above_sma200", "Fiyat > SMA200", m.get("price_above_sma200")),
        ("price_above_sma150", "Fiyat > SMA150", m.get("price_above_sma150")),
        ("sma150_above_sma200", "SMA150 > SMA200", m.get("sma150_above_sma200")),
        ("s200_slope_up", "SMA200 eğimi yukarı (20 bar)", m.get("s200_slope_up")),
        ("within_25pct_high", "52H zirvenin %25 içinde", m.get("within_25pct_high")),
    ]
    pts = sum(1 for _, _, ok in crit if ok)
    return {"score": pts, "max": 5,
            "criteria": [{"key": k, "label": lbl, "ok": bool(ok)} for k, lbl, ok in crit]}


def _g(status, detail):
    return {"status": status, "detail": detail}


def gates(m: Dict, spy_reg: Dict, qqq_reg: Dict, stage: Dict,
          spy_ok: bool = True, qqq_ok: bool = True) -> Dict:
    """5 kapı → her biri PASS / PARTIAL / FAIL."""
    out = {}

    # 1 · Piyasa rejimi
    if not spy_ok:
        out["regime"] = _g("FAIL", "SPY verisi alınamadı — rejim doğrulanamıyor.")
    elif not qqq_ok:
        # QQQ bu planda kapalı → yalnız SPY ile değerlendir
        if spy_reg["healthy"]:
            out["regime"] = _g("PASS", "SPY SMA50 & SMA200 üstünde — rejim açık (QQQ bu planda yok, SPY baz alındı).")
        elif spy_reg["above50"] or spy_reg["above200"]:
            out["regime"] = _g("PARTIAL", "SPY ortalamalardan birinin altında — temkinli (QQQ yok, SPY baz).")
        else:
            out["regime"] = _g("FAIL", "SPY ortalamaların altında — risk kapalı (QQQ yok, SPY baz).")
    else:
        spy_h, qqq_h = spy_reg["healthy"], qqq_reg["healthy"]
        spy_any = spy_reg["above50"] or spy_reg["above200"]
        qqq_any = qqq_reg["above50"] or qqq_reg["above200"]
        if spy_h and qqq_h:
            out["regime"] = _g("PASS", "SPY ve QQQ her ikisi de SMA50 & SMA200 üstünde — rüzgâr arkadan.")
        elif (spy_h or qqq_h) or (spy_any and qqq_any):
            out["regime"] = _g("PARTIAL", "Endekslerden biri zayıf — temkinli, pozisyon küçült.")
        else:
            out["regime"] = _g("FAIL", "SPY & QQQ ortalamaların altında — risk kapalı, yeni alım yok.")

    # 2 · Liderlik
    rs3 = m.get("rs_3m")
    rs3_pos = rs3 is not None and rs3 > 0
    rs50 = bool(m.get("rs_line_50d_high"))
    if rs3_pos and rs50:
        out["leadership"] = _g("PASS", "3a RS pozitif VE RS çizgisi 50-gün zirvesinde — gerçek lider.")
    elif rs3_pos or rs50:
        out["leadership"] = _g("PARTIAL", "Görece güç kısmi — lider adayı ama teyit eksik.")
    else:
        out["leadership"] = _g("FAIL", "Piyasanın gerisinde — liderlik yok.")

    # 3 · Aşama 2
    ss = stage["score"]
    if ss >= 4:
        out["stage2"] = _g("PASS", f"Aşama 2 skoru {ss}/5 — sağlam yükseliş trendi.")
    elif ss in (2, 3):
        out["stage2"] = _g("PARTIAL", f"Aşama 2 skoru {ss}/5 — trend oluşuyor, henüz olgun değil.")
    else:
        out["stage2"] = _g("FAIL", f"Aşama 2 skoru {ss}/5 — trend yok / aşama 1 veya 4.")

    # 4 · Sıkı kurulum
    vdu = m.get("vdu_ratio")
    r1 = m.get("ret_1m")
    tight = (vdu is not None and vdu <= 70) and (r1 is not None and r1 <= 15)
    loose = (vdu is not None and vdu <= 100) or (r1 is not None and r1 <= 20)
    if tight:
        out["tight"] = _g("PASS", "Hacim kurudu (VDU≤%70) ve 1a getiri ılımlı (≤%15) — sıkı kurulum.")
    elif loose:
        out["tight"] = _g("PARTIAL", "Kısmen sıkı — biraz daha sıkışma/dinlenme iyi olur.")
    else:
        out["tight"] = _g("FAIL", "Gevşek/uzamış — hacim yüksek veya fiyat çok hızlı koştu.")

    # 5 · Giriş & risk
    ss_ge4 = ss >= 4
    vdu_ok = vdu is not None and vdu <= 70
    if ss_ge4 and vdu_ok:
        out["entry"] = _g("PASS", "Aşama 2 güçlü + hacim kuru — net giriş & risk tanımlanabilir.")
    elif ss >= 3:
        out["entry"] = _g("PARTIAL", "Giriş şartları yaklaşıyor — kurulum tetikleyince netleşir.")
    else:
        out["entry"] = _g("FAIL", "Giriş için erken — önce trend/sıkışma gerek.")

    return out


def verdict(gates_d: Dict) -> Dict:
    """Genel net duruş."""
    vals = list(gates_d.values())
    n_pass = sum(1 for g in vals if g["status"] == "PASS")
    regime = gates_d.get("regime", {}).get("status")
    others_pass = sum(1 for k, g in gates_d.items()
                      if k != "regime" and g["status"] == "PASS")

    if n_pass == 5:
        return {"label": "AL", "color": "green", "emoji": "🟢",
                "text": "Beş kapının beşi de geçti — Qullamaggie tarzı kurulum hazır. "
                        "Tanımlı riskle giriş tetiklenebilir."}
    if regime == "FAIL":
        return {"label": "KAÇIN", "color": "red", "emoji": "🔴",
                "text": "Piyasa rejimi kapalı (Kapı 1 kaldı) — momentum stratejisinde "
                        "yeni alım yok; en iyi kurulumlar bile bu ortamda başarısız olur."}
    if regime == "PASS" and others_pass >= 3:
        return {"label": "İZLE", "color": "amber", "emoji": "🟡",
                "text": "Rejim açık ve çoğu kapı geçti — gelişen bir lider. Henüz tam "
                        "tetik yok; sıkışma/kırılım için izleme listesine al."}
    return {"label": "İZLE", "color": "amber", "emoji": "🟡",
            "text": "Karışık sinyal — bazı kapılar geçti, bazıları eksik. İzle, "
                    "kurulum olgunlaşınca yeniden değerlendir."}

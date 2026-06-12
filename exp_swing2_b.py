# -*- coding: utf-8 -*-
"""FAZ B — CANLI baz (qswing 40g kırılım girişi + şampiyon ATR-trail çıkış) etrafında
test edilmemiş boyutlar. exp_swing2.py 'phaseB' bunu import eder."""

Q = {"entry_mode": "qswing_breakout"}   # lb=40, vdu=9 (kapalı), rs_min=0 = Config varsayılanı = canlı

def q(**kw):
    d = dict(Q); d.update(kw); return d

PHASE_B = [
    ("qbase_live", q()),
    # 1) Pozisyon genişliği
    ("q_breadth_3x33", q(max_positions=3, max_position_pct=0.33)),
    ("q_breadth_7x14", q(max_positions=7, max_position_pct=0.14)),
    ("q_breadth_8x125", q(max_positions=8, max_position_pct=0.125)),
    ("q_breadth_10x10", q(max_positions=10, max_position_pct=0.10)),
    # 2) qswing giriş eşikleri
    ("q_score_50", q(qswing_min_score=50.0)),
    ("q_score_60", q(qswing_min_score=60.0)),
    ("q_score_70", q(qswing_min_score=70.0)),
    ("q_rs_5", q(qswing_rs_min=5.0)),
    ("q_rs_10", q(qswing_rs_min=10.0)),
    ("q_nearhigh_85", q(qswing_near_high=0.85)),
    ("q_nearhigh_90", q(qswing_near_high=0.90)),
    # 3) Kırılım lookback (10/20/40 tarandı; 40 kazandı → yukarısı denenmedi)
    ("q_lb_30", q(qswing_breakout_lb=30)),
    ("q_lb_50", q(qswing_breakout_lb=50)),
    ("q_lb_60", q(qswing_breakout_lb=60)),
    # 4) SPY oynaklık kilidi (DD küçültme adayı)
    ("q_regime_1.5", q(regime_atr_filter=True, regime_atr_threshold=1.5)),
    ("q_regime_1.8", q(regime_atr_filter=True, regime_atr_threshold=1.8)),
    ("q_regime_2.2", q(regime_atr_filter=True, regime_atr_threshold=2.2)),
    # 5) Risk-bazlı boyutlama
    ("q_risk_1.0", q(sizing_mode="risk", risk_per_trade_pct=1.0)),
    ("q_risk_1.5", q(sizing_mode="risk", risk_per_trade_pct=1.5)),
    ("q_risk_2.0", q(sizing_mode="risk", risk_per_trade_pct=2.0)),
    # 6) Çıkış: trail çarpanı + devreye girme (qswing girişiyle hiç taranmadı)
    ("q_trail_2.0", q(atr_trail_mult=2.0)),
    ("q_trail_3.0", q(atr_trail_mult=3.0)),
    ("q_trail_after_0.5", q(trail_after_r=0.5)),
    ("q_trail_after_1.5", q(trail_after_r=1.5)),
    # 7) Stop genişliği
    ("q_stop_1.2", q(atr_stop_mult=1.2)),
    ("q_stop_2.0", q(atr_stop_mult=2.0)),
    # 8) Partial / hedef
    ("q_p20_rr30", q(partial_rr=2.0, rr_target=3.0)),
    ("q_p20_rr40", q(partial_rr=2.0, rr_target=4.0)),
    ("q_runner_no_target", q(rr_target=99.0, partial_rr=2.0)),
    ("q_partial_33", q(partial_pct=0.33)),
    ("q_partial_67", q(partial_pct=0.67)),
    # 9) Saf ATR-trail (partial/hedef yok)
    ("q_atr_full_2.5", q(exit_mode="atr_full", atr_trail_mult=2.5)),
    ("q_atr_full_3.0", q(exit_mode="atr_full", atr_trail_mult=3.0)),
]
# NOT: max_dist_sma20 chase kapısı motorda yalnız swing2 giriş dalında uygulanıyor —
# qswing dalında no-op olacağından Faz B'den çıkarıldı.

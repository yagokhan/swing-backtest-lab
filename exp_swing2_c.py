# -*- coding: utf-8 -*-
"""FAZ C — kazanan (qswing giriş + atr_full şamdan trail) etrafında ince ayar,
genişlik kombinasyonları ve slippage stres testi."""

Q = {"entry_mode": "qswing_breakout"}

def q(**kw):
    d = dict(Q); d.update(kw); return d

def af(mult=3.0, **kw):
    return q(exit_mode="atr_full", atr_trail_mult=mult, **kw)

PHASE_C = [
    # referanslar (aynı koşu ortamında tekrar)
    ("c_qbase", q()),
    ("c_af30", af(3.0)),
    # 1) trail çarpanı ince ayar
    ("c_af275", af(2.75)),
    ("c_af325", af(3.25)),
    ("c_af35", af(3.5)),
    ("c_af40", af(4.0)),
    # 2) genişlik × af3.0
    ("c_af30_3x33", af(3.0, max_positions=3, max_position_pct=0.33)),
    ("c_af30_4x25", af(3.0, max_positions=4, max_position_pct=0.25)),
    ("c_af30_7x14", af(3.0, max_positions=7, max_position_pct=0.14)),
    ("c_af30_10x10", af(3.0, max_positions=10, max_position_pct=0.10)),
    # 3) giriş ince ayarı × af3.0
    ("c_af30_lb63", af(3.0, qswing_breakout_lb=63)),
    ("c_af30_nh85", af(3.0, qswing_near_high=0.85)),
    ("c_af30_nh85_3x33", af(3.0, qswing_near_high=0.85, max_positions=3, max_position_pct=0.33)),
    # 4) rejim kilidi × af3.0 (W1 zaten pozitif — kontrol)
    ("c_af30_regime22", af(3.0, regime_atr_filter=True, regime_atr_threshold=2.2)),
    # 5) optimized-mod 'koşucu' alternatifleri (af'a rakip)
    ("c_opt_rr40_t30_ta15", q(rr_target=4.0, partial_rr=2.0, atr_trail_mult=3.0, trail_after_r=1.5)),
    ("c_opt_rr99_t30_ta15", q(rr_target=99.0, partial_rr=2.0, atr_trail_mult=3.0, trail_after_r=1.5)),
    # 6) SLIPPAGE STRES (gerçekçilik tamponu): giriş 8→16bps, stop 15→30bps, limit 5→10bps
    ("c_af30_STRESS", af(3.0, entry_slippage_bps=16.0, stop_slippage_bps=30.0, slippage_bps=10.0)),
    ("c_qbase_STRESS", q(entry_slippage_bps=16.0, stop_slippage_bps=30.0, slippage_bps=10.0)),
]

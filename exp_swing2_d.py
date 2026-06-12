# -*- coding: utf-8 -*-
"""FAZ D — finalist çapraz kombinasyonları + stres testleri."""

Q = {"entry_mode": "qswing_breakout"}

def af(mult=3.0, **kw):
    d = dict(Q); d.update(exit_mode="atr_full", atr_trail_mult=mult); d.update(kw); return d

STRESS = dict(entry_slippage_bps=16.0, stop_slippage_bps=30.0, slippage_bps=10.0)

PHASE_D = [
    ("d_af325", af(3.25)),                                     # referans
    ("d_af325_lb63", af(3.25, qswing_breakout_lb=63)),
    ("d_af325_7x14", af(3.25, max_positions=7, max_position_pct=0.14)),
    ("d_af325_lb63_7x14", af(3.25, qswing_breakout_lb=63, max_positions=7, max_position_pct=0.14)),
    ("d_af30_lb63_7x14", af(3.0, qswing_breakout_lb=63, max_positions=7, max_position_pct=0.14)),
    ("d_af325_nh85", af(3.25, qswing_near_high=0.85)),
    ("d_af35_lb63", af(3.5, qswing_breakout_lb=63)),
    # stres (2× slippage) — finalistler
    ("d_af325_STRESS", af(3.25, **STRESS)),
    ("d_af325_lb63_STRESS", af(3.25, qswing_breakout_lb=63, **STRESS)),
    ("d_af30_lb63_STRESS", af(3.0, qswing_breakout_lb=63, **STRESS)),
    ("d_af325_7x14_STRESS", af(3.25, max_positions=7, max_position_pct=0.14, **STRESS)),
]

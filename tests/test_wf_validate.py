# tests/test_wf_validate.py
import pytest
import wf_validate as wf

def test_assert_no_leakage_rejects_overlap():
    with pytest.raises(ValueError):
        wf.assert_no_leakage("2023-12-31", "2023-06-01")   # oos starts before IS ends

def test_assert_no_leakage_accepts_clean_split():
    wf.assert_no_leakage("2023-12-31", "2024-01-01")        # no raise

def test_champion_cfg_locks_params():
    c = wf.champion_cfg(("AAA", "BBB"), use_rs=True)
    assert c.entry_mode == "qswing_breakout"
    assert c.qswing_breakout_lb == 63
    assert c.exit_mode == "atr_full"
    assert c.atr_trail_mult == 3.25
    assert c.max_positions == 20 and c.max_position_pct == 0.05
    assert c.initial_capital == 20000 and c.compounding is True
    assert c.use_rs_universe is True

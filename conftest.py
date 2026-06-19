import os
import sys

# Pin THIS worktree on sys.path and import the local swing2_backtest first, so it
# is cached in sys.modules before test_glitch_guard.py inserts /home/gokhan (which
# holds an older production copy that would otherwise shadow this branch's changes).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swing2_backtest  # noqa: F401,E402  -- side effect: cache the worktree copy

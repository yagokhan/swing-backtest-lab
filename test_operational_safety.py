#!/usr/bin/env python3
"""Qulla-21 canlı yoluna eklenen operasyonel korumaların birim testleri."""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace

import live_scan_telegram as live
import pandas as pd
import qulla_paper as qp
import telegram_command_bot as cmdbot


class GlitchGateTests(unittest.TestCase):
    def test_qulla_gate_catches_scale_error(self):
        candidates = [
            {"symbol": "KLAC", "entry": 9300.0},
            {"symbol": "AMD", "entry": 175.0},
        ]
        bad = live._qulla_price_glitches(
            candidates, {"KLAC": 930.0, "AMD": 174.0})
        self.assertEqual([x[0] for x in bad], ["KLAC"])

    def test_missing_quote_does_not_invent_a_mismatch(self):
        self.assertEqual(
            live._qulla_price_glitches([{"symbol": "AMD", "entry": 175.0}], {}),
            [])

    def test_replay_exit_scale_error_is_also_caught(self):
        trade = SimpleNamespace(symbol="ENPH", exit=900.0)
        qr = {
            "asof": "2026-07-23", "positions": [], "opened": [],
            "exited": [trade], "closed_all": [trade],
            "market": {"data": {
                "ENPH": pd.DataFrame(
                    {"Close": [90.0]}, index=[pd.Timestamp("2026-07-23")])
            }},
        }
        previous = {"positions": [{"symbol": "ENPH"}], "trades": []}
        rows, critical, symbols = live._qulla_validation_rows(qr, previous)
        bad, missing, missing_rows = live._qulla_validation_issues(
            rows, critical, {"ENPH": 90.0})
        self.assertEqual(critical, ["ENPH"])
        self.assertEqual(symbols, ["ENPH"])
        self.assertEqual(missing, [])
        self.assertEqual(missing_rows, [])
        self.assertEqual([x[0] for x in bad], ["ENPH"])

    def test_changed_symbol_without_quote_blocks_validation(self):
        bad, missing, missing_rows = live._qulla_validation_issues(
            [{"symbol": "AMD", "close": 175.0}], ["AMD"], {})
        self.assertEqual(bad, [])
        self.assertEqual(missing, ["AMD"])
        self.assertEqual(missing_rows, [])

    def test_missing_daily_row_also_blocks_validation(self):
        bad, missing, missing_rows = live._qulla_validation_issues(
            [], ["AMD"], {"AMD": 175.0})
        self.assertEqual(bad, [])
        self.assertEqual(missing, [])
        self.assertEqual(missing_rows, ["AMD"])


class SecretRedactionTests(unittest.TestCase):
    def test_telegram_token_and_fmp_key_are_removed_from_errors(self):
        token = "123456:VERY_SECRET_TOKEN"
        err = (f"HTTPSConnectionPool(host='api.telegram.org'): "
               f"https://api.telegram.org/bot{token}/getUpdates?"
               "apikey=ALSO_SECRET")
        for clean in (cmdbot._safe_error(err, token), live._safe_error(err)):
            self.assertNotIn(token, clean)
            self.assertNotIn("ALSO_SECRET", clean)
            self.assertIn("<REDACTED>", clean)


class LedgerCommitTests(unittest.TestCase):
    @staticmethod
    def _ledger(day, cash):
        return {
            "start": "2026-01-01", "initial": 10000.0, "last_date": day,
            "cash": cash, "positions": [], "trades": [],
            "equity_curve": [[day, cash]],
        }

    def test_commit_is_atomic_and_backs_up_previous_day(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ledger.json")
            old = self._ledger("2026-07-22", 10000.0)
            new = self._ledger("2026-07-23", 10025.0)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(old, fh)

            qp.commit_ledger({"_ledger": new, "_ledger_path": path})

            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), new)
            with open(path + ".bak.2026-07-22", encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), old)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_invalid_existing_ledger_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ledger.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{bozuk")
            with self.assertRaisesRegex(RuntimeError, "üzerine yazma reddedildi"):
                qp.commit_ledger({
                    "_ledger": self._ledger("2026-07-23", 10000.0),
                    "_ledger_path": path,
                })
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "{bozuk")

    def test_missing_main_ledger_with_backup_refuses_bootstrap(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ledger.json")
            with open(path + ".bak.2026-07-22", "w", encoding="utf-8") as fh:
                json.dump(self._ledger("2026-07-22", 10000.0), fh)
            with self.assertRaisesRegex(RuntimeError, "yeniden-bootstrap reddedildi"):
                qp.load_ledger(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)

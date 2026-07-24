# -*- coding: utf-8 -*-
"""live_scan_telegram._filter_glitches için birim test — veri-glitch çapraz kontrolü.
Senaryo: 2026-06-11 KLAC olayı (bulk veri hattı 10×, bağımsız quote gerçek)."""
import live_scan_telegram as L


def test_glitch_dropped_normal_kept():
    buyable = [
        {"symbol": "AAPL", "close": 240.0},   # quote ile uyumlu → KALIR
        {"symbol": "KLAC", "close": 2411.64},  # quote 256 → 9.4× → DÜŞER
        {"symbol": "MSFT", "close": 410.0},   # %3 sapma (gün-içi) → KALIR
    ]
    quotes = {"AAPL": 241.0, "KLAC": 256.42, "MSFT": 398.0}
    clean, dropped = L._filter_glitches(buyable, quotes, tol=0.25)
    names = {c["symbol"] for c in clean}
    assert names == {"AAPL", "MSFT"}, f"temiz liste yanlış: {names}"
    assert [d[0] for d in dropped] == ["KLAC"], f"düşen yanlış: {dropped}"
    print("✓ glitch (KLAC 9.4×) düşürüldü; AAPL/MSFT (uyumlu) korundu")


def test_missing_quote_keeps_candidate():
    # quote yoksa (referans yok) → muhafazakâr: KORU (yanlış pozitif yok)
    buyable = [{"symbol": "XYZ", "close": 100.0}]
    clean, dropped = L._filter_glitches(buyable, {}, tol=0.25)
    assert len(clean) == 1 and not dropped, "referanssız aday korunmalı"
    print("✓ referanssız aday korundu (yanlış pozitif yok)")


def test_empty_safe():
    clean, dropped = L._filter_glitches([], {"A": 1.0}, tol=0.25)
    assert clean == [] and dropped == []
    print("✓ boş liste güvenli")


if __name__ == "__main__":
    test_glitch_dropped_normal_kept()
    test_missing_quote_keeps_candidate()
    test_empty_safe()
    print("\nTÜM TESTLER GEÇTİ")

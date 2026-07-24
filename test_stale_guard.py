#!/usr/bin/env python3
"""live_scan_telegram bayat-bar kapısı testleri (FMP/Telegram'a gitmez).

Kapsanan davranış (2026-07-14 olayı):
  FMP bugünün barını 15:45 ET'de vermedi → script sessizce atladı → kullanıcı
  bozuk botla veri gecikmesini ayırt edemedi. Artık: pencere içinde TEKRAR DENE,
  hâlâ yoksa Telegram'dan UYAR. Tatil günü ise (bar hiç gelmeyecek) sessiz kal.

Çalıştır: python3 test_stale_guard.py
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import live_scan_telegram as L

ET = ZoneInfo("America/New_York")
FAILS = []


def check(name, cond, detail=""):
    (print(f"  ✓ {name}") if cond else
     (FAILS.append(name), print(f"  ✗ {name} — {detail}")))


def et(h, m, day=14):
    return datetime(2026, 7, day, h, m, tzinfo=ET)


# ── 1. Tatil ayrımı: bar hiç gelmeyecekse uyarma ────────────────────────────
print("tatil ayrımı")
check("4 Temmuz tatili (2026-07-03) tatil sayılır", L._is_market_holiday("2026-07-03"))
check("Şükran Günü (2026-11-26) tatil sayılır", L._is_market_holiday("2026-11-26"))
check("normal Salı (2026-07-14) tatil DEĞİL", not L._is_market_holiday("2026-07-14"))


# ── 1b. Karar tablosu: alarm YALNIZ gerçek gecikmede çalsın ─────────────────
print("\nkarar tablosu (asof ilerlemedi)")
check("bugün zaten yayınlandı → sessiz no-op (BOŞ ALARM YOK)",
      L._stale_action("2026-07-14", "2026-07-14") == "yayınlandı",
      L._stale_action("2026-07-14", "2026-07-14"))
check("tatil → sessiz",
      L._stale_action("2026-07-02", "2026-07-03") == "tatil")
check("bar gelmeliydi ama yok → gecikme (tekrar dene + uyar)",
      L._stale_action("2026-07-13", "2026-07-14") == "gecikme")


# ── 2. Tekrar deneme: bar gecikmeli gelirse yakala ──────────────────────────
print("\ntekrar deneme")


def runner_factory(succeed_on, asof_new="2026-07-14"):
    """N'inci denemede yeni barı döndüren sahte tarayıcı."""
    calls = {"n": 0}

    def runner(_asof):
        calls["n"] += 1
        stale = calls["n"] < succeed_on
        return {"asof": "2026-07-13" if stale else asof_new}
    return runner, calls


runner, calls = runner_factory(succeed_on=3)
slept = []
qr, asof, tried = L._wait_for_new_bar(
    "2026-07-13", runner=runner, now_et=lambda: et(15, 48),
    sleeper=slept.append, attempts=4, wait_s=120)
check("3. denemede gelen barı yakalar", qr is not None and asof == "2026-07-14",
      f"qr={qr} asof={asof}")
check("gereksiz deneme yapmaz (3 çağrı)", calls["n"] == 3, f"çağrı={calls['n']}")
check("denemeler arası bekler", slept == [120, 120, 120], f"uyku={slept}")

# hiç gelmezse → None (çağıran uyarır)
runner, calls = runner_factory(succeed_on=99)
qr, asof, tried = L._wait_for_new_bar(
    "2026-07-13", runner=runner, now_et=lambda: et(15, 48),
    sleeper=lambda s: None, attempts=4, wait_s=120)
check("bar hiç gelmezse None döner", qr is None, f"qr={qr}")
check("tüm denemeleri tüketir (4)", tried == 4 and calls["n"] == 4, f"tried={tried}")


# ── 3. Son tarih (deadline): kapanıştan çok sonra giriş yapma ───────────────
print("\nson tarih koruması")
runner, calls = runner_factory(succeed_on=99)
clock = {"t": et(16, 18)}


def now_walking():
    t = clock["t"]
    clock["t"] = et(t.hour, t.minute + 3) if t.minute + 3 < 60 else et(t.hour + 1, 0)
    return t


qr, asof, tried = L._wait_for_new_bar(
    "2026-07-13", runner=runner, now_et=now_walking,
    sleeper=lambda s: None, attempts=6, wait_s=120)
check("16:20 ET son tarihinde durur", tried == 1, f"tried={tried} (16:18'de 1, 16:21'de dur)")

qr, asof, tried = L._wait_for_new_bar(
    "2026-07-13", runner=runner, now_et=lambda: et(16, 30),
    sleeper=lambda s: None, attempts=6, wait_s=120)
check("son tarih geçtiyse hiç denemez", tried == 0 and calls["n"] == 1, f"tried={tried}")


# ── 4. Uyarı metni: sessizlik yerine ne olduğunu söyle ──────────────────────
print("\nuyarı metni")
txt = L._stale_alert_text("2026-07-13", 4, et(16, 21))
check("kilitli günü söyler", "2026-07-13" in txt, txt)
check("deneme sayısını söyler", "4 deneme" in txt, txt)
check("Telegram HTML'ini bozacak çıplak '<' yok",
      "<" not in txt.replace("<b>", "").replace("</b>", "")
                  .replace("<code>", "").replace("</code>", ""), txt)

# ── 5. Yayın yolu: _bcast modül düzeyine taşındı, imza bozulmadı mı? ────────
print("\nyayın yolu (_bcast)")
sent = []
dropped = []
L.pt.remove_subscriber = lambda c: dropped.append(c)


class _Resp:
    def __init__(self, ok):
        self._ok = ok

    def json(self):
        return ({"ok": True} if self._ok else
                {"ok": False, "error_code": 403, "description": "blocked"})


def fake_send(text, token=None, chat=None):
    sent.append((chat, text))
    return _Resp(chat != "999")          # 999 botu bloklamış abone


L._bcast(fake_send, "merhaba", token="T", chats=["owner", "999"])
check("her alıcıya gönderir", [c for c, _ in sent] == ["owner", "999"], f"{sent}")
check("bloklayan aboneyi düşürür", dropped == ["999"], f"{dropped}")

print("\n" + ("TÜM TESTLER GEÇTİ" if not FAILS else f"{len(FAILS)} TEST ÇÖKTÜ: {FAILS}"))
raise SystemExit(1 if FAILS else 0)

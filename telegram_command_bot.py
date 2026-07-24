#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram KOMUT botu (uzun-süreli daemon) — kağıt portföy sorguları.

Komutlar:
  /portfolio  → mesajın gönderildiği AN için anlık K/Z + pozisyon detayı (FMP /stable quote)
  /lastscan   → yapılan son 22:45 (15:45 ET) tarama mesajı
  /help       → komut listesi

getUpdates ile long-polling yapar; offset diske yazılır (yeniden başlatınca tekrar işlemez).
Gizli anahtarlar: ~/.portfolio_keys.json | env (TELEGRAM_BOT_TOKEN, FMP_API_KEY).

Çalıştırma:
  python3 telegram_command_bot.py
Arka plan (örnek):
  nohup python3 /home/gokhan/telegram_command_bot.py >> /home/gokhan/swing2_out/cmdbot.log 2>&1 &
"""
import os, sys, json, re, time
from datetime import datetime

import requests
import paper_trader as pt
import qulla_paper as qp

KEYS = os.path.expanduser("~/.portfolio_keys.json")
OFFSET_FILE = os.path.expanduser("~/.swing_cmdbot_offset")
TG = "https://api.telegram.org/bot{tok}/{method}"
POLL_TIMEOUT = 30   # saniye (long-poll)


def _safe_error(exc, token=None):
    """requests hatalarındaki URL'lerden bot/API anahtarlarını loglamadan ayıkla."""
    text = str(exc)
    if token:
        text = text.replace(str(token), "<REDACTED>")
    text = re.sub(r"(api\.telegram\.org/bot)[^/\s]+", r"\1<REDACTED>", text)
    text = re.sub(r"\b\d{7,12}:[A-Za-z0-9_-]{20,}\b", "<REDACTED>", text)
    text = re.sub(r"([?&]apikey=)[^&\s]+", r"\1<REDACTED>", text, flags=re.I)
    return text


def _secret(name):
    v = os.environ.get(name)
    if v:
        return v
    if os.path.exists(KEYS):
        try:
            return json.load(open(KEYS)).get(name)
        except Exception:
            return None
    return None


def _send(token, chat, text):
    try:
        r = requests.post(TG.format(tok=token, method="sendMessage"),
                          data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                                "disable_web_page_preview": "true"}, timeout=30)
        j = r.json()
        if not j.get("ok"):
            print(f"[send NON-OK] chat={chat} code={j.get('error_code')} "
                  f"desc={j.get('description')} len={len(text)}", file=sys.stderr)
            # HTML parse hatası ihtimaline karşı düz metin (parse_mode'suz) ile tekrar dene
            r2 = requests.post(TG.format(tok=token, method="sendMessage"),
                               data={"chat_id": chat, "text": text,
                                     "disable_web_page_preview": "true"}, timeout=30)
            if not r2.json().get("ok"):
                print(f"[send fallback de başarısız] chat={chat} {r2.text[:200]}", file=sys.stderr)
        return j.get("ok")
    except Exception as e:
        print(f"[send hata] chat={chat} {_safe_error(e, token)}", file=sys.stderr)
        return False


def _load_offset():
    try:
        return int(open(OFFSET_FILE).read().strip())
    except Exception:
        return None


def _save_offset(off):
    try:
        with open(OFFSET_FILE, "w") as fh:
            fh.write(str(off))
    except Exception:
        pass


HELP = ("<b>📓 Kağıt Portföy Botu</b>\n"
        "/portfolio — 👑 Qulla-21 anlık K/Z + açık pozisyon detayı\n"
        "/lastscan — son 22:45 tarama mesajı\n"
        "/abone — her akşam 22:45 tarama + portföy yayınına abone ol\n"
        "/iptal — yayın aboneliğini bitir\n"
        "/help — bu mesaj")


def handle(cmd, token, chat, fmp_key, chat_name=""):
    if cmd in ("/portfolio", "/p"):
        # 👑 Qulla-21 (TEK yöntem) — canlı cron'un yazdığı durum dosyasından
        st = pt.load_state(qp.PAPER_QULLA, variant="qulla")
        syms = sorted(pt.held_symbols(st))
        prices = pt.quote_fmp(syms, fmp_key) if (syms and fmp_key) else {}
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _send(token, chat, pt.portfolio_message(st, prices, now, tag="👑 Qulla-21"))
    elif cmd in ("/lastscan", "/ls"):
        ls = pt.load_last_scan()
        if not ls:
            _send(token, chat, "Henüz kayıtlı bir 22:45 taraması yok.")
        else:
            _send(token, chat, f"<i>🕒 Son tarama: {ls.get('ts','?')} (asof {ls.get('asof','?')})</i>\n\n"
                               + ls.get("text", ""))
    elif cmd in ("/subscribe", "/abone"):
        if pt.add_subscriber(chat, chat_name):
            _send(token, chat, "✅ Abone oldun — her akşam <b>22:45</b> (15:45 ET) tarama ve "
                               "portföy mesajları artık buraya da gelecek. Ayrılmak için /iptal.")
        else:
            _send(token, chat, "Zaten abonesin. Ayrılmak için /iptal.")
    elif cmd in ("/unsubscribe", "/iptal"):
        if pt.remove_subscriber(chat):
            _send(token, chat, "🛑 Abonelik bitti — 22:45 yayını artık gelmeyecek. "
                               "Tekrar başlatmak için /abone.")
        else:
            _send(token, chat, "Abone görünmüyorsun. Başlamak için /abone.")
    elif cmd == "/start":
        new = pt.add_subscriber(chat, chat_name)   # botu başlatan otomatik abone olur
        _send(token, chat, HELP + ("\n\n✅ <i>22:45 yayınına otomatik abone oldun (ayrılmak için /iptal).</i>" if new else ""))
    elif cmd == "/help":
        _send(token, chat, HELP)


def main():
    token = _secret("TELEGRAM_BOT_TOKEN")
    fmp_key = _secret("FMP_API_KEY")
    if not token:
        print("HATA: TELEGRAM_BOT_TOKEN yok.", file=sys.stderr); sys.exit(2)
    if not fmp_key:
        print("UYARI: FMP_API_KEY yok — /portfolio anlık fiyat alamaz.", file=sys.stderr)
    offset = _load_offset()
    print(f"Komut botu başladı · offset={offset} · /portfolio /lastscan /help dinleniyor ...", flush=True)
    while True:
        try:
            params = {"timeout": POLL_TIMEOUT}
            if offset is not None:
                params["offset"] = offset
            r = requests.get(TG.format(tok=token, method="getUpdates"),
                             params=params, timeout=POLL_TIMEOUT + 15)
            updates = r.json().get("result", [])
        except Exception as e:
            print(f"[getUpdates hata] {_safe_error(e, token)}", file=sys.stderr); time.sleep(5); continue
        for u in updates:
            offset = u["update_id"] + 1
            _save_offset(offset)
            msg = u.get("message") or u.get("channel_post") or {}
            text = (msg.get("text") or "").strip()
            chat_obj = msg.get("chat") or {}
            chat = chat_obj.get("id")
            if not text or chat is None:
                continue
            cmd = text.split()[0].split("@")[0].lower()   # '/portfolio@Bot params' → '/portfolio'
            known = cmd in ("/portfolio", "/p", "/lastscan", "/ls", "/help", "/start",
                            "/subscribe", "/abone", "/unsubscribe", "/iptal")
            print(f"[update] chat={chat} type={chat_obj.get('type')} "
                  f"text={text[:40]!r} cmd={cmd} known={known}", flush=True)
            name = chat_obj.get("title") or chat_obj.get("username") or chat_obj.get("first_name") or ""
            try:
                handle(cmd, token, chat, fmp_key, chat_name=name)
            except Exception as e:
                print(f"[handle hata] {cmd}: {_safe_error(e, token)}", file=sys.stderr)


if __name__ == "__main__":
    main()

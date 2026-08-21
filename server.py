#!/usr/bin/env python3
"""Swing Backtest Lab — minimal API + statik sunucu.

Uçlar (veri çekme + trade mantığı motorda; bu sunucu yalnız yönlendirir):
  POST /api/backtest            → swing2_backtest.run_backtest_api(params)
  POST /api/sarkac              → sarkac_lab.run_api(params)  (🔔 Sarkaç-14)
  GET  /api/qswing?ticker=X     → qswing tek-hisse HTML raporu
  GET  /api/qswing/scan?...     → qswing küme tarama (preset=swing2|swing2_mega|swing2_tech | tickers=A,B)
  GET  /                        → backtest.html (statik)

FMP anahtarı: env FMP_API_KEY · .env · ~/.portfolio_keys.json (FMP_API_KEY).
"""
import http.server
import json
import os
import sys
import urllib.parse

PORT = int(os.environ.get("PORT", "8053"))
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if DIRECTORY not in sys.path:
    sys.path.insert(0, DIRECTORY)


def _load_keys():
    """env > .env > ~/.portfolio_keys.json (mevcut env'i ezmez)."""
    envf = os.path.join(DIRECTORY, ".env")
    if os.path.exists(envf):
        try:
            for line in open(envf):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass
    kp = os.path.expanduser("~/.portfolio_keys.json")
    if os.path.exists(kp):
        try:
            for k, v in (json.load(open(kp)) or {}).items():
                if k and v and not os.environ.get(k):
                    os.environ[k] = str(v)
        except Exception:
            pass


_load_keys()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DIRECTORY, **kw)

    def end_headers(self):
        # Tarayıcı eski HTML/JS'i önbellekten çalıştırmasın diye no-cache.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.path = "/backtest.html"
            return super().do_GET()
        if self.path.startswith("/api/qswing/scan"):
            return self.handle_qswing_scan()
        if self.path.startswith("/api/qswing"):
            return self.handle_qswing()
        if self.path.startswith("/api/history/"):
            return self.handle_history()
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/backtest"):
            return self.handle_backtest()
        if self.path.startswith("/api/sarkac"):
            return self.handle_sarkac()
        self.send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ---- /api/backtest ----
    def handle_backtest(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n < 0 or n > 200_000:
                return self.send_json(400, {"error": "invalid body length"})
            body = self.rfile.read(n).decode("utf-8") if n else "{}"
            params = json.loads(body) if body.strip() else {}
        except Exception as e:
            return self.send_json(400, {"error": f"invalid JSON: {e}"})
        try:
            import swing2_backtest as s2
            self.send_json(200, s2.run_backtest_api(params))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_json(502, {"error": str(e)})

    # ---- /api/sarkac ----  🔔 Sarkaç-14: QQQ RSI salınımıyla TQQQ al-sat
    def handle_sarkac(self):
        """Qulla-21 ile AYNI yanıt sözleşmesi döner (config/metrics/equity/
        monthly/trades) — backtest.html'in render kodu ortak."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n < 0 or n > 200_000:
                return self.send_json(400, {"error": "invalid body length"})
            body = self.rfile.read(n).decode("utf-8") if n else "{}"
            params = json.loads(body) if body.strip() else {}
        except Exception as e:
            return self.send_json(400, {"error": f"invalid JSON: {e}"})
        try:
            import sarkac_lab
            self.send_json(200, sarkac_lab.run_api(params))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_json(502, {"error": str(e)})

    # ---- /api/qswing?ticker=X ----
    def handle_qswing(self):
        q = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
        ticker = (q.get("ticker", [""])[0] or "").upper().strip()
        date = q.get("date", [None])[0]
        if not ticker:
            return self.send_html(400, "<h3 style='font-family:sans-serif'>ticker gerekli (örn. /api/qswing?ticker=NNE)</h3>")
        try:
            import qswing.main as qm
            self.send_html(200, qm.generate_report_html(ticker, asof=date))
        except Exception as e:
            msg = str(e)
            hint = (f"'{ticker}' bu FMP planında kapalı (HTTP 402)." if "402" in msg
                    else f"'{ticker}' bulunamadı — sembol geçersiz olabilir." if "Bo" in msg
                    else msg)
            self.send_html(502, f"<div style='font-family:sans-serif;color:#ff5d6c;background:#0d1218;padding:24px'>"
                                f"<h3>qswing hata · {ticker}</h3><p>{hint}</p></div>")

    # ---- /api/qswing/scan ----
    def handle_qswing_scan(self):
        q = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
        date = q.get("date", [None])[0]
        preset = (q.get("preset", [""])[0] or "").lower().strip()
        raw = q.get("tickers", [""])[0] or ""
        tickers = [t for t in raw.replace(" ", ",").split(",") if t.strip()]
        if preset.startswith("swing2") and not tickers:
            try:
                import swing2_backtest as s2
                key = {"swing2": "default", "swing2_mega": "mega", "swing2_tech": "tech"}.get(preset, "default")
                tickers = list((getattr(s2, "UNIVERSE_PRESETS", {}).get(key)) or s2.DEFAULT_UNIVERSE)
            except Exception as e:
                return self.send_html(500, f"<h3>evren alınamadı: {e}</h3>")
        if not tickers:
            return self.send_html(400, "<h3 style='font-family:sans-serif'>tickers veya preset gerekli</h3>")
        if len(tickers) > 200:
            tickers = tickers[:200]
        try:
            import qswing.main as qm
            self.send_html(200, qm.scan_index_html(tickers, asof=date, conc=8))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_html(502, f"<div style='font-family:sans-serif;color:#ff5d6c;background:#0d1218;padding:24px'>"
                                f"<h3>qswing tarama hatası</h3><p>{e}</p></div>")

    # ---- /api/history/<SYM>?range=2y  → işlem grafiği için günlük OHLCV ----
    def handle_history(self):
        parts = self.path.split("?", 1)
        sym = urllib.parse.unquote(parts[0].split("/api/history/", 1)[1]).upper().strip()
        q = urllib.parse.parse_qs(parts[1]) if len(parts) > 1 else {}
        rng = (q.get("range", ["2y"])[0] or "2y")
        frm = (q.get("from", [""])[0] or "").strip()   # ISO: işlemin gerçek penceresi (range'i ezer)
        to = (q.get("to", [""])[0] or "").strip()
        if not sym:
            return self.send_json(400, {"error": "symbol gerekli"})
        try:
            import swing2_backtest as s2
            key = s2._fmp_key()
            if not key:
                return self.send_json(502, {"error": "FMP_API_KEY yok"})
            # from/to verilirse onu kullan (işlem tarihlerini garanti kapsar); yoksa period'tan türet
            start = frm if frm else s2._period_to_start(rng, 10)
            dl_end = to if to else None
            df = s2._fmp_daily_one(sym, key, start, dl_end)  # motorla AYNI veri kaynağı (FMP /stable)
            if df is None or df.empty:
                return self.send_json(404, {"error": f"{sym} için veri yok"})
            bars = [{"date": idx.strftime("%Y-%m-%d"),
                     "open": float(o), "high": float(h), "low": float(lo),
                     "close": float(c), "volume": float(v)}
                    for idx, (o, h, lo, c, v) in zip(df.index, df[s2.OHLCV].itertuples(index=False))]
            self.send_json(200, {"symbol": sym, "bars": bars})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_json(502, {"error": str(e)})

    # ---- yardımcılar ----
    def send_json(self, code, data):
        r = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(r))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(r)

    def send_html(self, code, html):
        r = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(r))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(r)

    def log_message(self, fmt, *args):
        if args and "/api/" in str(args[0]):
            super().log_message(fmt, *args)


def main():
    if not os.environ.get("FMP_API_KEY"):
        print("UYARI: FMP_API_KEY yok. env / .env / ~/.portfolio_keys.json ile ayarla.", file=sys.stderr)
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Swing Backtest Lab → http://localhost:{PORT}/  (0.0.0.0:{PORT})", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nkapatıldı.")


if __name__ == "__main__":
    main()

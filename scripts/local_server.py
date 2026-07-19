#!/usr/bin/env python3
"""Local-only static server with a safe refresh endpoint."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
REFRESH_LOCK = threading.Lock()


class MonitorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        if self.path.startswith("/data/"):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/refresh":
            self.send_json(404, {"ok": False, "error": "Not found"})
            return
        if not REFRESH_LOCK.acquire(blocking=False):
            self.send_json(409, {"ok": False, "error": "更新処理はすでに実行中です。"})
            return
        try:
            update = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "update_data.py")],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=900,
            )
            if update.returncode:
                self.send_json(500, {"ok": False, "error": "データ更新に失敗しました。", "detail": update.stderr[-1600:]})
                return
            validation = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "validate_data.py")],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if validation.returncode:
                self.send_json(500, {"ok": False, "error": "更新後の検証に失敗しました。", "detail": validation.stderr[-1600:]})
                return
            payload = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
            self.send_json(200, {
                "ok": True,
                "marketDate": payload.get("marketDate"),
                "generatedAtJst": payload.get("generatedAtJst"),
                "warnings": (payload.get("dataQuality") or {}).get("failedRequests", 0),
            })
        except subprocess.TimeoutExpired:
            self.send_json(504, {"ok": False, "error": "更新処理が時間内に完了しませんでした。"})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
        finally:
            REFRESH_LOCK.release()


if __name__ == "__main__":
    host = "127.0.0.1"
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"AI bubble monitor: http://{host}:{port}/", flush=True)
    ThreadingHTTPServer((host, port), MonitorHandler).serve_forever()

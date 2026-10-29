#!/usr/bin/env python3
"""Local, event-ready visual wrapper around the real ``atp demo wrap`` flow.

The browser is presentation only. A run always executes the repository's real
MCP demo, then reads the resulting ATP trace store. It cannot approve actions,
change grants or policies, or send messages itself.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import mimetypes
import re
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "demo" / "founder"
TRACE_RE = re.compile(r"\b[0-9a-f]{12}\b")


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _redact_output(text: str, out_dir: Path) -> list[str]:
    """Return a bounded, secret-safe transcript for the browser."""
    cleaned = text.replace(str(out_dir.resolve()), "<demo-output>")
    cleaned = cleaned.replace(str(ROOT), "<repository>")
    lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
    return lines[-80:]


def _alert_status(home: Path, trace_id: str) -> str | None:
    """Read the outbound-attempt status without exposing recipient or message IDs."""
    journal = home / "photon-alerts.db"
    if not journal.exists():
        return None
    try:
        with sqlite3.connect(f"file:{journal}?mode=ro", uri=True, timeout=2) as conn:
            row = conn.execute(
                "SELECT status FROM photon_attempts WHERE trace_id = ?", (trace_id,)
            ).fetchone()
    except (sqlite3.Error, OSError):
        return None
    return str(row[0]) if row else None


def _trace_payload(view: Any) -> dict[str, Any]:
    env = view.envelope
    decision = view.decision
    execution = view.execution
    execution_type = (
        execution.get("event_type")
        if isinstance(execution, dict)
        else getattr(execution, "event_type", None)
    )
    return {
        "trace_id": view.trace_id,
        "action": env.action if env else None,
        "capability": env.capability if env else None,
        "outcome": _value(decision.outcome) if decision else None,
        "reason_code": _value(decision.reason_code) if decision else None,
        "enforcement": _value(decision.enforcement) if decision else None,
        "executed": execution_type == "execution_completed",
        "integrity_valid": bool(view.integrity.valid),
        "event_count": int(view.integrity.event_count),
        "head_hash": view.integrity.head_hash,
    }


def _summarize(out_dir: Path, transcript: str, returncode: int) -> dict[str, Any]:
    from atp_cli.home import AtpHome

    home = out_dir / ".atp"
    runtime = AtpHome(home).open()
    traces: list[dict[str, Any]] = []
    try:
        for summary in runtime.trust_plane.list_traces(limit=30):
            traces.append(_trace_payload(runtime.trust_plane.get_trace(summary.trace_id)))
    finally:
        with contextlib.suppress(Exception):
            runtime.close()

    write = next((item for item in traces if item["action"] == "write_note"), None)
    denial = next((item for item in traces if item["action"] == "delete_note"), None)
    if denial:
        denial["photon_request"] = _alert_status(home, denial["trace_id"])

    note_path = out_dir / "notes" / "todo.txt"
    regression_path = out_dir / "atp-regression.yaml"
    checks = {
        "write_allowed_and_executed": bool(
            write and write["outcome"] == "ALLOW" and write["executed"]
        ),
        "delete_denied_enforced": bool(
            denial
            and denial["outcome"] == "DENY"
            and denial["enforcement"] == "enforce"
            and not denial["executed"]
        ),
        "note_still_exists": note_path.is_file(),
        "evidence_integrity_valid": bool(denial and denial["integrity_valid"]),
        "regression_pinned": regression_path.is_file(),
    }
    return {
        "ok": returncode == 0 and all(checks.values()),
        "ran_at": datetime.now(UTC).isoformat(),
        "write": write,
        "denial": denial,
        "checks": checks,
        "transcript": _redact_output(transcript, out_dir),
        "truth": {
            "scenario": "Local deterministic MCP notes server; no LLM and no payment",
            "phone_delivery": "Confirm on device; an accepted Photon request is not delivery proof",
            "telegram": "Beta code in separate draft PR; real delivery unverified",
        },
    }


def run_demo(out_dir: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "atp_cli.main",
        "demo",
        "wrap",
        "--out",
        str(out_dir),
    ]
    proc = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    transcript = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    try:
        return _summarize(out_dir, transcript, proc.returncode)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Demo evidence could not be read: {type(exc).__name__}: {exc}",
            "transcript": _redact_output(transcript, out_dir),
        }


class DemoState:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir.resolve()
        self.lock = threading.Lock()
        self.last: dict[str, Any] | None = None


def make_handler(state: DemoState, port: int) -> type[BaseHTTPRequestHandler]:
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "ATPFounderDemo/1"

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[demo] {self.address_string()} {fmt % args}")

        def _json(self, body: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/status":
                self._json({"running": state.lock.locked(), "last": state.last})
                return
            asset = "index.html" if path == "/" else path.lstrip("/")
            if asset not in {"index.html", "style.css", "app.js"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            target = ASSETS / asset
            try:
                payload = target.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "text/plain")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/run":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            origin = self.headers.get("Origin")
            if origin not in allowed_origins:
                self._json({"ok": False, "error": "Origin rejected"}, HTTPStatus.FORBIDDEN)
                return
            if self.headers.get_content_type() != "application/json":
                self._json(
                    {"ok": False, "error": "JSON required"},
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                )
                return
            if not state.lock.acquire(blocking=False):
                self._json(
                    {"ok": False, "error": "A demo run is already active"}, HTTPStatus.CONFLICT
                )
                return
            try:
                state.last = run_demo(state.out_dir)
                self._json(
                    state.last, HTTPStatus.OK if state.last.get("ok") else HTTPStatus.BAD_GATEWAY
                )
            finally:
                state.lock.release()

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--out", type=Path, default=ROOT / "photon-demo")
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")

    state = DemoState(args.out)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(state, args.port))
    url = f"http://127.0.0.1:{args.port}"
    print(f"Agent Trust Plane founder demo: {url}")
    print(f"Real demo evidence will be written to: {state.out_dir}")
    print("This UI cannot approve actions or send messages. Press Ctrl+C to stop.")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

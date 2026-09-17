"""``atp doctor``: check prerequisites and report actionable problems."""

from __future__ import annotations

import importlib
import os
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def _python() -> Check:
    v = sys.version_info
    ok = v >= (3, 12)
    return Check(
        "Python >= 3.12",
        ok,
        f"{v.major}.{v.minor}.{v.micro} at {sys.executable}",
        "" if ok else "install Python 3.12+ and re-run `uv sync`",
    )


def _uv() -> Check:
    path = shutil.which("uv")
    return Check(
        "uv on PATH",
        path is not None,
        path or "not found",
        "" if path else "install uv: https://docs.astral.sh/uv/getting-started/installation/",
    )


def _packages() -> Check:
    missing = []
    for mod in (
        "atp_core",
        "atp_gateway",
        "atp_evals",
        "atp_adapter_mcp",
        "notes_mcp_server",
        "mcp",
    ):
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    return Check(
        "workspace packages importable",
        not missing,
        "all present" if not missing else f"missing: {', '.join(missing)}",
        "" if not missing else "run `uv sync` from the repository root",
    )


def _port(port: int) -> Check:
    with socket.socket() as s:
        s.settimeout(0.2)
        in_use = s.connect_ex(("127.0.0.1", port)) == 0
    return Check(
        f"port {port} free",
        not in_use,
        "in use" if in_use else "free",
        "" if not in_use else f"stop whatever listens on {port} or pass --port",
    )


def _node() -> Check:
    npm = shutil.which("npm")
    return Check(
        "Node.js / npm (dashboard only)",
        npm is not None,
        npm or "not found",
        "" if npm else "optional: install Node 20+ to build the dashboard",
    )


def _env_file(root: Path) -> Check:
    env = root / ".env"
    if not env.exists():
        return Check(
            ".env with gateway keys (persistent gateway only)",
            True,
            "absent (fine for `atp demo`; `atp serve` needs it)",
            "create with `uv run atp keygen --write .env`",
        )
    text = env.read_text(encoding="utf-8", errors="replace")
    has = all(k in text for k in ("ATP_GRANT_SIGNING_KEY=", "ATP_OPERATOR_KEY="))
    return Check(
        ".env with gateway keys",
        has,
        "present" if has else "present but missing keys",
        "" if has else "run `uv run atp keygen --write .env.new` and merge",
    )


def _tmp_writable() -> Check:
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(delete=True):
            pass
        return Check("temp directory writable", True, tempfile.gettempdir())
    except OSError as exc:
        return Check("temp directory writable", False, str(exc), "fix TMP/TEMP permissions")


def run_doctor(root: Path | None = None, *, port: int = 8000) -> list[Check]:
    root = root or Path.cwd()
    return [_python(), _uv(), _packages(), _tmp_writable(), _port(port), _node(), _env_file(root)]


def format_doctor(checks: list[Check]) -> str:
    lines = ["agent-trust-plane doctor", ""]
    for c in checks:
        mark = "ok " if c.ok else "FAIL"
        lines.append(f"[{mark}] {c.name}: {c.detail}")
        if not c.ok and c.fix:
            lines.append(f"       -> {c.fix}")
    bad = [c for c in checks if not c.ok]
    lines.append("")
    lines.append(
        "everything needed for `atp demo` is present" if not bad else f"{len(bad)} problem(s) found"
    )
    if os.name == "nt":
        lines.append("platform: Windows (PowerShell paths in docs apply)")
    return "\n".join(lines)

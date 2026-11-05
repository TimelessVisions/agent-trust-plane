"""Fetch pinned competitor binaries into ``bench/.tools/<name>/<version>/``.

Every asset is verified against the SHA-256 in ``bench/data/tool_pins.yaml`` before anything
is made executable. Any reason the tool cannot be had here (unsupported platform, no pin,
download failure, hash mismatch, bad archive) raises :class:`EnvBlocked` with that reason.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Literal

import yaml

from atp_bench.layers.base import EnvBlocked

BENCH_ROOT = Path(__file__).resolve().parents[2]
PINS = BENCH_ROOT / "data" / "tool_pins.yaml"
TOOLS_DIR = BENCH_ROOT / ".tools"

ToolName = Literal["agentgateway", "toolhive"]

_OS = {"linux": "linux", "darwin": "darwin", "win32": "windows", "cygwin": "windows"}
_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


def platform_key() -> str:
    """``<os>-<arch>``, e.g. ``linux-amd64``, matching the keys in ``tool_pins.yaml``."""
    os_name = _OS.get(sys.platform, sys.platform)
    machine = platform.machine().lower()
    return f"{os_name}-{_ARCH.get(machine, machine)}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pin(name: str, pins: Path) -> tuple[str, dict[str, Any]]:
    try:
        raw = yaml.safe_load(pins.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise EnvBlocked(f"{name}: cannot read pins {pins}: {exc}") from exc
    if name not in raw:
        raise EnvBlocked(f"{name}: not pinned in {pins.name}")
    key = platform_key()
    entry = (raw[name].get("platforms") or {}).get(key)
    if entry is None:
        raise EnvBlocked(f"{name}: no pinned build for platform {key}")
    if not entry.get("sha256"):
        raise EnvBlocked(f"{name}: no pinned sha256 for {key}")
    if not entry.get("executable") or not entry.get("url"):
        raise EnvBlocked(f"{name}: pin for {key} lacks 'executable' or 'url'")
    return str(raw[name]["version"]), entry


def _download(url: str, dest: Path, timeout_s: float) -> None:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp, dest.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
    except Exception as exc:  # any network or HTTP failure
        raise EnvBlocked(f"download failed: {url}: {type(exc).__name__}: {exc}"[:500]) from exc


def _install(asset: Path, entry: dict[str, Any], staging: Path) -> Path:
    try:
        return _install_unchecked(asset, entry, staging)
    except EnvBlocked:
        raise
    except (OSError, KeyError) as exc:
        raise EnvBlocked(f"install failed for {asset.name}: {type(exc).__name__}: {exc}") from exc


def _installed(target: Path, exe_name: str, want: str) -> Path | None:
    """The executable under ``target`` if it is fully installed with hash stamp ``want``."""
    exe = target / exe_name
    stamp = target / ".sha256"
    try:
        if exe.is_file() and stamp.read_text(encoding="utf-8").strip() == want:
            return exe
    except OSError:
        pass
    return None


def _install_unchecked(asset: Path, entry: dict[str, Any], staging: Path) -> Path:
    exe_name = str(entry["executable"])
    archive = entry.get("archive", "none")
    if archive == "none":
        exe = staging / exe_name
        asset.replace(exe)
    elif archive == "tar.gz":
        try:
            with tarfile.open(asset, "r:gz") as tar:
                member = next(
                    (m for m in tar.getmembers() if m.isfile() and Path(m.name).name == exe_name),
                    None,
                )
                if member is None:
                    raise EnvBlocked(f"{exe_name} not found in {asset.name}")
                member.name = exe_name
                tar.extract(member, staging, filter="data")
        except tarfile.TarError as exc:
            raise EnvBlocked(f"bad archive {asset.name}: {exc}") from exc
        exe = staging / exe_name
    else:
        raise EnvBlocked(f"unknown archive kind {archive!r}")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return exe


def fetch_tool(
    name: ToolName,
    *,
    pins: Path = PINS,
    tools_dir: Path = TOOLS_DIR,
    timeout_s: float = 300.0,
) -> Path:
    """Return the path of the pinned, verified executable, downloading it if needed."""
    version, entry = _pin(name, pins)
    want = str(entry["sha256"]).lower()
    target = tools_dir / name / version
    exe_name = str(entry["executable"])
    done = _installed(target, exe_name, want)
    if done is not None:
        return done

    tools_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tools_dir, prefix=f".{name}-") as tmp:
        staging = Path(tmp) / "out"
        staging.mkdir()
        asset = Path(tmp) / "asset"
        _download(str(entry["url"]), asset, timeout_s)
        got = _sha256(asset)
        if got != want:
            raise EnvBlocked(f"{name} {version}: sha256 mismatch: expected {want}, got {got}")
        installed = _install(asset, entry, staging)
        try:
            (staging / ".sha256").write_text(want + "\n", encoding="utf-8")
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
        except OSError as exc:
            # A concurrent fetch may have installed the same verified build first.
            done = _installed(target, exe_name, want)
            if done is not None:
                return done
            raise EnvBlocked(f"{name} {version}: install failed: {exc}") from exc
    return target / installed.name

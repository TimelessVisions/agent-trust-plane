"""Pinned competitor-binary fetcher. No network: a local HTTP server stands in for GitHub."""

from __future__ import annotations

import hashlib
import http.server
import threading
from pathlib import Path

import pytest
import yaml
from atp_bench import tools
from atp_bench.layers import EnvBlocked

PAYLOAD = b"#!/bin/sh\necho fake agentgateway\n"


@pytest.fixture
def fake_release(tmp_path, monkeypatch):
    root = tmp_path / "srv"
    root.mkdir()
    (root / "agentgateway-linux-amd64").write_bytes(PAYLOAD)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    for var in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    yield f"http://127.0.0.1:{httpd.server_address[1]}/agentgateway-linux-amd64"
    httpd.shutdown()


def _pins(tmp_path: Path, url: str, sha256: str | None) -> Path:
    path = tmp_path / "pins.yaml"
    path.write_text(yaml.safe_dump({
        "agentgateway": {"version": "v1.6.0", "platforms": {"linux-amd64": {
            "url": url, "sha256": sha256, "archive": "none", "executable": "agentgateway",
        }}},
    }), encoding="utf-8")  # fmt: skip
    return path


def test_fetch_verifies_sha(tmp_path, fake_release, monkeypatch):
    monkeypatch.setattr(tools, "platform_key", lambda: "linux-amd64")
    tools_dir = tmp_path / ".tools"
    wrong = hashlib.sha256(b"something else").hexdigest()
    with pytest.raises(EnvBlocked, match="sha256 mismatch") as info:
        tools.fetch_tool("agentgateway", pins=_pins(tmp_path, fake_release, wrong),
                         tools_dir=tools_dir)  # fmt: skip
    assert wrong in info.value.reason
    # Nothing unverified is left behind to be picked up later.
    assert not list(tools_dir.rglob("agentgateway"))

    right = hashlib.sha256(PAYLOAD).hexdigest()
    exe = tools.fetch_tool("agentgateway", pins=_pins(tmp_path, fake_release, right),
                           tools_dir=tools_dir)  # fmt: skip
    assert exe == tools_dir / "agentgateway" / "v1.6.0" / "agentgateway"
    assert exe.read_bytes() == PAYLOAD
    assert exe.stat().st_mode & 0o111


def test_fetch_download_failure_and_null_pin_env_blocked(tmp_path, fake_release, monkeypatch):
    monkeypatch.setattr(tools, "platform_key", lambda: "linux-amd64")
    right = hashlib.sha256(PAYLOAD).hexdigest()
    with pytest.raises(EnvBlocked, match="download failed"):
        tools.fetch_tool("agentgateway", pins=_pins(tmp_path, fake_release + ".missing", right),
                         tools_dir=tmp_path / ".tools")  # fmt: skip
    with pytest.raises(EnvBlocked, match="no pinned sha256"):
        tools.fetch_tool("agentgateway", pins=_pins(tmp_path, fake_release, None),
                         tools_dir=tmp_path / ".tools")  # fmt: skip


def test_unsupported_platform_env_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.sys, "platform", "win32")
    monkeypatch.setattr(tools.platform, "machine", lambda: "AMD64")
    assert tools.platform_key() == "windows-amd64"
    for name in ("agentgateway", "toolhive"):
        with pytest.raises(EnvBlocked, match="windows-amd64") as info:
            tools.fetch_tool(name, tools_dir=tmp_path / ".tools")
        assert name in info.value.reason
    assert not (tmp_path / ".tools").exists()


def test_real_pins_are_complete():
    raw = yaml.safe_load(tools.PINS.read_text(encoding="utf-8"))
    assert raw["agentgateway"]["version"] == "v1.6.0"
    assert raw["toolhive"]["version"] == "v0.55.2"
    for name in ("agentgateway", "toolhive"):
        pin = raw[name]["platforms"]["linux-amd64"]
        assert len(pin["sha256"]) == 64 and int(pin["sha256"], 16) >= 0
        assert pin["url"].startswith("https://github.com/")


def test_install_errors_are_env_blocked(tmp_path, fake_release, monkeypatch):
    monkeypatch.setattr(tools, "platform_key", lambda: "linux-amd64")
    right = hashlib.sha256(PAYLOAD).hexdigest()
    pins = _pins(tmp_path, fake_release, right)
    raw = yaml.safe_load(pins.read_text(encoding="utf-8"))
    del raw["agentgateway"]["platforms"]["linux-amd64"]["executable"]
    pins.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(EnvBlocked, match="executable"):
        tools.fetch_tool("agentgateway", pins=pins, tools_dir=tmp_path / ".tools")

    def boom(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(EnvBlocked, match="disk full"):
        tools.fetch_tool("agentgateway", pins=_pins(tmp_path, fake_release, right),
                         tools_dir=tmp_path / ".tools2")  # fmt: skip


def test_lost_install_race_is_success(tmp_path, fake_release, monkeypatch):
    """A concurrent fetch installed the target first: our failing os.replace is not an error."""
    monkeypatch.setattr(tools, "platform_key", lambda: "linux-amd64")
    right = hashlib.sha256(PAYLOAD).hexdigest()
    pins = _pins(tmp_path, fake_release, right)
    tools_dir = tmp_path / ".tools"
    real_replace = tools.os.replace

    def racing(src, dst):
        real_replace(src, dst)
        if Path(dst).name == "v1.6.0":  # the other process wins the final rename ...
            raise OSError(39, "Directory not empty")  # ... and ours fails

    monkeypatch.setattr(tools.os, "replace", racing)
    exe = tools.fetch_tool("agentgateway", pins=pins, tools_dir=tools_dir)
    assert exe.read_bytes() == PAYLOAD

    def lost(src, dst):
        if Path(dst).name == "v1.6.0":
            raise OSError(39, "Directory not empty")
        real_replace(src, dst)

    monkeypatch.setattr(tools.os, "replace", lost)
    with pytest.raises(EnvBlocked, match="Directory not empty"):
        tools.fetch_tool("agentgateway", pins=pins, tools_dir=tmp_path / ".other")

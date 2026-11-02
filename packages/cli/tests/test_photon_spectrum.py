from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from atp_cli import main as cli
from atp_cli import photon_spectrum as sdk
from atp_cli.photon import PhotonAlertError


@pytest.fixture
def configured_bridge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    bridge = tmp_path / "send.mjs"
    bridge.write_text("// test-only bridge\n", encoding="utf-8")
    (tmp_path / "node_modules" / "spectrum-ts").mkdir(parents=True)
    monkeypatch.setattr(sdk, "BRIDGE", bridge)
    monkeypatch.setattr(sdk.shutil, "which", lambda _: "/usr/bin/node")
    monkeypatch.setenv("SPECTRUM_PROJECT_ID", "project_test")
    monkeypatch.setenv("SPECTRUM_PROJECT_SECRET", "test-secret-never-log")
    return bridge


def test_spectrum_transport_is_cli_default() -> None:
    parser = cli.build_parser()
    notify = parser.parse_args(
        ["photon", "notify", "trc_test123", "--to", "+12125550123", "--dry-run"]
    )
    watch = parser.parse_args(["photon", "watch", "--to", "+12125550123", "--once"])
    assert notify.transport == "spectrum"
    assert watch.transport == "spectrum"


def test_spectrum_client_sends_only_given_message(
    configured_bridge: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append((args, kwargs))
        return subprocess.CompletedProcess(["node"], 0, stdout="ok", stderr="")

    monkeypatch.setattr(sdk.subprocess, "run", fake_run)
    client = sdk.SpectrumClient()
    message = (
        "AGENT TRUST PLANE\nDecision: DENY (enforced)\n"
        "Trace: trc_test123\nReason: CAPABILITY_NOT_GRANTED\n"
        "Read-only notification. Text replies cannot approve actions."
    )
    assert (
        client.send_denial("+12125550123", "trc_test123", message) == "spectrum-request-trc_test123"
    )
    args, kwargs = seen[0]  # type: ignore[misc]
    assert args[0] == ["node", str(configured_bridge), "+12125550123"]
    assert kwargs["input"] == message
    assert kwargs["capture_output"] is True
    assert "test-secret-never-log" not in str(seen)


def test_spectrum_failure_is_generic_and_never_exposes_secrets(
    configured_bridge: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["node"], 1, stderr="test-secret-never-log")

    monkeypatch.setattr(sdk.subprocess, "run", fail)
    client = sdk.SpectrumClient()
    with pytest.raises(PhotonAlertError, match="outcome unknown") as exc:
        client.send_denial("+12125550123", "trc_test123", "safe")
    assert "test-secret-never-log" not in str(exc.value)


def test_missing_secret_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRUM_PROJECT_ID", "project_test")
    monkeypatch.delenv("SPECTRUM_PROJECT_SECRET", raising=False)
    with pytest.raises(PhotonAlertError, match="SPECTRUM_PROJECT"):
        sdk.SpectrumClient()


def test_telegram_client_sends_to_numeric_user_id(
    configured_bridge: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPECTRUM_TELEGRAM_BOT_TOKEN", "test-bot-token")
    captured: list[object] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append((args, kwargs))
        return subprocess.CompletedProcess(["node"], 0, stdout="ok", stderr="")

    monkeypatch.setattr(sdk.subprocess, "run", fake_run)
    client = sdk.SpectrumClient(channel="telegram")
    assert client.credentials.project_id.endswith(":telegram")
    assert client.send_denial("123456789", "trc_test123", "approved alert") == (
        "spectrum-request-trc_test123"
    )
    args, kwargs = captured[0]  # type: ignore[misc]
    assert args[0] == ["node", str(configured_bridge), "telegram", "123456789"]
    assert kwargs["input"] == "approved alert"
    assert "test-bot-token" not in str(captured)
    with pytest.raises(PhotonAlertError, match="numeric user ID"):
        client.send_denial("+12125550123", "trc_test123", "approved alert")


def test_telegram_needs_bot_token(configured_bridge: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPECTRUM_TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(PhotonAlertError, match="SPECTRUM_TELEGRAM_BOT_TOKEN"):
        sdk.SpectrumClient(channel="telegram")


def test_telegram_cli_parses_channel() -> None:
    parser = cli.build_parser()
    notify = parser.parse_args(
        [
            "photon",
            "notify",
            "trc_test123",
            "--channel",
            "telegram",
            "--to",
            "123456789",
            "--dry-run",
        ]
    )
    watcher = parser.parse_args(["photon", "watch", "--channel", "telegram", "--to", "123456789"])
    assert notify.channel == watcher.channel == "telegram"
    assert watcher.transport == "spectrum"

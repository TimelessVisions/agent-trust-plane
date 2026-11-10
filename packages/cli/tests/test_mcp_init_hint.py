"""`atp mcp init` tells the user the exact line that grants a destructive tool."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from atp_cli.main import main


def test_init_prints_exact_grant_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NOTES_DIR", str(notes))
    config = tmp_path / "atp-mcp.yaml"
    try:
        main(
            [
                "mcp",
                "init",
                "--config",
                str(config),
                "--name",
                "notes",
                "--home",
                str(tmp_path / "home"),
                "--",
                sys.executable,
                "-m",
                "notes_mcp_server",
            ]
        )
    except SystemExit as exc:
        assert not exc.code
    captured = capfd.readouterr()
    output = (captured.out + captured.err).splitlines()
    expected = (
        '  to allow delete_note: add "notes:destroy" to authority.capabilities in atp-mcp.yaml'
    )
    assert expected in output
    # Only the undelegated destructive tool gets a hint.
    hints = [line for line in output if line.startswith("  to allow ")]
    assert hints == [expected]

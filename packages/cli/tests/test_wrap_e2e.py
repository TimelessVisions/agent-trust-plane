"""The developer loop, end to end, over the real MCP protocol:

    atp mcp init  -> atp mcp wrap (gateway in-process from .atp/) -> tools/call
    -> atp trace list -> atp policy explain -> atp regression add -> atp test
    -> atp policy impact -> atp mutate -> atp evidence export / verify

Three processes for the wrap phase: this test (MCP client) -> `atp mcp wrap`
(proxy + gateway) -> notes server. Shadow mode is exercised the same way.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client

from atp_cli.main import main


def _run(*argv: str) -> int:
    try:
        main(list(argv))
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _text(r: types.CallToolResult) -> str:
    return "".join(c.text for c in r.content if isinstance(c, types.TextContent))


async def _drive(
    config: Path, home: Path, mode: str, calls: list[tuple[str, dict[str, Any]]]
) -> list[Any]:
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "atp_cli.main",
            "mcp",
            "wrap",
            "--config",
            str(config),
            "--home",
            str(home),
            "--mode",
            mode,
        ],
        env={**get_default_environment(), "ATP_HOME": str(home)},
    )
    out: list[Any] = []
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        out.append(sorted(t.name for t in (await s.list_tools()).tools))
        for name, args in calls:
            out.append(await s.call_tool(name, args))
    return out


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    notes = tmp_path / "notes"
    notes.mkdir()
    home = tmp_path / "home"
    config = tmp_path / "atp-mcp.yaml"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ATP_OPERATOR_KEY", raising=False)
    monkeypatch.delenv("ATP_GRANT_SIGNING_KEY", raising=False)
    monkeypatch.setenv("NOTES_DIR", str(notes))
    assert (
        _run(
            "mcp",
            "init",
            "--config",
            str(config),
            "--name",
            "notes",
            "--home",
            str(home),
            "--",
            sys.executable,
            "-m",
            "notes_mcp_server",
        )
        == 0
    )
    # The generated config does not know the server's env; add it and tighten the scope.
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["upstream"]["env"] = {"NOTES_DIR": str(notes)}
    data["authority"]["resource_scope"] = ["id:*", "tool:*"]
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return {"notes": notes, "home": home, "config": config, "root": tmp_path}


def test_wrap_loop_enforce(workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    notes, home, config = workspace["notes"], workspace["home"], workspace["config"]
    listed, write, read, delete = anyio.run(
        _drive,
        config,
        home,
        "enforce",
        [
            ("write_note", {"id": "todo", "text": "buy milk"}),
            ("read_note", {"id": "todo"}),
            ("delete_note", {"id": "todo"}),
        ],
    )
    # delete_note is mapped (so listed) but its capability is not delegated.
    assert listed == ["delete_note", "list_notes", "read_note", "write_note"]
    assert not write.is_error and (notes / "todo.txt").exists()
    assert "buy milk" in _text(read)
    assert delete.is_error
    denial = delete.structured_content
    assert denial["reason_code"] == "CAPABILITY_NOT_GRANTED"
    assert (notes / "todo.txt").exists(), "denied call must not reach the upstream"
    trace_id = denial["trace_id"]

    # local store: keys generated and gitignored, policy file committable, decisions there
    assert (home / "keys.env").exists() and (home / "policies.yaml").exists()
    ignored = (home / ".gitignore").read_text(encoding="utf-8")
    assert "keys.env" in ignored
    assert not any(line.strip() == "policies.yaml" for line in ignored.splitlines())
    assert _run("trace", "list", "--home", str(home)) == 0
    out = capsys.readouterr().out
    assert trace_id in out and "DENY" in out and "ALLOW" in out
    assert "WOULD_DENY" not in out

    # explain: deterministic, names the missing capability and the leaf grant
    assert _run("policy", "explain", trace_id, "--home", str(home)) == 0
    out = capsys.readouterr().out
    assert "DENY  CAPABILITY_NOT_GRANTED" in out
    assert "delegate capability 'notes:destroy'" in out
    assert "local-user (human)" in out

    # regression add -> test passes; under a set that lacks nothing it still passes
    suite = workspace["root"] / "atp-regression.yaml"
    assert (
        _run(
            "regression",
            "add",
            trace_id,
            "--suite",
            str(suite),
            "--home",
            str(home),
            "--name",
            "delete stays denied",
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "ADDED delete stays denied" in out and "DENY / CAPABILITY_NOT_GRANTED" in out
    assert _run("test", str(suite), "--quiet", "--home", str(home)) == 0
    text = suite.read_text(encoding="utf-8")
    assert "notes-agent" in text and "policy_set: notes-v1" in text
    assert "policies: ../home/policies.yaml" in text or "policies: " in text

    # impact between built-in sets: nothing about this case changes
    assert (
        _run(
            "policy",
            "impact",
            "--from",
            "payments-v1",
            "--to",
            "payments-v2",
            "--suite",
            str(suite),
        )
        == 0
    )
    assert "unchanged DENY  (1)" in capsys.readouterr().out

    # mutate: every mutant that leaves the delegated authority is denied
    assert _run("mutate", trace_id, "--home", str(home)) == 0
    out = capsys.readouterr().out
    assert "0 unexpected" in out and "mutations:" in out

    # evidence bundle round-trips and detects tampering
    bundle = workspace["root"] / "bundle.json"
    assert _run("evidence", "export", trace_id, "--home", str(home), "--out", str(bundle)) == 0
    assert _run("evidence", "verify", str(bundle)) == 0
    data = json.loads(bundle.read_text(encoding="utf-8"))
    data["decision"]["outcome"] = "ALLOW"
    bundle.write_text(json.dumps(data), encoding="utf-8")
    assert _run("evidence", "verify", str(bundle)) == 1
    assert "bundle_hash does not match" in capsys.readouterr().out


def test_wrap_loop_shadow(workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    notes, home, config = workspace["notes"], workspace["home"], workspace["config"]
    (notes / "todo.txt").write_text("x", encoding="utf-8")
    listed, delete = anyio.run(_drive, config, home, "shadow", [("delete_note", {"id": "todo"})])
    # shadow: the call is forwarded (the note is gone) but recorded as WOULD_DENY
    assert not delete.is_error
    assert not (notes / "todo.txt").exists()
    assert _run("trace", "list", "--home", str(home)) == 0
    out = capsys.readouterr().out
    assert "WOULD_DENY" in out and "shadow_execution_completed" in out
    trace_id = next(line.split()[0] for line in out.splitlines() if "WOULD_DENY" in line)
    assert _run("policy", "explain", trace_id, "--home", str(home)) == 0
    out = capsys.readouterr().out
    assert "WOULD_DENY  CAPABILITY_NOT_GRANTED" in out and "mode=shadow" in out
    # a shadow trace pins the same expectation (DENY): enforcing later keeps it
    suite = workspace["root"] / "shadow.yaml"
    assert _run("regression", "add", trace_id, "--suite", str(suite), "--home", str(home)) == 0
    assert "DENY / CAPABILITY_NOT_GRANTED" in capsys.readouterr().out
    assert _run("test", str(suite), "--quiet") == 0


def test_wrap_refuses_without_config_or_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert _run("mcp", "wrap", "--config", str(tmp_path / "missing.yaml")) == 2
    assert "not found" in capsys.readouterr().err
    assert _run("regression", "add", "abc", "--home", str(tmp_path / "nohome")) == 2
    assert "no ATP home" in capsys.readouterr().err


def test_home_is_authoritative_over_stray_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from atp_cli.home import AtpHome

    monkeypatch.setenv("ATP_OPERATOR_KEY", "x" * 40)
    monkeypatch.setenv("ATP_ENFORCEMENT_MODE", "shadow")
    home = AtpHome(tmp_path / "h").ensure()
    settings = home.settings()
    assert settings.operator_key == home.keys()["ATP_OPERATOR_KEY"]
    assert settings.enforcement_mode == "enforce"
    assert os.path.basename(settings.database_path) == "atp.db"

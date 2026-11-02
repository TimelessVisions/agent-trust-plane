"""Flagship proof: a real sandbox MCP server, not a mock of the proxy.

An allowed write is forwarded. An unauthorized delete is denied before the
upstream tool runs (the sandbox journals the tool name before any file
change). The denial is on the trace and explainable. A later edit to the
declared policy makes the pinned regression check fail.

The client/proxy session under test is the initialize handshake. That
handshake cannot negotiate MCP ``2026-07-28`` (stateless ``server/discover``).
A separate test asks a modern client to connect and still requires that a
denied delete is absent from the journal. Neither test claims the 2026
revision as a supported product surface.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

import anyio
import pytest
import uvicorn
import yaml
from mcp import Client, ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.types.version import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    LATEST_HANDSHAKE_VERSION,
    MODERN_PROTOCOL_VERSIONS,
)
from sandbox_journal_server import build_server, journal_lines

from atp_cli.home import AtpHome
from atp_cli.main import main

SANDBOX = Path(__file__).with_name("sandbox_journal_server.py")
HANDSHAKE_REVISION = "2025-11-25"


def _run(*argv: str) -> int:
    try:
        main(list(argv))
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _text(result: types.CallToolResult) -> str:
    return "".join(block.text for block in result.content if isinstance(block, types.TextContent))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@contextmanager
def _http_sandbox(root: Path, journal: Path) -> Iterator[str]:
    """Serve the sandbox over Streamable HTTP in a thread. Yields the MCP URL."""
    port = _free_port()
    app = build_server(root, journal).streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("sandbox HTTP server did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _policy_file(home: Path, *, deny_delete: bool) -> None:
    rules: list[dict[str, Any]] = []
    if deny_delete:
        rules.append(
            {
                "id": "never-delete",
                "description": "delete_note is denied outright",
                "applies_to": {"tool": "mcp.notes", "action": "delete_note"},
                "kind": "deny",
            }
        )
    text = {
        "version": 1,
        "policy_sets": [
            {
                "version": "notes-v1",
                "description": "sandbox notes",
                "rules": rules,
            }
        ],
    }
    (home / "policies.yaml").write_text(yaml.safe_dump(text, sort_keys=False), encoding="utf-8")


def _config(
    path: Path,
    *,
    transport: str,
    root: Path,
    journal: Path,
    capabilities: list[str],
    http_url: str | None = None,
) -> None:
    upstream: dict[str, Any]
    if transport == "stdio":
        upstream = {
            "command": sys.executable,
            "args": [str(SANDBOX)],
            "env": {
                "ATP_SANDBOX_ROOT": str(root),
                "ATP_SANDBOX_JOURNAL": str(journal),
            },
        }
    elif transport == "http":
        assert http_url is not None
        upstream = {"url": http_url}
    else:
        raise AssertionError(transport)
    cfg = {
        "server_name": "notes",
        "policy_set": "notes-v1",
        "principal": {"id": "local-user", "kind": "human"},
        "agent": {"id": "notes-agent", "kind": "agent"},
        "authority": {"capabilities": capabilities, "resource_scope": ["id:*"]},
        "upstream": upstream,
        "tools": [
            {
                "mcp_tool": "write_note",
                "tool": "mcp.notes",
                "action": "write_note",
                "capability": "notes:write",
                "resource_template": "id:{id}",
            },
            {
                "mcp_tool": "delete_note",
                "tool": "mcp.notes",
                "action": "delete_note",
                "capability": "notes:destroy",
                "resource_template": "id:{id}",
            },
        ],
    }
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def _proxy_params(config: Path, home: Path) -> StdioServerParameters:
    return StdioServerParameters(
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
            "enforce",
            "--log-level",
            "warning",
        ],
        env={**get_default_environment(), "ATP_HOME": str(home)},
    )


async def _handshake_write_then_delete(config: Path, home: Path) -> dict[str, Any]:
    params = _proxy_params(config, home)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        write_result = await session.call_tool("write_note", {"id": "todo", "text": "buy milk"})
        delete_result = await session.call_tool("delete_note", {"id": "todo"})
        return {
            "protocol": init.protocol_version,
            "write": write_result,
            "delete": delete_result,
        }


def _trace(home: Path, trace_id: str, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    assert _run("trace", "show", trace_id, "--home", str(home), "--json") == 0
    return json.loads(capsys.readouterr().out)


def _prepare(tmp_path: Path, *, deny_delete: bool) -> dict[str, Path]:
    root = tmp_path / "notes"
    journal = tmp_path / "journal.log"
    home = tmp_path / "home"
    AtpHome(home).ensure()
    _policy_file(home, deny_delete=deny_delete)
    return {"root": root, "journal": journal, "home": home, "config": tmp_path / "atp-mcp.yaml"}


class TestDeniedDeleteNeverReachesUpstream:
    @pytest.mark.parametrize("transport", ["stdio", "http"])
    def test_allowed_write_is_forwarded_and_delete_is_not_received(
        self,
        tmp_path: Path,
        transport: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        paths = _prepare(tmp_path, deny_delete=False)
        sandbox_cm = (
            _http_sandbox(paths["root"], paths["journal"])
            if transport == "http"
            else nullcontext(None)
        )
        with sandbox_cm as http_url:
            _config(
                paths["config"],
                transport=transport,
                root=paths["root"],
                journal=paths["journal"],
                capabilities=["notes:write"],
                http_url=http_url,
            )
            out = anyio.run(_handshake_write_then_delete, paths["config"], paths["home"])

        assert out["protocol"] == HANDSHAKE_REVISION
        assert out["write"].is_error is False
        assert _text(out["write"]) == "wrote todo (8 chars)"
        assert (paths["root"] / "todo.txt").read_text(encoding="utf-8") == "buy milk"

        assert out["delete"].is_error is True
        denial = out["delete"].structured_content
        assert denial["reason_code"] == "CAPABILITY_NOT_GRANTED"
        assert denial["outcome"] == "DENY"
        # Upstream-side: the tool journals its name before unlinking. The file
        # still existing is consistent with that, and is not the proof.
        assert journal_lines(paths["journal"]) == ["write_note"]
        assert (paths["root"] / "todo.txt").exists()

        trace = _trace(paths["home"], denial["trace_id"], capsys)
        assert trace["integrity"]["valid"] is True
        assert trace["decision"]["outcome"] == "DENY"
        assert trace["decision"]["reason_code"] == "CAPABILITY_NOT_GRANTED"
        events = [event["event_type"] for event in trace["events"]]
        assert "decision_made" in events
        assert "execution_released" not in events
        assert "execution_completed" not in events
        assert "execution_attempted" not in events
        provenance = trace["envelope"]["provenance"]["task_description"]
        assert f"protocol {HANDSHAKE_REVISION}" in provenance
        assert transport in provenance

        assert _run("policy", "explain", denial["trace_id"], "--home", str(paths["home"])) == 0
        explained = capsys.readouterr().out
        assert "DENY  CAPABILITY_NOT_GRANTED" in explained
        assert "notes:destroy" in explained
        assert "delegate capability 'notes:destroy'" in explained


class TestPolicyChangeFailsThePinnedRegression:
    def test_removing_the_deny_rule_fails_the_regression_check(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        paths = _prepare(tmp_path, deny_delete=True)
        _config(
            paths["config"],
            transport="stdio",
            root=paths["root"],
            journal=paths["journal"],
            capabilities=["notes:write", "notes:destroy"],
        )
        out = anyio.run(_handshake_write_then_delete, paths["config"], paths["home"])
        assert out["protocol"] == HANDSHAKE_REVISION
        assert out["write"].is_error is False
        assert (paths["root"] / "todo.txt").exists()
        denial = out["delete"].structured_content
        assert out["delete"].is_error is True
        assert denial["reason_code"] == "ACTION_DENIED_BY_POLICY"
        assert journal_lines(paths["journal"]) == ["write_note"]

        trace = _trace(paths["home"], denial["trace_id"], capsys)
        assert trace["integrity"]["valid"] is True
        assert trace["decision"]["outcome"] == "DENY"
        assert "execution_released" not in [event["event_type"] for event in trace["events"]]
        assert (
            f"protocol {HANDSHAKE_REVISION}" in trace["envelope"]["provenance"]["task_description"]
        )

        assert _run("policy", "explain", denial["trace_id"], "--home", str(paths["home"])) == 0
        explained = capsys.readouterr().out
        assert "ACTION_DENIED_BY_POLICY" in explained
        assert "never-delete" in explained

        suite = tmp_path / "atp-regression.yaml"
        assert (
            _run(
                "regression",
                "add",
                denial["trace_id"],
                "--suite",
                str(suite),
                "--home",
                str(paths["home"]),
                "--name",
                "delete stays denied by policy",
            )
            == 0
        )
        added = capsys.readouterr().out
        assert "ADDED delete stays denied by policy" in added
        assert "DENY / ACTION_DENIED_BY_POLICY" in added
        assert _run("test", str(suite), "--quiet", "--home", str(paths["home"])) == 0

        # The delegated capability still includes notes:destroy. Only the
        # declared rule changes. The pinned case must now fail closed as a
        # regression, not quietly start passing.
        _policy_file(paths["home"], deny_delete=False)
        assert _run("test", str(suite), "--home", str(paths["home"])) == 1
        failed = capsys.readouterr().out
        assert "0/1 passed" in failed or "failed" in failed.lower()
        assert "ALLOW" in failed
        assert "expected DENY" in failed


def test_handshake_revision_constants_match_the_pinned_sdk() -> None:
    """The installed MCP SDK separates handshake revisions from 2026-07-28.

    This pins the constants this repository was measured against. It is not
    evidence that the proxy implements the modern revision.
    """
    assert LATEST_HANDSHAKE_VERSION == HANDSHAKE_REVISION
    assert HANDSHAKE_REVISION in HANDSHAKE_PROTOCOL_VERSIONS
    assert "2026-07-28" not in HANDSHAKE_PROTOCOL_VERSIONS
    assert MODERN_PROTOCOL_VERSIONS == ("2026-07-28",)


@pytest.mark.parametrize("mode", ["auto", "2026-07-28"])
def test_modern_client_cannot_deliver_a_denied_delete(
    tmp_path: Path, mode: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A 2026-07-28 stdio client must still be unable to deliver a denied delete.

    Measured with mcp 2.2.0: ``mode='auto'`` does not fall back, and
    ``mode='2026-07-28'`` adopts that revision. The upstream hop inside the
    proxy remains an initialize handshake. This does not make the revision a
    supported product surface.
    """
    paths = _prepare(tmp_path, deny_delete=False)
    _config(
        paths["config"],
        transport="stdio",
        root=paths["root"],
        journal=paths["journal"],
        capabilities=["notes:write"],
    )

    async def body() -> dict[str, Any]:
        async with Client(_proxy_params(paths["config"], paths["home"]), mode=mode) as client:
            write_result = await client.call_tool("write_note", {"id": "todo", "text": "x"})
            delete_result = await client.call_tool("delete_note", {"id": "todo"})
            return {
                "protocol": client.protocol_version,
                "write_error": write_result.is_error,
                "delete_error": delete_result.is_error,
                "delete": delete_result.structured_content,
            }

    observed = anyio.run(body)
    assert observed["write_error"] is False
    assert observed["delete_error"] is True
    assert observed["delete"]["reason_code"] == "CAPABILITY_NOT_GRANTED"
    assert journal_lines(paths["journal"]) == ["write_note"]
    # mcp 2.2.0, 2026-10-29: Client mode "auto" and mode "2026-07-28" both
    # report 2026-07-28 against this stdio proxy, and the denied delete still
    # does not run. That is one tools/call boundary, not support for the
    # stateless revision (no HTTP serving, no MRTR, upstream still uses
    # initialize). The proxy records the upstream handshake revision.
    assert observed["protocol"] == "2026-07-28"
    trace = _trace(paths["home"], str(observed["delete"]["trace_id"]), capsys)
    assert f"protocol {HANDSHAKE_REVISION}" in trace["envelope"]["provenance"]["task_description"]

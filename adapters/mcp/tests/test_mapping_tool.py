"""The envelope's ``tool`` comes from the matched ``ToolMapping.tool``.

A declared rule whose ``applies_to.tool`` names a mapping's ``tool`` must be
enforced through the real ``atp mcp wrap`` proxy, and a config written by
``atp mcp init`` must keep stamping ``mcp.<server_name>`` exactly as before.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client

from atp_adapter_mcp.config import load_config
from atp_cli.home import AtpHome
from atp_cli.main import main

BANK_SERVER = """
import os
import sys

from mcp.server.mcpserver import MCPServer

JOURNAL = sys.argv[1]
server = MCPServer("bank")


@server.tool(name="send_money", description="Send money to a recipient.")
def send_money(recipient: str, amount: int) -> str:
    with open(JOURNAL, "a", encoding="utf-8") as handle:
        handle.write(f"send_money {recipient} {amount}\\n")
        handle.flush()
        os.fsync(handle.fileno())
    return f"sent {amount} to {recipient}"


if __name__ == "__main__":
    server.run("stdio")
"""


def _run(*argv: str) -> int:
    try:
        main(list(argv))
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _journal(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


async def _drive(
    config: Path, home: Path, calls: list[tuple[str, dict[str, Any]]]
) -> list[types.CallToolResult]:
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
            "enforce",
            "--log-level",
            "warning",
        ],
        env={**get_default_environment(), "ATP_HOME": str(home)},
    )
    out: list[types.CallToolResult] = []
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        for name, args in calls:
            out.append(await session.call_tool(name, args))
    return out


def test_rule_on_mapping_tool_is_enforced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server = tmp_path / "bank_server.py"
    server.write_text(BANK_SERVER, encoding="utf-8")
    journal = tmp_path / "journal.log"
    home = tmp_path / "home"
    AtpHome(home).ensure()
    policies = {
        "version": 1,
        "policy_sets": [
            {
                "version": "bank-v1",
                "description": "cap transfers on the logical tool",
                "rules": [
                    {
                        "id": "cap",
                        "applies_to": {"tool": "dojo.banking", "action": "send_money"},
                        "kind": "argument_max",
                        "argument": "amount",
                        "max": 100,
                    }
                ],
            }
        ],
    }
    (home / "policies.yaml").write_text(yaml.safe_dump(policies, sort_keys=False), "utf-8")
    config = tmp_path / "atp-mcp.yaml"
    cfg = {
        "server_name": "bank",
        "policy_set": "bank-v1",
        "principal": {"id": "local-user", "kind": "human"},
        "agent": {"id": "bank-agent", "kind": "agent"},
        "authority": {"capabilities": ["dojo.banking:send_money"], "resource_scope": ["acct:*"]},
        "upstream": {"command": sys.executable, "args": [str(server), str(journal)]},
        "tools": [
            {
                "mcp_tool": "send_money",
                "tool": "dojo.banking",
                "action": "send_money",
                "capability": "dojo.banking:send_money",
                "resource_template": "acct:{recipient}",
            }
        ],
    }
    config.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    within, over = anyio.run(
        _drive,
        config,
        home,
        [
            ("send_money", {"recipient": "alice", "amount": 50}),
            ("send_money", {"recipient": "mallory", "amount": 500}),
        ],
    )

    assert within.is_error is False, within.structured_content
    assert over.is_error is True
    denial = over.structured_content
    assert denial["reason_code"] == "ARGUMENT_EXCEEDS_LIMIT"
    assert _journal(journal) == ["send_money alice 50"], "denied call must not reach upstream"

    assert _run("trace", "show", denial["trace_id"], "--home", str(home), "--json") == 0
    trace = json.loads(capsys.readouterr().out)
    assert trace["envelope"]["tool"] == "dojo.banking"
    assert trace["integrity"]["valid"] is True


def test_init_written_config_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NOTES_DIR", str(notes))
    config_path = tmp_path / "atp-mcp.yaml"
    assert (
        _run(
            "mcp",
            "init",
            "--config",
            str(config_path),
            "--name",
            "notes",
            "--home",
            str(tmp_path / "home"),
            "--",
            sys.executable,
            "-m",
            "notes_mcp_server",
        )
        == 0
    )
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert raw["tools"], "init should map the discovered tools"
    assert {m["tool"] for m in raw["tools"]} == {"mcp.notes"}

    config = load_config(config_path)
    # Before this fix every envelope was stamped ProxyConfig.envelope_tool; an
    # init-written config must produce that same tool for every mapped call.
    assert config.envelope_tool == "mcp.notes"
    for mapping in config.tools:
        assert mapping.envelope_tool == config.envelope_tool


def test_wrap_refuses_mapping_onto_gateway_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The local gateway releases mapped tools to the proxy. A mapping that names
    a tool the gateway executes itself (``payments``) is refused at startup."""
    home = tmp_path / "home"
    AtpHome(home).ensure()
    config = tmp_path / "atp-mcp.yaml"
    cfg = {
        "server_name": "bank",
        "authority": {"capabilities": ["payments:send"], "resource_scope": ["acct:*"]},
        "upstream": {"command": sys.executable, "args": ["-c", "pass"]},
        "tools": [
            {
                "mcp_tool": "send_money",
                "tool": "payments",
                "action": "send_money",
                "capability": "payments:send",
                "resource_template": "acct:{recipient}",
            }
        ],
    }
    config.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    assert _run("mcp", "wrap", "--config", str(config), "--home", str(home)) == 2
    assert "gateway executes itself" in capsys.readouterr().err

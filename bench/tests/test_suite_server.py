"""Journaling MCP server over AgentDojo suites (stdio, real subprocess)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client

from atp_bench.dojo import SUITES, Call, load_suite
from atp_bench.suite_server import (
    READONLY,
    STATE_CHANGING,
    build_server,
    is_state_changing,
    read_journal,
)


def _params(suite: str, injection: str, journal: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=[
            "-m", "atp_bench.suite_server",
            "--suite", suite,
            "--injection-task", injection,
            "--journal", str(journal),
        ],
        env=get_default_environment(),
    )


def _drive(params: StdioServerParameters, steps):
    """Run ``steps(session)`` against a live server; return its result."""

    async def main():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await steps(session)

    return anyio.run(main)


def _text(result: types.CallToolResult) -> str:
    return "".join(b.text for b in result.content if isinstance(b, types.TextContent))


def test_lists_every_suite_tool(tmp_path):
    suite = load_suite("banking")

    async def steps(session):
        return await session.list_tools()

    listed = _drive(_params("banking", "none", tmp_path / "j.jsonl"), steps)
    assert {t.name for t in listed.tools} == set(suite.tool_names)
    send = next(t for t in listed.tools if t.name == "send_money")
    # Argument names come from AgentDojo's parameter models.
    assert {"recipient", "amount", "subject", "date"} <= set(send.input_schema["properties"])


def test_journals_before_executing(tmp_path):
    journal = tmp_path / "j.jsonl"

    async def steps(session):
        ok = await session.call_tool("get_iban", {})
        return ok

    result = _drive(_params("banking", "none", journal), steps)
    assert not result.is_error
    lines = journal.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [{"function": "get_iban", "args": {}}]
    assert read_journal(journal) == [Call("get_iban", {})]


def test_raising_tool_still_counts_as_reached(tmp_path):
    journal = tmp_path / "j.jsonl"
    suite = load_suite("banking")
    # update_scheduled_transaction on a missing id raises inside the AgentDojo function.
    env = suite.default_env()
    _, errored = suite.run(env, Call("update_scheduled_transaction", {"id": 987654, "amount": 1.0}))
    assert errored

    async def steps(session):
        raising = await session.call_tool(
            "update_scheduled_transaction", {"id": 987654, "amount": 1.0}
        )
        bad_args = await session.call_tool("send_money", {"nonsense": True})
        return raising, bad_args

    raising, bad_args = _drive(_params("banking", "none", journal), steps)
    assert raising.is_error and bad_args.is_error
    assert read_journal(journal) == [
        Call("update_scheduled_transaction", {"id": 987654, "amount": 1.0}),
        Call("send_money", {"nonsense": True}),
    ]


def test_journal_line_exists_while_function_runs(tmp_path, monkeypatch):
    """The line is on disk before the AgentDojo function is invoked."""
    suite = load_suite("banking")
    journal = tmp_path / "j.jsonl"
    seen: list[list[Call]] = []
    real_run = type(suite).run

    def spy(self, env, call):
        seen.append(read_journal(journal))
        return real_run(self, env, call)

    monkeypatch.setattr(type(suite), "run", spy)
    server = build_server(suite, None, journal)

    async def go():
        await server.call_tool("get_iban", {})

    anyio.run(go)
    assert seen == [[Call("get_iban", {})]]


def test_injection_goal_reaches_tool_output(tmp_path):
    suite = load_suite("banking")
    goal = suite.injection_goal("injection_task_0")
    env = suite.env_with_injection("injection_task_0")
    clean = suite.env_with_injection(None)
    assert goal in env.model_dump_json().replace("\n", "\n") or goal in json.dumps(
        env.model_dump()
    )
    assert goal not in json.dumps(clean.model_dump())

    async def steps(session):
        return await session.call_tool("get_most_recent_transactions", {})

    journal = tmp_path / "j.jsonl"
    result = _drive(_params("banking", "injection_task_0", journal), steps)
    assert not result.is_error
    assert " ".join(goal.split()) in " ".join(_text(result).split())
    assert read_journal(journal)[0].function == "get_most_recent_transactions"


@pytest.mark.parametrize("name", SUITES)
def test_every_injection_task_loads(name):
    suite = load_suite(name)
    for tid in suite.injection_task_ids():
        suite.env_with_injection(tid)


def test_every_tool_is_classified():
    for n in SUITES:
        s = load_suite(n)
        assert set(s.tool_names) == READONLY[n] | STATE_CHANGING[n]
        assert not (READONLY[n] & STATE_CHANGING[n])


def test_is_state_changing():
    assert is_state_changing("banking", "send_money")
    assert not is_state_changing("banking", "get_iban")
    with pytest.raises(KeyError):
        is_state_changing("banking", "no_such_tool")

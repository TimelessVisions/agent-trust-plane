"""Journaling MCP server over AgentDojo suites (stdio, real subprocess)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anyio
import pytest
from atp_bench.dojo import SUITES, Call, load_suite
from atp_bench.suite_server import (
    READONLY,
    STATE_CHANGING,
    build_server,
    is_state_changing,
    read_journal,
)
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client


def _params(suite: str, injection: str, journal: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "atp_bench.suite_server",
            "--suite",
            suite,
            "--injection-task",
            injection,
            "--journal",
            str(journal),
        ],
        env=get_default_environment(),
    )


def _drive(params: StdioServerParameters, steps):
    """Run ``steps(session)`` against a live server; return its result."""

    async def main():
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await steps(session)

    return anyio.run(main)


def _text(result: types.CallToolResult) -> str:
    return "".join(b.text for b in result.content if isinstance(b, types.TextContent))


@pytest.mark.parametrize("name", SUITES)
def test_lists_every_suite_tool(tmp_path, name):
    suite = load_suite(name)

    async def steps(session):
        return await session.list_tools()

    listed = _drive(_params(name, "none", tmp_path / "j.jsonl"), steps)
    assert {t.name for t in listed.tools} == set(suite.tool_names)
    # Argument names come from AgentDojo's parameter models, for every tool.
    want = {n: set(schema.get("properties", {})) for n, _, schema in suite.tool_specs()}
    got = {t.name: set(t.input_schema.get("properties", {})) for t in listed.tools}
    assert got == want
    if name == "banking":
        send = next(t for t in listed.tools if t.name == "send_money")
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


def _strings(obj) -> list[str]:
    """Every string value nested anywhere in a dumped model."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, (list, tuple, set)):
        return [s for v in obj for s in _strings(v)]
    return []


def test_injection_goal_reaches_tool_output(tmp_path):
    suite = load_suite("banking")
    goal = suite.injection_goal("injection_task_0")
    env = suite.env_with_injection("injection_task_0")
    clean = suite.env_with_injection(None)
    # Compare against the raw string values: JSON escaping would hide a goal with newlines.
    assert any(goal in v for v in _strings(env.model_dump()))
    assert not any(goal in v for v in _strings(clean.model_dump()))

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


# Injection tasks whose ground truth is empty in AgentDojo v1.2.1 (nothing to journal).
KNOWN_EMPTY_GROUND_TRUTH = {
    ("workspace", f"injection_task_{i}") for i in (6, 7, 8, 9, 10, 11, 12, 13)
} | {("travel", "injection_task_6")}


@pytest.mark.parametrize("name", SUITES)
def test_every_injection_ground_truth_has_a_state_changing_call(name):
    suite = load_suite(name)
    env = suite.default_env()
    for tid in suite.injection_task_ids():
        calls = suite.injection_ground_truth(tid, env)
        if (name, tid) in KNOWN_EMPTY_GROUND_TRUTH:
            assert not calls, f"{name}/{tid} is no longer empty; update the list"
            continue
        assert any(is_state_changing(name, c.function) for c in calls), (
            f"{name}/{tid} ground truth {[c.function for c in calls]} has no state-changing call"
        )


def test_journal_write_failure_runs_nothing(tmp_path, monkeypatch):
    """If the journal line cannot be written, the AgentDojo function must not run."""
    import atp_bench.suite_server as mod

    suite = load_suite("banking")
    ran: list[Call] = []
    real_run = type(suite).run

    def spy(self, env, call):
        ran.append(call)
        return real_run(self, env, call)

    def fail(journal, call):
        raise OSError("disk full")

    monkeypatch.setattr(type(suite), "run", spy)
    monkeypatch.setattr(mod, "_journal_append", fail)
    server = build_server(suite, None, tmp_path / "j.jsonl")

    async def go():
        return await server.call_tool("send_money", {
            "recipient": "GB29NWBK60161331926819", "amount": 1.0,
            "subject": "x", "date": "2022-01-01",
        })  # fmt: skip

    with pytest.raises(Exception, match="Error executing tool send_money") as info:
        anyio.run(go)
    # The client gets an error result and no journal line; the runner's partial-journal guard
    # (test_run.py::test_partial_journal_is_inconclusive) then makes the item INCONCLUSIVE.
    assert isinstance(info.value.__cause__, OSError)
    assert "disk full" in str(info.value.__cause__)
    assert ran == []
    assert read_journal(tmp_path / "j.jsonl") == []


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_http_mode_journals_like_stdio(tmp_path):
    """``--http PORT`` serves Streamable HTTP at /mcp and writes the same journal as stdio."""
    import subprocess
    import time

    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    async def steps(session):
        tools = await session.list_tools()
        ok = await session.call_tool("get_iban", {})
        raising = await session.call_tool(
            "update_scheduled_transaction", {"id": 987654, "amount": 1.0}
        )
        bad_args = await session.call_tool("send_money", {"nonsense": True})
        return {t.name for t in tools.tools}, ok.is_error, raising.is_error, bad_args.is_error

    stdio_journal = tmp_path / "stdio.jsonl"
    stdio_out = _drive(_params("banking", "injection_task_0", stdio_journal), steps)

    http_journal = tmp_path / "http.jsonl"
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "atp_bench.suite_server", "--suite", "banking",
         "--injection-task", "injection_task_0", "--journal", str(http_journal),
         "--http", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        deadline = time.monotonic() + 180
        while True:
            assert proc.poll() is None, proc.stderr.read().decode(errors="replace")
            try:
                httpx2.get(url, timeout=2.0)
                break
            except httpx2.TransportError:
                assert time.monotonic() < deadline, "HTTP suite server did not come up"
                time.sleep(0.5)

        async def main():
            async with (
                streamable_http_client(url) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                return await steps(session)

        http_out = anyio.run(main)
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    assert http_out == stdio_out
    assert stdio_out[1:] == (False, True, True)
    assert http_journal.read_text(encoding="utf-8") == stdio_journal.read_text(encoding="utf-8")
    assert [c.function for c in read_journal(http_journal)] == [
        "get_iban", "update_scheduled_transaction", "send_money",
    ]  # fmt: skip

"""Journaling MCP server over one AgentDojo suite (stdio, or Streamable HTTP at /mcp).

Every tool call is appended to a JSONL journal and flushed to disk BEFORE the
AgentDojo function runs. A call that raises, or that carries bad arguments, still
leaves its line: it reached the upstream. A call denied by a gate in front of this
server leaves no line. The journal is the ground truth for "did it reach upstream".

With ``--deliveries`` the server also records, after each call has run and the environment was
dumped, one line per call: ``seq``, ``function`` and whether the result text carried the
injection task's GOAL (``contained_injection``). A journal longer than the deliveries file
means a call was interrupted between its journal line and its record: the run's state cannot
be trusted. That file is how a live run proves the agent was actually shown the injection.

Tool schemas come from AgentDojo's own parameter models. MCP-level argument
validation is deliberately permissive so that validation happens after journaling,
inside AgentDojo.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from pathlib import Path
from typing import Any

import yaml
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from pydantic import ConfigDict

from atp_bench.dojo import SUITES, Call, DojoSuite, load_suite

_DATA = Path(__file__).resolve().parents[2] / "data" / "readonly_tools.yaml"


def _load_classification() -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    raw = yaml.safe_load(_DATA.read_text(encoding="utf-8"))
    return (
        {s: frozenset(v["readonly"]) for s, v in raw.items()},
        {s: frozenset(v["state_changing"]) for s, v in raw.items()},
    )


READONLY, STATE_CHANGING = _load_classification()


def is_state_changing(suite: str, tool: str) -> bool:
    if tool in STATE_CHANGING[suite]:
        return True
    if tool in READONLY[suite]:
        return False
    raise KeyError(f"{tool!r} is not classified for suite {suite!r}")


def _journal_append(journal: Path, call: Call) -> None:
    journal.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"function": call.function, "args": call.args}, sort_keys=True)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _deliveries_append(path: Path, seq: int, function: str, contained_injection: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {"seq": seq, "function": function, "contained_injection": contained_injection},
        sort_keys=True,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_deliveries(path: Path) -> list[dict[str, Any]]:
    """The deliveries sidecar as written by ``--deliveries`` ([] if the file does not exist)."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            rows.append(
                {
                    "seq": int(obj["seq"]),
                    "function": str(obj["function"]),
                    "contained_injection": bool(obj["contained_injection"]),
                }
            )
    return rows


def _normalised(text: str) -> str:
    # AgentDojo renders results as YAML, which folds long lines: compare on single spaces.
    return " ".join(text.split())


def _write_env_dump(path: Path, suite: DojoSuite, env: Any) -> None:
    """Atomically replace ``path`` with the environment as JSON (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(suite.dump_env(env))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def read_journal(path: Path) -> list[Call]:
    if not path.exists():
        return []
    calls: list[Call] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            calls.append(Call(function=obj["function"], args=obj["args"]))
    return calls


class _AnyArgs(ArgModelBase):
    """Accept whatever the client sends; AgentDojo validates after the journal write."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


def build_server(
    suite: DojoSuite,
    injection_task: str | None,
    journal: Path,
    dump_env: Path | None = None,
    deliveries: Path | None = None,
) -> MCPServer:
    """``dump_env``: keep the environment JSON on disk, written at start and after every call.

    The environment changes only inside a call, so the file is always the final environment:
    a live agent may kill the server without a clean shutdown, and nothing waits for one. Its
    existence also proves the server started."""
    env = suite.env_with_injection(injection_task)
    goal = _normalised(suite.injection_goal(injection_task)) if injection_task else ""
    seq = 0
    lock = threading.Lock()  # AgentDojo functions mutate one shared env
    if dump_env is not None:
        _write_env_dump(dump_env, suite, env)
    server = MCPServer(
        f"atp-bench-{suite.name}",
        instructions=f"AgentDojo {suite.name} suite. Every call is journaled before it runs.",
    )

    def make_handler(name: str):
        def handler(**kwargs: Any) -> str:
            nonlocal seq
            call = Call(function=name, args=kwargs)
            with lock:
                _journal_append(journal, call)
                text, errored = suite.run(env, call)
                if dump_env is not None:
                    _write_env_dump(dump_env, suite, env)
                if deliveries is not None:
                    seq += 1
                    carried = bool(goal) and goal[:80] in _normalised(text)
                    _deliveries_append(deliveries, seq, name, carried)
            if errored:
                raise ToolError(text)
            return text

        return handler

    for name, description, schema in suite.tool_specs():
        tool = Tool(
            fn=make_handler(name),
            name=name,
            description=description,
            parameters=schema,
            fn_metadata=FuncMetadata(arg_model=_AnyArgs),
            is_async=False,
        )
        server._tool_manager._tools[name] = tool
    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atp_bench.suite_server")
    parser.add_argument("--suite", required=True, choices=SUITES)
    parser.add_argument("--injection-task", required=True, help="injection task id, or 'none'")
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument(
        "--dump-env",
        type=Path,
        metavar="PATH",
        help="keep the environment as JSON at PATH: written at start and after every call",
    )
    parser.add_argument(
        "--deliveries",
        type=Path,
        metavar="PATH",
        help="append one line per completed call: whether its result carried the injection",
    )
    parser.add_argument(
        "--http",
        type=int,
        metavar="PORT",
        help="serve Streamable HTTP at http://127.0.0.1:PORT/mcp instead of stdio",
    )
    args = parser.parse_args(argv)
    injection = None if args.injection_task == "none" else args.injection_task
    server = build_server(
        load_suite(args.suite), injection, args.journal, args.dump_env, args.deliveries
    )
    if args.http is None:
        server.run(transport="stdio")
    else:
        # Same server, same handlers: the journal is written exactly as in stdio mode.
        server.run(
            transport="streamable-http",
            host="127.0.0.1",
            port=args.http,
            streamable_http_path="/mcp",
        )


if __name__ == "__main__":
    main()

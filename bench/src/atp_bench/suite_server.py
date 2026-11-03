"""Journaling MCP server over one AgentDojo suite (stdio).

Every tool call is appended to a JSONL journal and flushed to disk BEFORE the
AgentDojo function runs. A call that raises, or that carries bad arguments, still
leaves its line: it reached the upstream. A call denied by a gate in front of this
server leaves no line. The journal is the ground truth for "did it reach upstream".

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


def build_server(suite: DojoSuite, injection_task: str | None, journal: Path) -> MCPServer:
    env = suite.env_with_injection(injection_task)
    lock = threading.Lock()  # AgentDojo functions mutate one shared env
    server = MCPServer(
        f"atp-bench-{suite.name}",
        instructions=f"AgentDojo {suite.name} suite. Every call is journaled before it runs.",
    )

    def make_handler(name: str):
        def handler(**kwargs: Any) -> str:
            call = Call(function=name, args=kwargs)
            with lock:
                _journal_append(journal, call)
                text, errored = suite.run(env, call)
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
    args = parser.parse_args(argv)
    injection = None if args.injection_task == "none" else args.injection_task
    build_server(load_suite(args.suite), injection, args.journal).run(transport="stdio")


if __name__ == "__main__":
    main()

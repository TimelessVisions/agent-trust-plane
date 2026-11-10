"""Baseline: the agent talks straight to the suite server. Nothing is ever blocked."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mcp import StdioServerParameters, types
from mcp.client.stdio import get_default_environment

from atp_bench.annotations import Annotation
from atp_bench.dojo import DojoSuite
from atp_bench.layers.base import CallOutcome, Session, StdioMcpSession, result_text


def suite_server_argv(suite: str, injection_task: str | None, journal: Path) -> list[str]:
    """argv for the journaling suite server; every path absolute."""
    return [
        sys.executable,
        "-m",
        "atp_bench.suite_server",
        "--suite",
        suite,
        "--injection-task",
        injection_task or "none",
        "--journal",
        str(Path(journal).resolve()),
    ]


def _classify(result: types.CallToolResult) -> CallOutcome:
    # An upstream tool error still reached the upstream, so it is ALLOWED.
    return CallOutcome("ALLOWED", result_text(result)[:300])


class OpenLayer:
    name = "open"

    def __init__(self, timeout_s: float = 30.0) -> None:
        self.timeout_s = timeout_s

    @contextmanager
    def open(
        self,
        suite: DojoSuite,
        annotation: Annotation,
        injection_task: str | None,
        journal: Path,
        workdir: Path,
    ) -> Iterator[Session]:
        argv = suite_server_argv(suite.name, injection_task, journal)
        params = StdioServerParameters(
            command=argv[0], args=argv[1:], env=get_default_environment()
        )
        with StdioMcpSession(params, _classify, call_timeout_s=self.timeout_s) as session:
            yield session

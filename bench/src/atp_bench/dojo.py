"""Thin adapter over AgentDojo. The only module allowed to import ``agentdojo``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentdojo.task_suite.load_suites import get_suite

SUITES = ("workspace", "travel", "banking", "slack")
BENCHMARK_VERSION = "v1.2.1"


@dataclass(frozen=True)
class Call:
    function: str
    args: dict[str, Any]


def _calls(raw) -> list[Call]:
    return [Call(function=c.function, args=dict(c.args)) for c in raw]


class DojoSuite:
    def __init__(self, suite) -> None:
        self._suite = suite
        self.name: str = suite.name
        self.tool_names: tuple[str, ...] = tuple(t.name for t in suite.tools)

    def user_task_ids(self) -> list[str]:
        return sorted(self._suite.user_tasks)

    def injection_task_ids(self) -> list[str]:
        return sorted(self._suite.injection_tasks)

    def default_env(self):
        return self._suite.load_and_inject_default_environment(
            self._suite.get_injection_vector_defaults()
        )

    def user_ground_truth(self, task_id: str, env) -> list[Call]:
        return _calls(self._suite.user_tasks[task_id].ground_truth(env))

    def injection_ground_truth(self, task_id: str, env) -> list[Call]:
        return _calls(self._suite.injection_tasks[task_id].ground_truth(env))

    def prompt(self, task_id: str) -> str:
        return self._suite.user_tasks[task_id].PROMPT


def load_suite(name: str) -> DojoSuite:
    if name not in SUITES:
        raise ValueError(f"unknown suite {name!r}; expected one of {SUITES}")
    return DojoSuite(get_suite(BENCHMARK_VERSION, name))

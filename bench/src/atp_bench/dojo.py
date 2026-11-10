"""Thin adapter over AgentDojo. The only module allowed to import ``agentdojo``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from agentdojo.functions_runtime import FunctionsRuntime
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
        self._runtime = FunctionsRuntime(suite.tools)

    def tool_specs(self) -> list[tuple[str, str, dict[str, Any]]]:
        """(name, description, JSON input schema) for every tool, from AgentDojo's models."""
        return [
            (t.name, t.description, t.parameters.model_json_schema()) for t in self._suite.tools
        ]

    def injection_goal(self, task_id: str) -> str:
        return self._suite.injection_tasks[task_id].GOAL

    def env_with_injection(self, injection_task_id: str | None):
        """Default env; with a task id, every injection vector carries that task's GOAL."""
        if injection_task_id is None:
            return self.default_env()
        goal = self.injection_goal(injection_task_id)
        vectors = self._suite.get_injection_vector_defaults()
        return self._suite.load_and_inject_default_environment({v: goal for v in vectors})

    def run(self, env, call: Call) -> tuple[str, bool]:
        """Execute ``call`` via AgentDojo's FunctionsRuntime: (result text, errored)."""
        result, error = self._runtime.run_function(env, call.function, call.args)
        if error is not None:
            return error, True
        return tool_result_to_str(result), False

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

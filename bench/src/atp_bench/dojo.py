"""Thin adapter over AgentDojo. The only module allowed to import ``agentdojo``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.types import text_content_block_from_string

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

    def dump_env(self, env) -> str:
        """The environment as JSON text (what ``suite_server --dump-env`` writes)."""
        return env.model_dump_json()

    def load_env(self, text: str):
        """Inverse of ``dump_env``: the suite's own environment type, validated."""
        return self._suite.environment_type.model_validate_json(text)

    @staticmethod
    def _traces(calls: Sequence[Call]) -> list[FunctionCall]:
        return [FunctionCall(function=c.function, args=dict(c.args)) for c in calls]

    def utility(
        self,
        task_id: str,
        output: str,
        pre_env,
        post_env,
        traces: Sequence[Call] = (),
    ) -> bool:
        """AgentDojo's own user-task check (trace-based when the task defines one)."""
        return self._suite._check_user_task_utility(
            self._suite.user_tasks[task_id],
            [text_content_block_from_string(output)],
            pre_env,
            post_env,
            self._traces(traces),
        )

    def security(
        self,
        injection_task_id: str,
        output: str,
        pre_env,
        post_env,
        traces: Sequence[Call] = (),
    ) -> bool:
        """AgentDojo's own injection-task check: True means the attack SUCCEEDED."""
        return self._suite._check_injection_task_security(
            self._suite.injection_tasks[injection_task_id],
            [text_content_block_from_string(output)],
            pre_env,
            post_env,
            self._traces(traces),
        )


def load_suite(name: str) -> DojoSuite:
    if name not in SUITES:
        raise ValueError(f"unknown suite {name!r}; expected one of {SUITES}")
    return DojoSuite(get_suite(BENCHMARK_VERSION, name))

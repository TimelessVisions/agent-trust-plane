"""Scenario contract and the checker used to write them."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from atp_adapter_http import TrustPlaneClient
from atp_evals.model import Check
from finance_agent import DelegationGraph, SimulatedAgent


@dataclass
class EvalContext:
    client: TrustPlaneClient
    graph: DelegationGraph
    brain: SimulatedAgent
    checks: list[Check] = field(default_factory=list)
    trace_ids: list[str] = field(default_factory=list)
    primary_trace_id: str | None = None
    decision: dict[str, Any] | None = None

    # ------------------------------------------------------------- checking
    def expect(self, name: str, observed: Any, expected: Any, detail: str | None = None) -> bool:
        ok = bool(observed == expected)
        self.checks.append(
            Check(name=name, passed=ok, expected=expected, observed=observed, detail=detail)
        )
        return ok

    def expect_true(self, name: str, condition: bool, detail: str | None = None) -> bool:
        self.checks.append(
            Check(name=name, passed=condition, expected=True, observed=condition, detail=detail)
        )
        return condition

    def note_trace(self, trace_id: str, *, primary: bool = False) -> None:
        if trace_id not in self.trace_ids:
            self.trace_ids.append(trace_id)
        if primary or self.primary_trace_id is None:
            self.primary_trace_id = trace_id

    def ledger_size(self) -> int:
        return len(self.client.ledger())


@dataclass(frozen=True)
class EvalScenario:
    eval_id: str
    title: str
    threat: str
    description: str
    run: Callable[[EvalContext], str]
    """Runs the scenario and returns a one-paragraph explanation of what was proven."""

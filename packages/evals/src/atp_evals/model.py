from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvalStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class Check(BaseModel):
    """One concrete assertion an eval made against the real system."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    passed: bool
    expected: Any = None
    observed: Any = None
    detail: str | None = None


class EvalResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    eval_id: str
    title: str
    threat: str
    description: str
    status: EvalStatus
    checks: tuple[Check, ...]
    explanation: str
    trace_ids: tuple[str, ...] = ()
    primary_trace_id: str | None = None
    decision: dict[str, Any] | None = Field(
        default=None, description="The headline decision this eval produced, if any."
    )
    error: str | None = None
    duration_ms: int


class EvalReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    started_at: datetime
    finished_at: datetime
    gateway: dict[str, Any]
    results: tuple[EvalResult, ...]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status is EvalStatus.PASS)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def all_passed(self) -> bool:
        return self.passed == self.total

    def summary(self) -> dict[str, Any]:
        return {"passed": self.passed, "total": self.total, "all_passed": self.all_passed}

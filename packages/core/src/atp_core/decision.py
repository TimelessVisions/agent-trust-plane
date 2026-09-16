"""Structured authorization decisions.

A decision is never "safe"/"unsafe". It is an outcome, a reason code, the
policy that produced it, and the constraints that were checked, so that a
human or a test can reconstruct exactly why the outcome happened.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atp_core.authority import EffectiveAuthority
from atp_core.ids import new_id
from atp_core.reasons import ReasonCode
from atp_core.timeutil import utcnow


class DecisionOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class PolicyRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Stable policy id, e.g. payments.vendor.max_amount")
    version: str = Field(description="Policy version, e.g. v1")

    @property
    def qualified(self) -> str:
        return f"{self.id}.{self.version}"


class ConstraintEvaluation(BaseModel):
    """One concrete comparison a policy made, e.g. requested 12500 vs limit 1000."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    requested: Any = None
    limit: Any = None
    satisfied: bool
    detail: str | None = None


class PolicyEvaluation(BaseModel):
    """Result of evaluating one policy against one envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy: PolicyRef
    outcome: DecisionOutcome
    reason_code: ReasonCode
    message: str
    constraints: tuple[ConstraintEvaluation, ...] = ()


class ApprovalRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    approver_role: str
    reason: str


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(default_factory=lambda: new_id("dec"))
    trace_id: str
    envelope_id: str
    action_hash: str
    decided_at: datetime = Field(default_factory=utcnow)

    outcome: DecisionOutcome
    reason_code: ReasonCode
    explanation: str = Field(description="Human-readable, derived from the matched policy.")
    matched_policy: PolicyRef | None = Field(
        default=None,
        description="The policy that determined the outcome. None only for ALLOW.",
    )
    policy_set_version: str
    evaluations: tuple[PolicyEvaluation, ...] = Field(
        description="Every applicable policy, in evaluation order, including passes."
    )
    effective_authority: EffectiveAuthority | None = Field(
        default=None,
        description="Resolved authority snapshot. None when delegation resolution failed.",
    )
    approval: ApprovalRequirement | None = None
    replay_of: str | None = Field(
        default=None,
        description="When this decision was produced by replay, the original decision id.",
    )

    @property
    def is_allow(self) -> bool:
        return self.outcome is DecisionOutcome.ALLOW

    def violations(self) -> list[PolicyEvaluation]:
        return [e for e in self.evaluations if e.outcome is not DecisionOutcome.ALLOW]

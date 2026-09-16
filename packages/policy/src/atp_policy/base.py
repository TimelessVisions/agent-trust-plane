"""Policy contract.

A policy is a small, named, versioned object with two methods. It never
raises to signal a denial; it returns a typed evaluation so the engine can
record every result, including passes, in the trace.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from atp_core import (
    ActionEnvelope,
    ConstraintEvaluation,
    DecisionOutcome,
    EffectiveAuthority,
    PolicyEvaluation,
    PolicyRef,
    ReasonCode,
)
from atp_policy.directory import VendorDirectory


@dataclass(frozen=True)
class PolicyContext:
    """Everything a policy is allowed to look at.

    A plain dataclass rather than a pydantic model: it is an in-process value
    that carries a Protocol-typed directory, never a wire object.
    """

    envelope: ActionEnvelope
    vendors: VendorDirectory
    now: datetime
    authority: EffectiveAuthority | None = None
    """None when delegation resolution failed."""
    resolution_error: tuple[ReasonCode, str] | None = None


class Policy(ABC):
    id: str
    version: str
    description: str

    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(id=self.id, version=self.version)

    @abstractmethod
    def applies_to(self, ctx: PolicyContext) -> bool: ...

    @abstractmethod
    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation: ...

    # Helpers so policies read declaratively.
    def allow(
        self, message: str, constraints: tuple[ConstraintEvaluation, ...] = ()
    ) -> PolicyEvaluation:
        return PolicyEvaluation(
            policy=self.ref,
            outcome=DecisionOutcome.ALLOW,
            reason_code=ReasonCode.ALLOWED,
            message=message,
            constraints=constraints,
        )

    def deny(
        self,
        reason_code: ReasonCode,
        message: str,
        constraints: tuple[ConstraintEvaluation, ...] = (),
    ) -> PolicyEvaluation:
        return PolicyEvaluation(
            policy=self.ref,
            outcome=DecisionOutcome.DENY,
            reason_code=reason_code,
            message=message,
            constraints=constraints,
        )

    def require_approval(
        self,
        reason_code: ReasonCode,
        message: str,
        constraints: tuple[ConstraintEvaluation, ...] = (),
    ) -> PolicyEvaluation:
        return PolicyEvaluation(
            policy=self.ref,
            outcome=DecisionOutcome.REQUIRE_APPROVAL,
            reason_code=reason_code,
            message=message,
            constraints=constraints,
        )


class PolicySet(BaseModel):
    """An ordered, versioned bundle of policies. The version is what replay
    lets you vary."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    version: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    description: str
    policies: tuple[Policy, ...]

    def refs(self) -> list[PolicyRef]:
        return [p.ref for p in self.policies]

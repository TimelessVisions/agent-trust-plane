"""Wire schemas for the gateway API that are not already domain models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atp_audit import EventType
from atp_core import ActionEnvelope, PolicyRef


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: ActionEnvelope
    execution_grant: str | None = Field(
        default=None,
        description="The signed grant returned by /authorize. Required for execution.",
    )


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_set_version: str | None = Field(
        default=None, description="Policy set to replay under. Defaults to the active set."
    )


class TraceEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    actor: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)


class PolicySetView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    description: str
    is_default: bool
    policies: list[PolicyRef]
    policy_descriptions: dict[str, str]


class ErrorBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason_code: str
    message: str


class HealthView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    default_policy_set: str
    grant_ttl_seconds: int
    tools: list[str]
    signing_key_fingerprint: str

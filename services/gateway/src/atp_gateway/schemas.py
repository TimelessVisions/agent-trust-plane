"""Wire schemas for the gateway API that are not already domain models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atp_audit import EventType
from atp_core import ActionEnvelope, PolicyRef, PrincipalRef


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
    """Agent-side provenance. There is no ``actor`` field: the actor is the
    authenticated agent, always."""

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)


class CredentialIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: PrincipalRef
    label: str = Field(min_length=1, max_length=200)
    expires_at: datetime | None = None


class CredentialIssued(BaseModel):
    """Returned exactly once. The token is not stored and cannot be retrieved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_id: str
    agent: PrincipalRef
    label: str
    issued_at: datetime
    expires_at: datetime | None
    token: str


class CredentialView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_id: str
    agent: PrincipalRef
    label: str
    issued_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


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

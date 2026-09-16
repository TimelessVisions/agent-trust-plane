from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atp_core import AuthorityConstraints, PrincipalRef, ensure_aware, new_id, utcnow
from atp_identity.scope import validate_pattern

_IDENT = r"^[A-Za-z0-9._:-]+$"


class DelegationGrant(BaseModel):
    """One link in a delegation chain.

    A grant says: ``grantor`` gives ``grantee`` the right to exercise
    ``capabilities`` over ``resource_scope`` within ``constraints`` until
    ``expires_at``, and derives that right from ``parent_grant_id`` (or from
    the grantor's own human authority when ``parent_grant_id`` is None).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    grant_id: str = Field(default_factory=lambda: new_id("grt"))
    label: str = Field(max_length=200, description="Human-readable purpose of the grant.")

    grantor: PrincipalRef
    grantee: PrincipalRef
    parent_grant_id: str | None = Field(
        default=None,
        description="None only for a root grant, which must be issued by a human to itself.",
    )

    capabilities: frozenset[str] = Field(min_length=1)
    resource_scope: tuple[str, ...] = Field(min_length=1)
    constraints: AuthorityConstraints = Field(default_factory=AuthorityConstraints)

    issued_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    revoked_at: datetime | None = None

    @field_validator("capabilities")
    @classmethod
    def _validate_caps(cls, caps: frozenset[str]) -> frozenset[str]:
        import re

        for cap in caps:
            if not re.fullmatch(_IDENT, cap):
                raise ValueError(f"invalid capability identifier: {cap!r}")
        return caps

    @field_validator("resource_scope")
    @classmethod
    def _validate_scope(cls, scope: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(validate_pattern(p) for p in scope)

    @field_validator("expires_at", "issued_at", "revoked_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return ensure_aware(value) if value is not None else None

    @property
    def is_root(self) -> bool:
        return self.parent_grant_id is None

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or utcnow()) >= self.expires_at

    def is_revoked(self) -> bool:
        return self.revoked_at is not None


class DelegationRequest(BaseModel):
    """What a caller submits to create a grant. The service fills in ids and
    validates the request against the parent before it becomes a grant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(max_length=200)
    grantor: PrincipalRef
    grantee: PrincipalRef
    parent_grant_id: str | None = None
    capabilities: frozenset[str] = Field(min_length=1)
    resource_scope: tuple[str, ...] = Field(min_length=1)
    constraints: AuthorityConstraints = Field(default_factory=AuthorityConstraints)
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)

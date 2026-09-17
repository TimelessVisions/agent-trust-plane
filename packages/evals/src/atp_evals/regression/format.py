"""The regression suite file format (YAML or JSON).

A suite pins *authorization decisions*: for a declared delegation graph and a
set of recorded actions, the gateway must keep returning the expected
outcome and reason code under a given policy set. Nothing in a suite can
execute anything: the runner only calls ``/authorize``.

Every model here uses ``extra="forbid"`` and bounded fields because suites
are often produced from recorded traces, and a trace is untrusted input.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from atp_core import DecisionOutcome, Money, PrincipalRef

_ALIAS = r"^[A-Za-z0-9._-]{1,64}$"
_IDENT = r"^[A-Za-z0-9._:-]+$"
_SCOPE = r"^(\*|[A-Za-z0-9._-]+:(\*|[A-Za-z0-9._-]+))$"
_DURATION = re.compile(r"^(\d+)([smhd])$")
SUITE_VERSION = 1


def parse_duration(text: str) -> timedelta:
    m = _DURATION.match(text)
    if not m:
        raise ValueError(f"duration must look like 30d, 12h, 15m or 90s: {text!r}")
    n, unit = int(m.group(1)), m.group(2)
    return {
        "s": timedelta(seconds=n),
        "m": timedelta(minutes=n),
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
    }[unit]


class GrantSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_ALIAS, description="Alias used by cases and child grants.")
    label: str = Field(default="", max_length=200)
    grantor: str = Field(pattern=_ALIAS, description="Principal alias.")
    grantee: str = Field(pattern=_ALIAS)
    parent: str | None = Field(default=None, pattern=_ALIAS)
    capabilities: tuple[str, ...] = Field(min_length=1)
    resource_scope: tuple[str, ...] = Field(min_length=1)
    max_amount: Money | None = None
    currencies: tuple[str, ...] | None = None
    expires_in: str = Field(default="1d", pattern=r"^\d+[smhd]$")

    @field_validator("capabilities")
    @classmethod
    def _idents(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for v in values:
            if not re.fullmatch(_IDENT, v):
                raise ValueError(f"invalid capability: {v!r}")
        return values

    @field_validator("resource_scope")
    @classmethod
    def _scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for v in values:
            if not re.fullmatch(_SCOPE, v):
                raise ValueError(f"invalid resource pattern: {v!r}")
        return values


class DelegationSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    principals: dict[str, PrincipalRef] = Field(min_length=1)
    grants: tuple[GrantSpec, ...] = Field(min_length=1)

    @field_validator("principals")
    @classmethod
    def _aliases(cls, value: dict[str, PrincipalRef]) -> dict[str, PrincipalRef]:
        for alias in value:
            if not re.fullmatch(_ALIAS, alias):
                raise ValueError(f"invalid principal alias: {alias!r}")
        return value


class Expectation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: DecisionOutcome
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z_]{3,80}$")
    matched_policy: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9._-]+$", description="e.g. payments.vendor.max_amount.v1"
    )


class Source(BaseModel):
    """Where a case came from. Informational only; never trusted for anything."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")
    recorded_at: str | None = Field(default=None, max_length=40)
    gateway: str | None = Field(default=None, max_length=200)
    policy_set: str | None = Field(default=None, max_length=64)


class CaseSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._:/'()-]{0,119}$")
    description: str = Field(default="", max_length=1000)
    agent: str = Field(pattern=_ALIAS)
    principal: str = Field(pattern=_ALIAS)
    delegation: str = Field(pattern=_ALIAS, description="Grant alias the agent acts under.")
    capability: str = Field(pattern=_IDENT, max_length=128)
    tool: str = Field(pattern=_IDENT, max_length=64)
    action: str = Field(pattern=_IDENT, max_length=64)
    resource: str = Field(pattern=_IDENT, max_length=256)
    arguments: dict[str, Any] = Field(default_factory=dict)
    expect: Expectation
    source: Source | None = None

    @field_validator("arguments")
    @classmethod
    def _bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        from atp_core import canonical_json

        if len(canonical_json(value)) > 16 * 1024:
            raise ValueError("arguments exceed 16 KiB")
        return value


class Suite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(default=SUITE_VERSION, ge=1, le=1)
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=2000)
    policy_set: str = Field(default="payments-v2", pattern=r"^[A-Za-z0-9._-]+$")
    delegations: DelegationSpec
    cases: tuple[CaseSpec, ...] = Field(min_length=1)

    def validate_references(self) -> None:
        principals = set(self.delegations.principals)
        grants = {g.id for g in self.delegations.grants}
        seen: set[str] = set()
        for g in self.delegations.grants:
            if g.grantor not in principals or g.grantee not in principals:
                raise ValueError(f"grant {g.id}: unknown principal alias")
            if g.parent is not None and g.parent not in seen:
                raise ValueError(f"grant {g.id}: parent {g.parent!r} must be declared earlier")
            seen.add(g.id)
        names: set[str] = set()
        for c in self.cases:
            if c.name in names:
                raise ValueError(f"duplicate case name: {c.name!r}")
            names.add(c.name)
            if c.agent not in principals or c.principal not in principals:
                raise ValueError(f"case {c.name!r}: unknown principal alias")
            if c.delegation not in grants:
                raise ValueError(f"case {c.name!r}: unknown delegation alias {c.delegation!r}")


def load_suite(path: str | Path) -> Suite:
    p = Path(path)
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{p}: expected a mapping at top level")
    suite = Suite.model_validate(raw)
    suite.validate_references()
    return suite


def dump_suite(suite: Suite, path: str | Path) -> None:
    data = suite.model_dump(mode="json", exclude_none=True)
    Path(path).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

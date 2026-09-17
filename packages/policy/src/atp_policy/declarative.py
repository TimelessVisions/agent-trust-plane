"""Declarative policy sets loaded from YAML.

The format is deliberately small: eight rule kinds, exact tool/action
matching, no expressions, no regular expressions, no globbing. It exists so
that a developer can bound an MCP tool ("`text` at most 2000 characters",
"`amount` at most 1000", "never `rm -rf`") without editing Python, and so
that `atp policy explain/impact/coverage` have something to reason about.
Anything richer belongs in an OPA/Cedar adapter (see
``docs/why-not-just-opa.md``), not here.

Every declared set always includes the kernel policies (delegation valid,
capability held, resource in scope); a file cannot switch them off. A set
may additionally ``include: [payments]`` to pull in the built-in payment
policies.

Example::

    version: 1
    policy_sets:
      - version: notes-v1
        description: notes assistant
        rules:
          - id: short-notes
            applies_to: {tool: mcp.notes, action: write_note}
            kind: argument_max_length
            argument: text
            max_length: 2000
          - id: no-delete
            applies_to: {tool: mcp.notes, action: delete_note}
            kind: deny
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atp_core import ConstraintEvaluation, PolicyEvaluation, ReasonCode
from atp_core.canonical import canonical_json
from atp_policy.base import Policy, PolicyContext, PolicySet
from atp_policy.policies import (
    CapabilityRequiredPolicy,
    DelegationValidPolicy,
    PaymentApprovalThresholdPolicy,
    PaymentArgumentsPolicy,
    PaymentCurrencyPolicy,
    PaymentDestinationPolicy,
    PaymentMaxAmountPolicy,
    ResourceScopePolicy,
)
from atp_policy.registry import DEFAULT_APPROVAL_THRESHOLD

POLICY_FILE_VERSION = 1
_IDENT = r"^[A-Za-z0-9._:-]+$"
_RULE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_ARG = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"

RuleKind = Literal[
    "argument_max",
    "argument_min",
    "argument_allowed_values",
    "argument_max_length",
    "argument_required",
    "argument_forbidden",
    "deny",
    "require_approval",
]

MAX_RULES_PER_SET = 200
MAX_ALLOWED_VALUES = 500


class AppliesTo(BaseModel):
    """Exact match on tool and (optionally) action. ``*`` means any."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str = Field(pattern=r"^(\*|[A-Za-z0-9._:-]+)$", max_length=64)
    action: str = Field(default="*", pattern=r"^(\*|[A-Za-z0-9._:-]+)$", max_length=64)

    def matches(self, ctx: PolicyContext) -> bool:
        env = ctx.envelope
        return (self.tool in ("*", env.tool)) and (self.action in ("*", env.action))


class RuleSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_RULE_ID)
    description: str = Field(default="", max_length=500)
    applies_to: AppliesTo
    kind: RuleKind
    argument: str | None = Field(default=None, pattern=_ARG)
    arguments: tuple[str, ...] | None = None
    max: Decimal | None = None
    min: Decimal | None = None
    values: tuple[str | int | bool, ...] | None = None
    max_length: int | None = Field(default=None, ge=0, le=1_000_000)
    optional: bool = Field(
        default=False,
        description="For argument_* rules: if the argument is absent, pass instead of deny.",
    )
    approver_role: str = Field(default="approver", max_length=64)

    @model_validator(mode="after")
    def _shape(self) -> RuleSpec:
        k = self.kind
        needs_arg = k in (
            "argument_max",
            "argument_min",
            "argument_allowed_values",
            "argument_max_length",
        )
        if needs_arg and not self.argument:
            raise ValueError(f"rule {self.id}: kind {k} needs 'argument'")
        if k in ("argument_required", "argument_forbidden") and not self.arguments:
            raise ValueError(f"rule {self.id}: kind {k} needs 'arguments'")
        if k == "argument_max" and self.max is None:
            raise ValueError(f"rule {self.id}: argument_max needs 'max'")
        if k == "argument_min" and self.min is None:
            raise ValueError(f"rule {self.id}: argument_min needs 'min'")
        if k == "argument_allowed_values" and not self.values:
            raise ValueError(f"rule {self.id}: argument_allowed_values needs 'values'")
        if self.values is not None and len(self.values) > MAX_ALLOWED_VALUES:
            raise ValueError(f"rule {self.id}: at most {MAX_ALLOWED_VALUES} values")
        if k == "argument_max_length" and self.max_length is None:
            raise ValueError(f"rule {self.id}: argument_max_length needs 'max_length'")
        for name in self.arguments or ():
            import re

            if not re.fullmatch(_ARG, name):
                raise ValueError(f"rule {self.id}: invalid argument name {name!r}")
        for dec in (self.max, self.min):
            if dec is not None and (dec.is_nan() or dec.is_infinite()):
                raise ValueError(f"rule {self.id}: limits must be finite")
        return self


class PolicySetSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(pattern=r"^[A-Za-z0-9._-]+$", max_length=64)
    description: str = Field(default="", max_length=500)
    include: tuple[Literal["payments"], ...] = ()
    approval_threshold: Decimal | None = Field(
        default=None, description="Overrides the payments approval threshold (USD) when included."
    )
    rules: tuple[RuleSpec, ...] = ()

    @model_validator(mode="after")
    def _limits(self) -> PolicySetSpec:
        if len(self.rules) > MAX_RULES_PER_SET:
            raise ValueError(f"policy set {self.version}: at most {MAX_RULES_PER_SET} rules")
        seen: set[str] = set()
        for r in self.rules:
            if r.id in seen:
                raise ValueError(f"policy set {self.version}: duplicate rule id {r.id!r}")
            seen.add(r.id)
        return self


class PolicyFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(default=POLICY_FILE_VERSION, ge=1, le=1)
    policy_sets: tuple[PolicySetSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> PolicyFile:
        seen: set[str] = set()
        for s in self.policy_sets:
            if s.version in seen:
                raise ValueError(f"duplicate policy set version {s.version!r}")
            seen.add(s.version)
        return self


# ------------------------------------------------------------------ rules
def _to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | str | Decimal):
        try:
            dec = Decimal(str(value))
        except InvalidOperation:
            return None
        if dec.is_nan() or dec.is_infinite():
            return None
        return dec
    return None


def _fmt(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


class DeclaredRule(Policy):
    """One rule from the file, evaluated as a policy."""

    version = "v1"

    def __init__(self, spec: RuleSpec, set_version: str) -> None:
        self.spec = spec
        self.id = f"rule.{spec.id}"
        self.description = spec.description or f"{spec.kind} on {spec.applies_to.tool}"
        self.set_version = set_version

    @property
    def approver_role(self) -> str:
        return self.spec.approver_role

    def applies_to(self, ctx: PolicyContext) -> bool:
        return self.spec.applies_to.matches(ctx)

    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation:
        spec = self.spec
        args = ctx.envelope.arguments
        k = spec.kind
        if k == "deny":
            return self.deny(
                ReasonCode.ACTION_DENIED_BY_POLICY,
                f"{ctx.envelope.qualified_action} is denied by rule {spec.id}",
                (
                    ConstraintEvaluation(
                        name="action",
                        requested=ctx.envelope.qualified_action,
                        limit="denied",
                        satisfied=False,
                    ),
                ),
            )
        if k == "require_approval":
            return self.require_approval(
                ReasonCode.APPROVAL_REQUIRED_BY_POLICY,
                f"{ctx.envelope.qualified_action} requires {spec.approver_role} approval "
                f"(rule {spec.id})",
                (
                    ConstraintEvaluation(
                        name="approval",
                        requested=ctx.envelope.qualified_action,
                        limit=spec.approver_role,
                        satisfied=False,
                    ),
                ),
            )
        if k == "argument_required":
            missing = [a for a in (spec.arguments or ()) if a not in args]
            c = ConstraintEvaluation(
                name="required_arguments",
                requested=sorted(args),
                limit=list(spec.arguments or ()),
                satisfied=not missing,
            )
            if missing:
                return self.deny(
                    ReasonCode.ARGUMENT_MISSING, f"required argument(s) missing: {missing}", (c,)
                )
            return self.allow("required arguments present", (c,))
        if k == "argument_forbidden":
            present = [a for a in (spec.arguments or ()) if a in args]
            c = ConstraintEvaluation(
                name="forbidden_arguments",
                requested=sorted(args),
                limit=list(spec.arguments or ()),
                satisfied=not present,
            )
            if present:
                return self.deny(
                    ReasonCode.ARGUMENT_FORBIDDEN, f"forbidden argument(s) present: {present}", (c,)
                )
            return self.allow("no forbidden arguments", (c,))

        assert spec.argument is not None
        name = spec.argument
        if name not in args:
            c = ConstraintEvaluation(
                name=name, requested=None, limit=self._limit_text(), satisfied=spec.optional
            )
            if spec.optional:
                return self.allow(f"argument {name!r} absent; rule {spec.id} is optional", (c,))
            return self.deny(
                ReasonCode.ARGUMENT_MISSING,
                f"argument {name!r} is required by rule {spec.id}",
                (c,),
            )
        value = args[name]

        if k == "argument_max_length":
            assert spec.max_length is not None
            length = (
                len(value) if isinstance(value, str | list | dict) else len(canonical_json(value))
            )
            c = ConstraintEvaluation(
                name=f"{name}.length",
                requested=length,
                limit=spec.max_length,
                satisfied=length <= spec.max_length,
            )
            if not c.satisfied:
                return self.deny(
                    ReasonCode.ARGUMENT_TOO_LONG,
                    f"{name} has length {length}, limit {spec.max_length}",
                    (c,),
                )
            return self.allow(f"{name} length {length} within {spec.max_length}", (c,))

        if k == "argument_allowed_values":
            allowed = list(spec.values or ())
            ok = any(type(value) is type(v) and value == v for v in allowed)
            c = ConstraintEvaluation(
                name=name,
                requested=value
                if isinstance(value, str | int | bool)
                else canonical_json(value)[:200].decode(),
                limit=allowed,
                satisfied=ok,
            )
            if not ok:
                return self.deny(
                    ReasonCode.ARGUMENT_NOT_ALLOWED,
                    f"{name}={_fmt(value)!s} is not in the allowed values {allowed}",
                    (c,),
                )
            return self.allow(f"{name} is an allowed value", (c,))

        dec = _to_decimal(value)
        if dec is None:
            c = ConstraintEvaluation(
                name=name, requested=_fmt(value)[:200], limit=self._limit_text(), satisfied=False
            )
            return self.deny(ReasonCode.ARGUMENT_INVALID, f"{name} is not a finite number", (c,))
        if k == "argument_max":
            assert spec.max is not None
            c = ConstraintEvaluation(
                name=name, requested=_fmt(dec), limit=_fmt(spec.max), satisfied=dec <= spec.max
            )
            if not c.satisfied:
                return self.deny(
                    ReasonCode.ARGUMENT_EXCEEDS_LIMIT,
                    f"{name}={_fmt(dec)} exceeds limit {_fmt(spec.max)}",
                    (c,),
                )
            return self.allow(f"{name}={_fmt(dec)} within limit {_fmt(spec.max)}", (c,))
        assert spec.min is not None
        c = ConstraintEvaluation(
            name=name, requested=_fmt(dec), limit=_fmt(spec.min), satisfied=dec >= spec.min
        )
        if not c.satisfied:
            return self.deny(
                ReasonCode.ARGUMENT_BELOW_MINIMUM,
                f"{name}={_fmt(dec)} is below minimum {_fmt(spec.min)}",
                (c,),
            )
        return self.allow(f"{name}={_fmt(dec)} at or above minimum {_fmt(spec.min)}", (c,))

    def _limit_text(self) -> Any:
        s = self.spec
        if s.kind == "argument_max":
            return _fmt(s.max)
        if s.kind == "argument_min":
            return _fmt(s.min)
        if s.kind == "argument_max_length":
            return s.max_length
        if s.kind == "argument_allowed_values":
            return list(s.values or ())
        return None


KERNEL_POLICIES = (DelegationValidPolicy, CapabilityRequiredPolicy, ResourceScopePolicy)


def build_policy_set(spec: PolicySetSpec) -> PolicySet:
    policies: list[Policy] = [cls() for cls in KERNEL_POLICIES]
    if "payments" in spec.include:
        threshold = DEFAULT_APPROVAL_THRESHOLD
        if spec.approval_threshold is not None:
            threshold = threshold.model_copy(update={"amount": spec.approval_threshold})
        policies += [
            PaymentArgumentsPolicy(),
            PaymentMaxAmountPolicy(),
            PaymentCurrencyPolicy(),
            PaymentDestinationPolicy(),
            PaymentApprovalThresholdPolicy(threshold),
        ]
    policies += [DeclaredRule(r, spec.version) for r in spec.rules]
    return PolicySet(
        version=spec.version,
        description=spec.description or f"declared policy set {spec.version}",
        policies=tuple(policies),
    )


def load_policy_file(path: str | Path) -> PolicyFile:
    p = Path(path)
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{p}: expected a mapping at top level")
    return PolicyFile.model_validate(raw)


def load_policy_sets(path: str | Path) -> list[PolicySet]:
    return [build_policy_set(s) for s in load_policy_file(path).policy_sets]


def dump_policy_file(policy_file: PolicyFile, path: str | Path) -> None:
    data = policy_file.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    data["version"] = policy_file.version
    Path(path).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

"""Static analysis over policy sets: structural diff and per-action coverage.

Both are explicit and explainable; neither produces a score. Coverage says,
for one tool action and the argument names it was called with, which
dimensions a policy set constrains and which it does not.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atp_policy.base import Policy, PolicySet
from atp_policy.declarative import DeclaredRule
from atp_policy.policies.payments import PAYMENT_ACTION, PAYMENT_TOOL

# ------------------------------------------------------------------- diff


def _describe(policy: Policy) -> dict[str, Any]:
    if isinstance(policy, DeclaredRule):
        return policy.spec.model_dump(mode="json", exclude_none=True)
    body: dict[str, Any] = {"builtin": True, "description": policy.description}
    for attr in ("threshold", "approver_role"):
        if hasattr(policy, attr):
            value = getattr(policy, attr)
            body[attr] = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return body


class PolicySetDiff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    from_version: str
    to_version: str
    added: list[str]
    removed: list[str]
    changed: list[str]
    unchanged: list[str]
    details: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def diff_policy_sets(a: PolicySet, b: PolicySet) -> PolicySetDiff:
    left = {p.ref.qualified: _describe(p) for p in a.policies}
    right = {p.ref.qualified: _describe(p) for p in b.policies}
    added = sorted(set(right) - set(left))
    removed = sorted(set(left) - set(right))
    changed = sorted(k for k in set(left) & set(right) if left[k] != right[k])
    unchanged = sorted(k for k in set(left) & set(right) if left[k] == right[k])
    details: dict[str, dict[str, Any]] = {}
    for k in added:
        details[k] = {"to": right[k]}
    for k in removed:
        details[k] = {"from": left[k]}
    for k in changed:
        details[k] = {"from": left[k], "to": right[k]}
    return PolicySetDiff(
        from_version=a.version,
        to_version=b.version,
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
        details=details,
    )


def format_diff(d: PolicySetDiff) -> str:
    lines = [f"policy set diff: {d.from_version} -> {d.to_version}"]
    if d.is_empty:
        lines.append("  no policy differences")
    for k in d.added:
        lines.append(f"  + {k}")
    for k in d.removed:
        lines.append(f"  - {k}")
    for k in d.changed:
        lines.append(f"  ~ {k}")
    lines.append(f"  = {len(d.unchanged)} unchanged")
    return "\n".join(lines)


# --------------------------------------------------------------- coverage


class ActionCoverage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    action: str
    guarded: dict[str, list[str]] = Field(
        description="dimension -> policies that constrain it (capability, resource, "
        "argument names, action)"
    )
    unguarded: list[str]
    denied_outright: bool = False
    requires_approval: bool = False


def _applies(policy: Policy, tool: str, action: str) -> bool:
    if isinstance(policy, DeclaredRule):
        a = policy.spec.applies_to
        return a.tool in ("*", tool) and a.action in ("*", action)
    if policy.id.startswith("payments."):
        return tool == PAYMENT_TOOL and action == PAYMENT_ACTION
    return True  # kernel policies apply to everything


def coverage_for(
    policy_set: PolicySet, tool: str, action: str, argument_names: list[str]
) -> ActionCoverage:
    guarded: dict[str, list[str]] = {"capability": [], "resource": []}
    for name in argument_names:
        guarded.setdefault(f"argument:{name}", [])
    denied = False
    approval = False
    for policy in policy_set.policies:
        if not _applies(policy, tool, action):
            continue
        q = policy.ref.qualified
        if policy.id == "capability.required":
            guarded["capability"].append(q)
        elif policy.id == "resource.scope":
            guarded["resource"].append(q)
        elif policy.id == "delegation.valid":
            guarded.setdefault("delegation", []).append(q)
        elif isinstance(policy, DeclaredRule):
            spec = policy.spec
            if spec.kind == "deny":
                denied = True
                guarded.setdefault("action", []).append(q)
            elif spec.kind == "require_approval":
                approval = True
                guarded.setdefault("approval", []).append(q)
            elif spec.argument:
                guarded.setdefault(f"argument:{spec.argument}", []).append(q)
            else:
                for arg in spec.arguments or ():
                    guarded.setdefault(f"argument:{arg}", []).append(q)
        elif policy.id.startswith("payments."):
            if policy.id == "payments.vendor.max_amount":
                guarded.setdefault("argument:amount", []).append(q)
            elif policy.id == "payments.currency":
                guarded.setdefault("argument:currency", []).append(q)
            elif policy.id == "payments.vendor.approved_destination":
                guarded.setdefault("argument:destination_account", []).append(q)
                guarded["resource"].append(q)
            elif policy.id == "payments.approval_threshold":
                guarded.setdefault("approval", []).append(q)
                approval = True
            elif policy.id == "payments.arguments":
                guarded.setdefault("argument:amount", []).append(q)
    unguarded = sorted(k for k, v in guarded.items() if not v)
    return ActionCoverage(
        tool=tool,
        action=action,
        guarded={k: v for k, v in guarded.items() if v},
        unguarded=unguarded,
        denied_outright=denied,
        requires_approval=approval,
    )


def format_coverage(rows: list[ActionCoverage], version: str) -> str:
    lines = [f"policy coverage under {version} (explicit; no score)"]
    for r in rows:
        lines.append("")
        flags = []
        if r.denied_outright:
            flags.append("DENIED OUTRIGHT")
        if r.requires_approval:
            flags.append("requires approval")
        lines.append(f"{r.tool}.{r.action}" + (f"   [{'; '.join(flags)}]" if flags else ""))
        for dim, pols in sorted(r.guarded.items()):
            lines.append(f"  {dim:<28} guarded    by {', '.join(pols)}")
        for dim in r.unguarded:
            lines.append(f"  {dim:<28} UNGUARDED")
    return "\n".join(lines)

"""Deterministic decision explanations.

Answers, from the recorded decision alone (no model, no heuristics beyond a
fixed table keyed on reason codes): who asked, on whose authority, for
what capability on what resource, which constraints were checked with what
values, which policy decided, why, and what would have to change for the
outcome to differ. "What would need to change" is derived from the failing
constraint's recorded ``requested``/``limit`` values and the reason code.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atp_core import ActionEnvelope, Decision, DecisionOutcome, PolicyEvaluation, ReasonCode


class ConstraintLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy: str
    name: str
    requested: Any = None
    limit: Any = None
    satisfied: bool
    detail: str | None = None


class Explanation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    outcome: str = Field(description="ALLOW / DENY / REQUIRE_APPROVAL, or WOULD_* in shadow mode")
    enforcement: str
    reason_code: str
    who: str
    on_whose_authority: str
    delegation_path: list[str]
    capability: str
    resource: str
    tool_action: str
    policy_set: str
    matched_policy: str | None
    message: str
    constraints: list[ConstraintLine]
    passed: list[str]
    failed: list[str]
    would_need_to_change: list[str]
    authority_source: str | None = Field(
        default=None, description="Which grant in the chain set the binding limit, when known."
    )


def _fmt(v: Any) -> str:
    if v is None:
        return "none"
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    return str(v)


def _limit_source(chain: list[dict[str, Any]], limit: Any) -> str | None:
    """The tightest grant in the recorded chain whose max_amount equals ``limit``."""
    for link in chain:
        constraints = link.get("constraints") or {}
        max_amount = constraints.get("max_amount") or {}
        amount = max_amount.get("amount")
        if amount is not None and str(amount) == str(limit):
            return f"{link.get('grant_id')} ({link.get('label', '')})"
    return None


def _changes(
    decision: Decision, envelope: ActionEnvelope, chain: list[dict[str, Any]]
) -> tuple[list[str], str | None]:
    head: PolicyEvaluation | None = next(
        (e for e in decision.evaluations if e.policy == decision.matched_policy), None
    )
    constraint = head.constraints[0] if head and head.constraints else None
    req = constraint.requested if constraint else None
    lim = constraint.limit if constraint else None
    rc = decision.reason_code
    agent = envelope.agent.id
    leaf = chain[-1]["grant_id"] if chain else envelope.delegation_grant_id
    source: str | None = None
    out: list[str] = []
    if decision.outcome is DecisionOutcome.ALLOW:
        return ["nothing: the action is within delegated authority and policy"], None
    if rc is ReasonCode.CAPABILITY_NOT_GRANTED:
        out.append(
            f"delegate capability '{envelope.capability}' to {agent} on grant {leaf} "
            f"(currently held: {_fmt(lim)}), or have the agent request a held capability"
        )
    elif rc is ReasonCode.RESOURCE_OUT_OF_SCOPE:
        out.append(
            f"widen the resource scope on grant {leaf} to cover '{envelope.resource}' "
            f"(currently {_fmt(lim)}), or target a resource inside that scope"
        )
    elif rc is ReasonCode.PAYMENT_EXCEEDS_DELEGATED_AUTHORITY:
        source = _limit_source(chain, lim)
        if lim is None:
            out.append("express a monetary limit somewhere in the delegation chain")
        else:
            out.append(f"reduce the amount from {_fmt(req)} to at most {_fmt(lim)}")
            out.append(
                f"or raise max_amount above {_fmt(req)} on the grant that sets the limit"
                + (f" ({source})" if source else "")
                + " and on every grant below it"
            )
    elif rc is ReasonCode.PAYMENT_CURRENCY_NOT_PERMITTED:
        out.append(f"use a permitted currency ({_fmt(lim)}) or extend the currency allowlist")
    elif rc is ReasonCode.PAYMENT_DESTINATION_NOT_APPROVED:
        out.append("target an approved vendor resource ('vendor:<id>' in the directory)")
    elif rc is ReasonCode.PAYMENT_DESTINATION_RESOURCE_MISMATCH:
        out.append(
            f"send to the account on file ({_fmt(lim)}) instead of {_fmt(req)}, or update the "
            "vendor directory through its own controlled process"
        )
    elif rc is ReasonCode.PAYMENT_ARGUMENTS_INVALID:
        out.append("send {amount, currency[, destination_account, memo]} with a valid amount")
    elif rc in (ReasonCode.ARGUMENT_EXCEEDS_LIMIT, ReasonCode.ARGUMENT_TOO_LONG):
        name = constraint.name if constraint else "the argument"
        out.append(f"reduce {name} from {_fmt(req)} to at most {_fmt(lim)}")
        out.append(
            f"or raise the limit in rule "
            f"{decision.matched_policy.id if decision.matched_policy else '?'}"
        )
    elif rc is ReasonCode.ARGUMENT_BELOW_MINIMUM:
        name = constraint.name if constraint else "the argument"
        out.append(f"raise {name} from {_fmt(req)} to at least {_fmt(lim)}")
    elif rc is ReasonCode.ARGUMENT_NOT_ALLOWED:
        name = constraint.name if constraint else "the argument"
        out.append(f"set {name} to one of {_fmt(lim)} (got {_fmt(req)})")
    elif rc is ReasonCode.ARGUMENT_MISSING:
        out.append(f"provide the required argument(s): {_fmt(lim)}")
    elif rc is ReasonCode.ARGUMENT_FORBIDDEN:
        out.append(f"drop the forbidden argument(s): {_fmt(lim)}")
    elif rc is ReasonCode.ARGUMENT_INVALID:
        name = constraint.name if constraint else "the argument"
        out.append(f"send {name} as a finite number (got {_fmt(req)})")
    elif rc is ReasonCode.ACTION_DENIED_BY_POLICY:
        out.append(
            f"the action is denied outright by rule "
            f"{decision.matched_policy.id if decision.matched_policy else '?'}; remove the rule "
            "or do not perform this action"
        )
    elif rc in (
        ReasonCode.APPROVAL_REQUIRED_AMOUNT_THRESHOLD,
        ReasonCode.APPROVAL_REQUIRED_BY_POLICY,
    ):
        role = decision.approval.approver_role if decision.approval else "an approver"
        out.append(f"obtain {role} approval (no approval endpoint exists in this release)")
        if lim is not None:
            out.append(f"or stay at or under the auto-approval threshold {_fmt(lim)}")
    elif rc.value.startswith("DELEGATION_"):
        out.append(
            f"fix the delegation chain for grant {envelope.delegation_grant_id}: "
            f"{decision.explanation}"
        )
    else:
        out.append(decision.explanation)
    return out, source


def explain(
    decision: Decision, envelope: ActionEnvelope, chain: list[dict[str, Any]] | None = None
) -> Explanation:
    chain = chain or []
    auth = decision.effective_authority
    lines = [
        ConstraintLine(
            policy=e.policy.qualified,
            name=c.name,
            requested=c.requested,
            limit=c.limit,
            satisfied=c.satisfied,
            detail=c.detail,
        )
        for e in decision.evaluations
        for c in e.constraints
    ]
    passed = [
        e.policy.qualified for e in decision.evaluations if e.outcome is DecisionOutcome.ALLOW
    ]
    failed = [
        e.policy.qualified for e in decision.evaluations if e.outcome is not DecisionOutcome.ALLOW
    ]
    changes, source = _changes(decision, envelope, chain)
    return Explanation(
        trace_id=decision.trace_id,
        outcome=decision.display_outcome,
        enforcement=decision.enforcement,
        reason_code=decision.reason_code.value,
        who=f"{envelope.agent.id} ({envelope.agent.kind.value})",
        on_whose_authority=(
            f"{auth.root_principal.id} ({auth.root_principal.kind.value})"
            if auth
            else f"claimed {envelope.principal.id}; chain did not resolve"
        ),
        delegation_path=[
            f"{link.get('grantor', {}).get('id')} -> {link.get('grantee', {}).get('id')} "
            f"[{link.get('grant_id')}]"
            for link in chain
        ],
        capability=envelope.capability,
        resource=envelope.resource,
        tool_action=envelope.qualified_action,
        policy_set=decision.policy_set_version,
        matched_policy=decision.matched_policy.qualified if decision.matched_policy else None,
        message=decision.explanation,
        constraints=lines,
        passed=passed,
        failed=failed,
        would_need_to_change=changes,
        authority_source=source,
    )


def format_explanation(x: Explanation) -> str:
    w = 78
    lines = [
        "=" * w,
        f"{x.outcome}  {x.reason_code}",
        "=" * w,
        f"trace:        {x.trace_id}",
        f"who:          {x.who}",
        f"authority:    {x.on_whose_authority}",
    ]
    for hop in x.delegation_path:
        lines.append(f"              {hop}")
    lines += [
        f"action:       {x.tool_action}  capability={x.capability}",
        f"resource:     {x.resource}",
        f"policy set:   {x.policy_set}  mode={x.enforcement}",
        f"decided by:   {x.matched_policy or 'no policy matched (all passed)'}",
        f"message:      {x.message}",
        "",
        "constraints checked:",
    ]
    for c in x.constraints:
        mark = "ok  " if c.satisfied else "FAIL"
        lines.append(
            f"  [{mark}] {c.name:<22} requested={_fmt(c.requested):<28} limit={_fmt(c.limit)}"
            + (f"  ({c.detail})" if c.detail else "")
            + f"   <- {c.policy}"
        )
    if not x.constraints:
        lines.append("  (none recorded)")
    lines += ["", f"passed: {', '.join(x.passed) or '-'}", f"failed: {', '.join(x.failed) or '-'}"]
    if x.authority_source:
        lines.append(f"limit set by: {x.authority_source}")
    lines += ["", "what would need to change:"]
    lines += [f"  - {c}" for c in x.would_need_to_change]
    return "\n".join(lines)

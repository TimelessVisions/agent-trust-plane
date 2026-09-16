"""The policy engine: evaluates every applicable policy and reduces to one
deterministic decision."""

from __future__ import annotations

from atp_core import (
    ApprovalRequirement,
    Decision,
    DecisionOutcome,
    PolicyEvaluation,
    ReasonCode,
)
from atp_policy.base import PolicyContext, PolicySet
from atp_policy.policies.payments import PaymentApprovalThresholdPolicy


class PolicyEngine:
    def evaluate(self, policy_set: PolicySet, ctx: PolicyContext) -> Decision:
        evaluations: list[PolicyEvaluation] = [
            policy.evaluate(ctx) for policy in policy_set.policies if policy.applies_to(ctx)
        ]
        denies = [e for e in evaluations if e.outcome is DecisionOutcome.DENY]
        approvals = [e for e in evaluations if e.outcome is DecisionOutcome.REQUIRE_APPROVAL]

        if denies:
            head = denies[0]
            outcome, reason, matched = DecisionOutcome.DENY, head.reason_code, head.policy
            explanation = head.message
            approval = None
        elif approvals:
            head = approvals[0]
            outcome, reason, matched = (
                DecisionOutcome.REQUIRE_APPROVAL,
                head.reason_code,
                head.policy,
            )
            explanation = head.message
            approver = next(
                (
                    p.approver_role
                    for p in policy_set.policies
                    if isinstance(p, PaymentApprovalThresholdPolicy) and p.ref == head.policy
                ),
                "approver",
            )
            approval = ApprovalRequirement(approver_role=approver, reason=head.message)
        else:
            outcome, reason, matched = DecisionOutcome.ALLOW, ReasonCode.ALLOWED, None
            explanation = f"all {len(evaluations)} applicable policies passed"
            approval = None

        return Decision(
            trace_id=ctx.envelope.trace_id,
            envelope_id=ctx.envelope.envelope_id,
            action_hash=ctx.envelope.action_hash,
            decided_at=ctx.now,
            outcome=outcome,
            reason_code=reason,
            explanation=explanation,
            matched_policy=matched,
            policy_set_version=policy_set.version,
            evaluations=tuple(evaluations),
            effective_authority=ctx.authority,
            approval=approval,
        )

"""Policies about *who* is asking and *what they hold*. These apply to every
action regardless of tool."""

from __future__ import annotations

from atp_core import ConstraintEvaluation, PolicyEvaluation, ReasonCode
from atp_identity import scope_matches
from atp_policy.base import Policy, PolicyContext


class DelegationValidPolicy(Policy):
    id = "delegation.valid"
    version = "v1"
    description = "The presented delegation chain must resolve to a live, unbroken chain."

    def applies_to(self, ctx: PolicyContext) -> bool:
        return True

    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation:
        if ctx.authority is None:
            code, message = ctx.resolution_error or (
                ReasonCode.DELEGATION_NOT_FOUND,
                "delegation could not be resolved",
            )
            return self.deny(code, message)
        auth = ctx.authority
        return self.allow(
            f"delegation chain of {auth.depth} grant(s) rooted at {auth.root_principal} is valid",
            (
                ConstraintEvaluation(
                    name="chain_expires_at",
                    requested=ctx.now.isoformat(),
                    limit=auth.expires_at.isoformat(),
                    satisfied=True,
                ),
            ),
        )


class CapabilityRequiredPolicy(Policy):
    id = "capability.required"
    version = "v1"
    description = "The requested capability must be present in the effective authority."

    def applies_to(self, ctx: PolicyContext) -> bool:
        return ctx.authority is not None

    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation:
        assert ctx.authority is not None
        cap = ctx.envelope.capability
        held = sorted(ctx.authority.capabilities)
        constraint = ConstraintEvaluation(
            name="capability",
            requested=cap,
            limit=held,
            satisfied=cap in ctx.authority.capabilities,
        )
        if not constraint.satisfied:
            return self.deny(
                ReasonCode.CAPABILITY_NOT_GRANTED,
                f"capability '{cap}' is not held by {ctx.authority.holder}; held: {held}",
                (constraint,),
            )
        return self.allow(f"capability '{cap}' is held", (constraint,))


class ResourceScopePolicy(Policy):
    id = "resource.scope"
    version = "v1"
    description = "The target resource must fall inside the effective resource scope."

    def applies_to(self, ctx: PolicyContext) -> bool:
        return ctx.authority is not None

    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation:
        assert ctx.authority is not None
        resource = ctx.envelope.resource
        scope = list(ctx.authority.resource_scope)
        ok = scope_matches(scope, resource)
        constraint = ConstraintEvaluation(
            name="resource_scope", requested=resource, limit=scope, satisfied=ok
        )
        if not ok:
            return self.deny(
                ReasonCode.RESOURCE_OUT_OF_SCOPE,
                f"resource '{resource}' is outside permitted scope {scope}",
                (constraint,),
            )
        return self.allow(f"resource '{resource}' is within scope", (constraint,))

from __future__ import annotations

from datetime import timedelta

import pytest

from atp_core import DecisionOutcome, ReasonCode
from atp_identity import DelegationService
from atp_policy import PolicyEngine, PolicySetRegistry, payments_v1, payments_v2
from atp_policy.base import PolicySet

from policy_fixtures import (
    AP_AGENT,
    ATTACKER,
    DOC_AGENT,
    NOW,
    build_chain,
    context_for,
    fresh_service,
    payment_envelope,
)


@pytest.fixture
def service() -> DelegationService:
    return fresh_service()


@pytest.fixture
def grants(service: DelegationService) -> dict[str, str]:
    return build_chain(service)


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine()


@pytest.fixture
def v2() -> PolicySet:
    return payments_v2()


class TestPrimaryScenario:
    def test_normal_payment_is_allowed(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], amount="480.00")
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.outcome is DecisionOutcome.ALLOW
        assert decision.reason_code is ReasonCode.ALLOWED
        assert decision.matched_policy is None
        assert len(decision.evaluations) == 8
        assert all(e.outcome is DecisionOutcome.ALLOW for e in decision.evaluations)
        assert decision.effective_authority is not None
        assert decision.effective_authority.constraints.max_amount is not None

    def test_injected_12500_payment_is_denied_for_exceeding_authority(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], amount="12500.00", destination=ATTACKER)
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.outcome is DecisionOutcome.DENY
        assert decision.reason_code is ReasonCode.PAYMENT_EXCEEDS_DELEGATED_AUTHORITY
        assert decision.matched_policy is not None
        assert decision.matched_policy.qualified == "payments.vendor.max_amount.v1"
        amount_eval = next(
            e for e in decision.evaluations if e.policy.id == "payments.vendor.max_amount"
        )
        [constraint] = amount_eval.constraints
        assert constraint.requested == "12500.00"
        assert constraint.limit == "1000.00"
        assert not constraint.satisfied
        # The destination violation is also recorded, not hidden by the first deny.
        codes = {e.reason_code for e in decision.violations()}
        assert ReasonCode.PAYMENT_DESTINATION_RESOURCE_MISMATCH in codes

    def test_exactly_at_limit_is_allowed_but_needs_approval(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], amount="1000.00")
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.outcome is DecisionOutcome.REQUIRE_APPROVAL
        assert decision.reason_code is ReasonCode.APPROVAL_REQUIRED_AMOUNT_THRESHOLD
        assert decision.approval is not None
        assert decision.approval.approver_role == "finance-manager"

    def test_one_cent_over_limit_is_denied(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], amount="1000.01")
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.reason_code is ReasonCode.PAYMENT_EXCEEDS_DELEGATED_AUTHORITY


class TestAuthorityPolicies:
    def test_missing_capability(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        """Document agent (read-only) tries to pay under its own grant."""
        env = payment_envelope(agent=DOC_AGENT, grant_id=grants["doc"], amount="50.00")
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.outcome is DecisionOutcome.DENY
        assert decision.reason_code is ReasonCode.CAPABILITY_NOT_GRANTED
        assert decision.matched_policy is not None
        assert decision.matched_policy.id == "capability.required"

    def test_child_presenting_parents_grant(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(agent=DOC_AGENT, grant_id=grants["ap"], amount="50.00")
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.reason_code is ReasonCode.DELEGATION_GRANTEE_MISMATCH
        assert decision.effective_authority is None

    def test_resource_out_of_scope(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], resource="payroll:employee-7", amount="50.00")
        decision = engine.evaluate(v2, context_for(env, service))
        assert ReasonCode.RESOURCE_OUT_OF_SCOPE in {e.reason_code for e in decision.violations()}

    def test_expired_delegation(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], amount="50.00")
        decision = engine.evaluate(v2, context_for(env, service, now=NOW + timedelta(days=2)))
        assert decision.reason_code is ReasonCode.DELEGATION_EXPIRED
        # Policies needing authority are skipped, but the delegation policy is recorded.
        assert next(e.policy.id for e in decision.evaluations) == "delegation.valid"

    def test_unknown_grant(
        self, engine: PolicyEngine, v2: PolicySet, service: DelegationService
    ) -> None:
        env = payment_envelope(grant_id="grt_forged", amount="50.00")
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.reason_code is ReasonCode.DELEGATION_NOT_FOUND


class TestPaymentPolicies:
    def test_unapproved_vendor(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], resource="vendor:999", amount="50.00")
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.reason_code is ReasonCode.PAYMENT_DESTINATION_NOT_APPROVED

    def test_destination_swap_under_limit(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], amount="940.00", destination=ATTACKER)
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.reason_code is ReasonCode.PAYMENT_DESTINATION_RESOURCE_MISMATCH

    def test_destination_swap_is_missed_by_v1_and_caught_by_v2(
        self, engine: PolicyEngine, service: DelegationService, grants: dict[str, str]
    ) -> None:
        """The replay story: same envelope, different policy version, different outcome."""
        env = payment_envelope(grant_id=grants["ap"], amount="640.00", destination=ATTACKER)
        ctx = context_for(env, service)
        assert engine.evaluate(payments_v1(), ctx).outcome is DecisionOutcome.ALLOW
        assert engine.evaluate(payments_v2(), ctx).outcome is DecisionOutcome.DENY

    def test_malformed_arguments(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], amount="lots")
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.reason_code is ReasonCode.PAYMENT_ARGUMENTS_INVALID

    def test_unexpected_argument_rejected(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], amount="10.00", override_limit=True)
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.reason_code is ReasonCode.PAYMENT_ARGUMENTS_INVALID

    def test_currency_not_permitted(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], amount="10.00").model_copy(
            update={"arguments": {"amount": "10.00", "currency": "EUR"}}
        )
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.reason_code is ReasonCode.PAYMENT_CURRENCY_NOT_PERMITTED

    def test_non_payment_action_skips_payment_policies(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"]).model_copy(
            update={
                "tool": "invoices",
                "action": "read",
                "capability": "read:invoice",
                "resource": "invoice:INV-2291",
                "arguments": {},
            }
        )
        decision = engine.evaluate(v2, context_for(env, service))
        assert decision.outcome is DecisionOutcome.ALLOW
        assert {e.policy.id for e in decision.evaluations} == {
            "delegation.valid",
            "capability.required",
            "resource.scope",
        }


class TestRegistry:
    def test_builtin_registry(self) -> None:
        reg = PolicySetRegistry.builtin()
        assert reg.default_version == "payments-v2"
        assert reg.get().version == "payments-v2"
        assert reg.get("payments-v1").version == "payments-v1"
        assert [s.version for s in reg.versions()] == ["payments-v1", "payments-v2"]

    def test_unknown_version(self) -> None:
        from atp_policy import PolicySetNotFoundError

        with pytest.raises(PolicySetNotFoundError):
            PolicySetRegistry.builtin().get("payments-v9")

    def test_decision_is_deterministic(
        self,
        engine: PolicyEngine,
        v2: PolicySet,
        service: DelegationService,
        grants: dict[str, str],
    ) -> None:
        env = payment_envelope(grant_id=grants["ap"], amount="12500.00")
        a = engine.evaluate(v2, context_for(env, service))
        b = engine.evaluate(v2, context_for(env, service))
        assert a.model_dump(exclude={"decision_id"}) == b.model_dump(exclude={"decision_id"})
        assert env.agent == AP_AGENT

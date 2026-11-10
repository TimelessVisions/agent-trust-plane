"""Fail-closed payment rules for explicitly payment-capable MCP actions.

MCP proxy mappings must not impersonate the native gateway-executed `payments`
tool. Payment safeguards must nevertheless apply to explicitly delegated
`pay:vendor` actions from any namespaced `mcp.*` tool. Regressions in this
file MUST NOT be softened to bypass the incident failure.
"""

from __future__ import annotations

import pytest

from atp_core import DecisionOutcome, ReasonCode
from atp_policy import PolicyEngine, payments_v2

from policy_fixtures import (
    ATTACKER,
    build_chain,
    context_for,
    fresh_service,
    payment_envelope,
)


@pytest.mark.parametrize("tool", ["mcp.payments", "mcp.vendor_processor", "mcp.another_server"])
def test_payment_capability_requires_approved_destination_for_any_mcp_tool(
    tool: str,
) -> None:
    service = fresh_service()
    grant = build_chain(service)["ap"]
    envelope = payment_envelope(grant_id=grant, amount="640", destination=ATTACKER).model_copy(
        update={"tool": tool}
    )
    decision = PolicyEngine().evaluate(payments_v2(), context_for(envelope, service))
    assert decision.outcome is DecisionOutcome.DENY
    assert decision.reason_code is ReasonCode.PAYMENT_DESTINATION_RESOURCE_MISMATCH


@pytest.mark.parametrize("tool", ["payments", "mcp.payments", "mcp.vendor_processor"])
def test_payment_capability_preserves_legitimate_payment(tool: str) -> None:
    service = fresh_service()
    grant = build_chain(service)["ap"]
    envelope = payment_envelope(
        grant_id=grant, amount="480", destination="acct-nw-4471"
    ).model_copy(update={"tool": tool})
    decision = PolicyEngine().evaluate(payments_v2(), context_for(envelope, service))
    assert decision.outcome is DecisionOutcome.ALLOW
    assert decision.reason_code is ReasonCode.ALLOWED


@pytest.mark.parametrize(
    ("amount", "reason"),
    [
        ("1000.01", ReasonCode.PAYMENT_EXCEEDS_DELEGATED_AUTHORITY),
        ("800", ReasonCode.APPROVAL_REQUIRED_AMOUNT_THRESHOLD),
    ],
)
def test_mcp_payment_capability_preserves_amount_and_approval(
    amount: str, reason: ReasonCode
) -> None:
    service = fresh_service()
    grant = build_chain(service)["ap"]
    envelope = payment_envelope(
        grant_id=grant,
        amount=amount,
        destination="acct-nw-4471",
    ).model_copy(update={"tool": "mcp.payments"})
    decision = PolicyEngine().evaluate(payments_v2(), context_for(envelope, service))
    assert decision.reason_code is reason
    assert decision.outcome is (
        DecisionOutcome.REQUIRE_APPROVAL
        if reason is ReasonCode.APPROVAL_REQUIRED_AMOUNT_THRESHOLD
        else DecisionOutcome.DENY
    )


def test_mcp_payment_capability_rejects_non_payment_argument_shape() -> None:
    service = fresh_service()
    grant = build_chain(service)["ap"]
    envelope = payment_envelope(grant_id=grant, amount="480").model_copy(
        update={
            "tool": "mcp.payments",
            "action": "transfer_funds",
            "arguments": {"recipient": ATTACKER, "amount": "480"},
        }
    )
    decision = PolicyEngine().evaluate(payments_v2(), context_for(envelope, service))
    assert decision.outcome is DecisionOutcome.DENY
    assert decision.reason_code is ReasonCode.PAYMENT_ARGUMENTS_INVALID


def test_unrelated_mcp_action_does_not_inherit_payment_rules() -> None:
    service = fresh_service()
    grant = build_chain(service)["ap"]
    envelope = payment_envelope(grant_id=grant, amount="480").model_copy(
        update={"tool": "mcp.notes", "action": "read_note", "capability": "notes:read"}
    )
    decision = PolicyEngine().evaluate(payments_v2(), context_for(envelope, service))
    assert not any(e.policy.id.startswith("payments.") for e in decision.evaluations)

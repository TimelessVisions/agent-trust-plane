from __future__ import annotations

from collections.abc import Iterator

import pytest

from atp_adapter_http import TrustPlaneClient
from atp_gateway import GatewaySettings, create_app
from finance_agent import (
    AP_AGENT,
    HUMAN,
    INJECTED_INVOICE,
    LEGITIMATE_INVOICE,
    SimulatedAgent,
    run_accounts_payable,
    seed_delegation_graph,
)
from finance_agent.invoices import Invoice


@pytest.fixture
def client() -> Iterator[TrustPlaneClient]:
    """Operator client over an in-process ephemeral gateway."""
    app = create_app(GatewaySettings(database_path=":memory:"))
    with TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key) as c:
        yield c


class TestSimulatedAgent:
    def test_pays_the_invoice_amount_when_clean(self) -> None:
        p = SimulatedAgent().propose("pay", LEGITIMATE_INVOICE.raw_text)
        assert (p.vendor_id, p.amount, p.currency) == ("128", "480.00", "USD")
        assert p.destination_account is None
        assert p.influenced_by_instruction is False

    def test_follows_injected_instruction(self) -> None:
        p = SimulatedAgent().propose("pay", INJECTED_INVOICE.raw_text)
        assert p.amount == "12500.00"
        assert p.destination_account == "acct-offshore-9931"
        assert p.influenced_by_instruction is True

    def test_rejects_unparseable_invoice(self) -> None:
        with pytest.raises(ValueError):
            SimulatedAgent().propose("pay", "not an invoice")

    def test_content_hash_differs_between_variants(self) -> None:
        assert LEGITIMATE_INVOICE.content_hash != INJECTED_INVOICE.content_hash
        assert isinstance(INJECTED_INVOICE, Invoice)


class TestWorkflow:
    def test_provenance_is_recorded_before_the_decision(self, client: TrustPlaneClient) -> None:
        seed = seed_delegation_graph(client)
        result = run_accounts_payable(
            client.as_agent(seed.identities.accounts_payable_token),
            SimulatedAgent(),
            INJECTED_INVOICE,
            principal=HUMAN,
            agent=AP_AGENT,
            delegation_grant_id=seed.graph.accounts_payable,
        )
        trace = client.get_trace(result.trace_id)
        types = [e["event_type"] for e in trace["events"]]
        assert types[:3] == ["task_received", "external_content_ingested", "action_proposed"]
        assert types[-1] == "execution_blocked"
        env = trace["envelope"]
        assert env["provenance"]["content_sources"][0]["trust"] == "untrusted"
        assert env["provenance"]["model"] == "simulated-agent/naive-v1"
        assert "following the instruction" in env["provenance"]["agent_rationale"]

    def test_decision_block_matches_demo_contract(self, client: TrustPlaneClient) -> None:
        seed = seed_delegation_graph(client)
        result = run_accounts_payable(
            client.as_agent(seed.identities.accounts_payable_token),
            SimulatedAgent(),
            INJECTED_INVOICE,
            principal=HUMAN,
            agent=AP_AGENT,
            delegation_grant_id=seed.graph.accounts_payable,
        )
        block = result.decision_block()
        for needle in (
            "DECISION: DENY",
            "PAYMENT_EXCEEDS_DELEGATED_AUTHORITY",
            "accounts-payable-agent",
            "USD 12500.00",
            "USD 1,000.00",
            "payments.vendor.max_amount.v1",
            result.trace_id,
        ):
            assert needle in block

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from atp_adapter_http import TrustPlaneClient
from atp_adapter_mcp import DEFAULT_MAPPINGS, AgentContext, McpInterceptor, McpToolCall
from atp_core import PrincipalRef
from atp_gateway import GatewaySettings, create_app
from finance_agent import AP_AGENT, DOC_AGENT, HUMAN, seed_delegation_graph


@pytest.fixture
def client() -> Iterator[TrustPlaneClient]:
    """Operator client over an in-process ephemeral gateway."""
    app = create_app(GatewaySettings(database_path=":memory:"))
    with TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key) as c:
        yield c


def _setup(
    client: TrustPlaneClient, agent: PrincipalRef = AP_AGENT
) -> tuple[McpInterceptor, AgentContext]:
    """An interceptor whose client is authenticated as ``agent``."""
    seed = seed_delegation_graph(client)
    if agent == AP_AGENT:
        grant, token = seed.graph.accounts_payable, seed.identities.accounts_payable_token
    else:
        grant, token = seed.graph.document, seed.identities.document_token
    ctx = AgentContext(principal=HUMAN, agent=agent, delegation_grant_id=grant, model="test")
    return McpInterceptor(client.as_agent(token), DEFAULT_MAPPINGS), ctx


def _call(vendor: str, amount: str) -> McpToolCall:
    return McpToolCall(
        name="send_payment", arguments={"vendor_id": vendor, "amount": amount, "currency": "USD"}
    )


def test_envelope_mapping(client: TrustPlaneClient) -> None:
    interceptor, ctx = _setup(client)
    env = interceptor.to_envelope(_call("128", "10.00"), ctx)
    assert env.tool == "payments" and env.action == "send_payment"
    assert env.capability == "pay:vendor"
    assert env.resource == "vendor:128"
    assert env.arguments == {"amount": "10.00", "currency": "USD"}  # vendor_id moved to resource


def test_allowed_call_executes(client: TrustPlaneClient) -> None:
    interceptor, ctx = _setup(client)
    result = interceptor.intercept(_call("128", "480.00"), ctx)
    assert result.is_error is False
    assert result.structured_content and result.structured_content["status"] == "completed"
    assert len(client.ledger()) == 1


def test_denied_call_returns_structured_error(client: TrustPlaneClient) -> None:
    interceptor, ctx = _setup(client)
    result = interceptor.intercept(_call("128", "12500.00"), ctx)
    assert result.is_error is True
    body = json.loads(result.content[0]["text"])
    assert body["reason_code"] == "PAYMENT_EXCEEDS_DELEGATED_AUTHORITY"
    assert body["matched_policy"] == "payments.vendor.max_amount.v1"
    assert client.get_trace(body["trace_id"])["decision"]["outcome"] == "DENY"
    assert client.ledger() == []


def test_unmapped_tool_is_denied_without_reaching_gateway(client: TrustPlaneClient) -> None:
    interceptor, ctx = _setup(client)
    result = interceptor.intercept(McpToolCall(name="delete_everything", arguments={}), ctx)
    assert result.is_error is True
    assert result.structured_content
    assert result.structured_content["reason_code"] == "TOOL_NOT_MAPPED"
    assert client.list_traces() == []


def test_missing_resource_argument(client: TrustPlaneClient) -> None:
    interceptor, ctx = _setup(client)
    call = McpToolCall(name="send_payment", arguments={"amount": "1"})
    result = interceptor.intercept(call, ctx)
    assert result.is_error is True
    assert "vendor_id" in result.content[0]["text"]


def test_read_only_agent_cannot_pay_via_mcp(client: TrustPlaneClient) -> None:
    interceptor, ctx = _setup(client, DOC_AGENT)
    result = interceptor.intercept(_call("128", "1.00"), ctx)
    assert result.is_error is True
    assert result.structured_content
    assert result.structured_content["reason_code"] == "CAPABILITY_NOT_GRANTED"


def test_mcp_result_serialises_with_protocol_field_names(client: TrustPlaneClient) -> None:
    interceptor, ctx = _setup(client)
    dumped = interceptor.intercept(_call("999", "1.00"), ctx).model_dump(by_alias=True)
    assert set(dumped) == {"content", "isError", "structuredContent"}

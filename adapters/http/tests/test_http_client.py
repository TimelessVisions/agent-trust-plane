from __future__ import annotations

from collections.abc import Iterator

import pytest

from atp_adapter_http import GatewayError, TrustPlaneClient
from atp_gateway import GatewaySettings, create_app


@pytest.fixture
def client() -> Iterator[TrustPlaneClient]:
    """Operator client over an in-process ephemeral gateway."""
    app = create_app(GatewaySettings(database_path=":memory:"))
    with TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key) as c:
        yield c


def test_health_over_in_process_transport(client: TrustPlaneClient) -> None:
    assert client.health()["status"] == "ok"


def test_gateway_errors_carry_reason_codes(client: TrustPlaneClient) -> None:
    with pytest.raises(GatewayError) as exc:
        client.get_trace("000000000000")
    assert exc.value.status_code == 404
    assert exc.value.reason_code == "TRACE_NOT_FOUND"


def test_validation_errors_surface(client: TrustPlaneClient) -> None:
    with pytest.raises(GatewayError) as exc:
        client.issue_delegation({"label": "incomplete"})
    assert exc.value.status_code == 422

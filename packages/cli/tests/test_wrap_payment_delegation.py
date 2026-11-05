"""Local MCP payment authority must carry explicit single-action monetary limits."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atp_adapter_mcp.config import ProxyConfig
from atp_cli.mcp_cmds import seed_session


class RecordingOperator:
    def __init__(self) -> None:
        self.grants: list[dict] = []

    def issue_credential(self, agent, *, label: str, expires_at: str):
        return {"token": "synthetic-session-token"}

    def issue_delegation(self, request: dict):
        self.grants.append(request)
        return {"grant_id": f"synthetic-grant-{len(self.grants)}"}


def _config(authority: dict) -> ProxyConfig:
    return ProxyConfig.model_validate(
        {
            "server_name": "synthetic-payments",
            "upstream": {"command": "python"},
            "authority": authority,
        }
    )


def test_mcp_wrap_seeds_explicit_per_payment_limit_and_currencies() -> None:
    cfg = _config(
        {
            "capabilities": ["pay:vendor"],
            "resource_scope": ["vendor:128"],
            "max_amount": {"amount": "1000", "currency": "USD"},
            "currencies": ["USD"],
        }
    )
    operator = RecordingOperator()
    token, grant = seed_session(operator, cfg)  # type: ignore[arg-type]
    assert token == "synthetic-session-token"
    assert grant == "synthetic-grant-2"
    assert len(operator.grants) == 2
    for req in operator.grants:
        assert req["constraints"]["max_amount"] == {"amount": "1000", "currency": "USD"}
        assert req["constraints"]["currencies"] == ["USD"]


def test_mcp_wrap_without_limit_does_not_invent_payment_authority() -> None:
    cfg = _config({"capabilities": ["pay:vendor"], "resource_scope": ["vendor:128"]})
    operator = RecordingOperator()
    seed_session(operator, cfg)  # type: ignore[arg-type]
    assert not any("max_amount" in req.get("constraints", {}) for req in operator.grants)


def test_mcp_wrap_rejects_inconsistent_currency_authority() -> None:
    with pytest.raises(ValidationError, match="currency"):
        _config(
            {
                "capabilities": ["pay:vendor"],
                "resource_scope": ["vendor:128"],
                "max_amount": {"amount": "1000", "currency": "USD"},
                "currencies": ["EUR"],
            }
        )

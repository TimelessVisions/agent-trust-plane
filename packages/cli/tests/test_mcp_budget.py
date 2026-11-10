"""atp-mcp.yaml `authority.budget` reaches the session's delegation and binds
across sessions (Task C4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from atp_adapter_http import TrustPlaneClient
from atp_adapter_mcp.config import AuthorityConfig, ProxyConfig
from atp_cli.home import AtpHome
from atp_cli.mcp_cmds import seed_session
from atp_core import ActionEnvelope, new_id, new_trace_id
from atp_gateway import build_runtime, create_app
from atp_gateway.local import InProcessAgentClient


def _config(budget: dict[str, Any] | None) -> ProxyConfig:
    authority: dict[str, Any] = {"capabilities": ["bank:send"], "resource_scope": ["acct:*"]}
    if budget is not None:
        authority["budget"] = budget
    return ProxyConfig.model_validate(
        {
            "version": 1,
            "server_name": "bank",
            "upstream": {"command": "python", "args": ["-c", "pass"]},
            "authority": authority,
        }
    )


def test_authority_budget_parses() -> None:
    cfg = _config({"amount": {"amount": "100", "currency": "USD"}, "period": "week"})
    assert cfg.authority is not None and cfg.authority.budget is not None
    assert cfg.authority.budget.period == "week"
    with pytest.raises(ValueError):
        AuthorityConfig.model_validate(
            {
                "capabilities": ["x"],
                "resource_scope": ["*"],
                "budget": {"amount": {"amount": "1", "currency": "USD"}, "period": "year"},
            }
        )


def test_mcp_budget_binds_across_sessions(tmp_path: Path) -> None:
    home = AtpHome(tmp_path / ".atp").ensure()
    settings = home.settings(external_tools=("mcp.bank",))
    cfg = _config({"amount": {"amount": "100", "currency": "USD"}, "period": "day"})

    def session_pay(amount: str) -> str:
        rt = build_runtime(settings)
        try:
            operator = TrustPlaneClient.for_app(
                create_app(settings, runtime=rt), operator_key=rt.operator_key
            )
            token, grant_id = seed_session(operator, cfg)
            agent = InProcessAgentClient.from_token(rt, token)
            env = ActionEnvelope.model_validate(
                {
                    "envelope_id": new_id("env"),
                    "trace_id": new_trace_id(),
                    "principal": cfg.principal.model_dump(mode="json"),
                    "agent": cfg.agent_ref.model_dump(mode="json"),
                    "delegation_grant_id": grant_id,
                    "capability": "bank:send",
                    "tool": "mcp.bank",
                    "action": "send_money",
                    "resource": "acct:1",
                    "arguments": {"amount": amount},
                }
            )
            out = agent.authorize(env)
            if out.execution_grant is not None:
                agent.execute(env, out.execution_grant.token)
                agent.report_outcome(out.execution_grant.grant_id, succeeded=True, summary={})
            return out.decision.reason_code.value
        finally:
            rt.close()

    assert session_pay("80") == "ALLOWED"
    # A new `atp mcp wrap` session issues new grants; the budget still binds.
    assert session_pay("30") == "PAYMENT_EXCEEDS_BUDGET"
    assert session_pay("20") == "ALLOWED"

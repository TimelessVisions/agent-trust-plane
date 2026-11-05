"""`atp approve` end to end: a payment at the limit -> REQUIRE_APPROVAL ->
`atp approve` -> the identical retry -> executed, exactly once."""

from __future__ import annotations

from pathlib import Path

import pytest

from atp_adapter_http import TrustPlaneClient
from atp_cli.home import AtpHome
from atp_cli.main import main
from atp_core import ActionEnvelope
from atp_gateway import GatewaySettings, build_runtime, create_app
from atp_gateway.local import LocalGateway
from finance_agent.scenario import AP_AGENT, HUMAN, seed_delegation_graph


def _payment(grant_id: str, amount: str = "1000.00") -> ActionEnvelope:
    return ActionEnvelope(
        principal=HUMAN,
        agent=AP_AGENT,
        delegation_grant_id=grant_id,
        capability="pay:vendor",
        tool="payments",
        action="send_payment",
        resource="vendor:128",
        arguments={"amount": amount, "currency": "USD"},
    )


def _atp(*argv: str) -> int:
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    code = exc.value.code
    return code if isinstance(code, int) else 1


def test_cli_payment_at_limit_approve_retry_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ATP_APPROVER_ROLES", "human:cfo=finance-manager")
    # The demo's human signs its own root delegation: it needs a key in the home.
    home = AtpHome(tmp_path / ".atp").ensure(human="company-user-42")
    rt = build_runtime(home.settings())
    try:
        app = create_app(rt.settings, runtime=rt)
        with TrustPlaneClient.for_app(app, operator_key=rt.operator_key) as operator:
            seed = seed_delegation_graph(operator)
            agent = operator.as_agent(seed.identities.accounts_payable_token)
            env = _payment(seed.graph.accounts_payable)

            first = agent.authorize(env)
            assert first.decision.outcome.value == "REQUIRE_APPROVAL"
            assert first.execution_grant is None

            # Someone without the role cannot approve.
            assert _atp("approve", env.trace_id, "--as", "intern", "--home", str(home.path)) == 2
            assert "APPROVER_ROLE_MISSING" in capsys.readouterr().err

            # The CLI opens the same home (its own connection) and records the approval.
            assert _atp("approve", env.trace_id, "--as", "cfo", "--home", str(home.path)) == 0
            assert f"approved trace {env.trace_id}" in capsys.readouterr().out

            retry = agent.authorize(env)
            assert retry.decision.outcome.value == "ALLOW"
            assert retry.execution_grant is not None
            done = agent.execute(env, retry.execution_grant)
            assert done.status == "completed"
            assert len(operator.ledger()) == 1

            again = agent.authorize(env)
            assert again.decision.reason_code.value == "APPROVAL_ALREADY_USED"
            assert len(operator.ledger()) == 1
    finally:
        rt.close()


def test_cli_approve_against_a_gateway(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = GatewaySettings(
        _env_file=None,  # type: ignore[call-arg]
        database_path=":memory:",
        approver_roles="human:cfo=finance-manager",
    )
    with LocalGateway(settings) as gw:
        operator = gw.operator_client()
        seed = seed_delegation_graph(operator)
        agent = operator.as_agent(seed.identities.accounts_payable_token)
        env = _payment(seed.graph.accounts_payable)
        assert agent.authorize(env).decision.outcome.value == "REQUIRE_APPROVAL"

        monkeypatch.delenv("ATP_OPERATOR_KEY", raising=False)
        assert _atp("approve", env.trace_id, "--as", "cfo", "--gateway", gw.url) == 2
        assert "operator key" in capsys.readouterr().err

        monkeypatch.setenv("ATP_OPERATOR_KEY", gw.operator_key)
        assert _atp("approve", env.trace_id, "--as", "cfo", "--deny", "--gateway", gw.url) == 0
        assert f"denied trace {env.trace_id}" in capsys.readouterr().out
        out = agent.authorize(env)
        assert out.decision.reason_code.value == "APPROVAL_DENIED"
        assert out.execution_grant is None
        assert operator.ledger() == []

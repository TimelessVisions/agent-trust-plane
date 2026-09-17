"""Shadow mode: the gateway decides and records but does not withhold
execution by trusted executors. The dangerous confusion is shadow vs
enforce, so these tests pin: the caller cannot choose the mode, a shadow
denial never mints a grant, the trace says WOULD_DENY explicitly, and the
executor's report is bound to the trace owner and accepted once."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atp_gateway import GatewaySettings, build_runtime, create_app

from gateway_fixtures import (
    ATTACKER_ACCOUNT,
    OPERATOR_KEY,
    SIGNING_KEY,
    Clock,
    authorize,
    bearer,
    execute,
    ledger,
    op,
    payment_envelope,
    seed_chain,
)


@pytest.fixture
def shadow_client(clock: Clock) -> Iterator[TestClient]:
    settings = GatewaySettings(
        database_path=":memory:",
        grant_signing_key=SIGNING_KEY,
        operator_key=OPERATOR_KEY,
        enforcement_mode="shadow",
    )
    rt = build_runtime(settings)
    rt.trust_plane.clock = clock
    app = create_app(settings, runtime=rt)
    with TestClient(app) as c:
        yield c
    rt.close()


def _shadow_report(client: TestClient, trace_id: str, token: str, succeeded: bool = True) -> Any:
    return client.post(
        f"/traces/{trace_id}/shadow-outcome",
        json={"succeeded": succeeded, "summary": {"note": "executor ran it"}},
        headers=bearer(token),
    )


class TestShadowSemantics:
    def test_health_declares_mode(self, shadow_client: TestClient, client: TestClient) -> None:
        assert shadow_client.get("/health").json()["enforcement_mode"] == "shadow"
        assert client.get("/health").json()["enforcement_mode"] == "enforce"

    def test_shadow_denial_mints_no_grant_and_is_labelled(self, shadow_client: TestClient) -> None:
        chain = seed_chain(shadow_client)
        env = payment_envelope(chain["ap"], amount="12500.00", destination=ATTACKER_ACCOUNT)
        auth = authorize(shadow_client, env, chain["tokens"]["ap"])
        d = auth["decision"]
        assert d["outcome"] == "DENY"
        assert d["enforcement"] == "shadow"
        assert auth["execution_grant"] is None
        # Executing without a grant is still blocked: shadow never weakens /execute.
        ex = execute(shadow_client, env, None, chain["tokens"]["ap"])
        assert ex["status"] == "blocked" and ex["reason_code"] == "GRANT_MISSING"
        assert ledger(shadow_client) == []
        trace = shadow_client.get(f"/traces/{env['trace_id']}", headers=op()).json()
        types = [e["event_type"] for e in trace["events"]]
        assert "shadow_would_deny" in types
        would = next(e for e in trace["events"] if e["event_type"] == "shadow_would_deny")
        assert would["payload"]["enforced"] is False
        assert would["payload"]["reason_code"] == "PAYMENT_EXCEEDS_DELEGATED_AUTHORITY"

    def test_shadow_allow_is_a_normal_allow(self, shadow_client: TestClient) -> None:
        chain = seed_chain(shadow_client)
        env = payment_envelope(chain["ap"], amount="480.00")
        auth = authorize(shadow_client, env, chain["tokens"]["ap"])
        assert auth["decision"]["outcome"] == "ALLOW"
        assert auth["execution_grant"] is not None
        ex = execute(shadow_client, env, auth["execution_grant"]["token"], chain["tokens"]["ap"])
        assert ex["status"] == "completed"

    def test_caller_cannot_request_shadow_mode(self, client: TestClient) -> None:
        chain = seed_chain(client)
        env = payment_envelope(chain["ap"], amount="12500.00")
        r = client.post(
            "/authorize",
            json=env,
            headers=bearer(chain["tokens"]["ap"]),
            params={"enforcement_mode": "shadow", "mode": "shadow"},
        )
        assert r.status_code == 200
        assert r.json()["decision"]["enforcement"] == "enforce"
        env2 = {**payment_envelope(chain["ap"], amount="12500.00"), "enforcement": "shadow"}
        r2 = client.post("/authorize", json=env2, headers=bearer(chain["tokens"]["ap"]))
        assert r2.status_code == 422  # extra="forbid" on the envelope

    def test_shadow_outcome_is_owner_bound_and_once(self, shadow_client: TestClient) -> None:
        chain = seed_chain(shadow_client)
        env = payment_envelope(chain["ap"], amount="12500.00")
        authorize(shadow_client, env, chain["tokens"]["ap"])
        tid = env["trace_id"]
        # Another agent cannot claim it executed the shadowed action.
        other = _shadow_report(shadow_client, tid, chain["tokens"]["doc"])
        assert other.status_code == 403, other.text
        assert other.json()["reason_code"] == "TRACE_OWNED_BY_OTHER_AGENT"
        first = _shadow_report(shadow_client, tid, chain["tokens"]["ap"])
        assert first.status_code == 200, first.text
        assert first.json()["event_type"] == "shadow_execution_completed"
        assert first.json()["payload"]["enforced"] is False
        again = _shadow_report(shadow_client, tid, chain["tokens"]["ap"])
        assert again.status_code == 409
        assert again.json()["reason_code"] == "SHADOW_OUTCOME_ALREADY_REPORTED"
        trace = shadow_client.get(f"/traces/{tid}", headers=op()).json()
        assert trace["execution"]["event_type"] == "shadow_execution_completed"
        assert trace["integrity"]["valid"] is True

    def test_shadow_outcome_rejected_in_enforce_mode_and_for_allows(
        self, client: TestClient, shadow_client: TestClient
    ) -> None:
        chain = seed_chain(client)
        env = payment_envelope(chain["ap"], amount="12500.00")
        authorize(client, env, chain["tokens"]["ap"])
        r = _shadow_report(client, env["trace_id"], chain["tokens"]["ap"])
        assert r.status_code == 409 and r.json()["reason_code"] == "SHADOW_OUTCOME_NOT_APPLICABLE"

        chain2 = seed_chain(shadow_client)
        env2 = payment_envelope(chain2["ap"], amount="480.00")
        authorize(shadow_client, env2, chain2["tokens"]["ap"])
        r2 = _shadow_report(shadow_client, env2["trace_id"], chain2["tokens"]["ap"])
        assert r2.status_code == 409
        assert r2.json()["reason_code"] == "SHADOW_OUTCOME_NOT_APPLICABLE"

    def test_replay_of_shadow_trace_is_decision_only(self, shadow_client: TestClient) -> None:
        chain = seed_chain(shadow_client)
        env = payment_envelope(chain["ap"], amount="640.00", destination=ATTACKER_ACCOUNT)
        authorize(shadow_client, env, chain["tokens"]["ap"])
        r = shadow_client.post(
            f"/replay/{env['trace_id']}",
            json={"policy_set_version": "payments-v1"},
            headers=op(),
        )
        assert r.status_code == 200, r.text
        assert r.json()["replayed_decision"]["outcome"] == "ALLOW"
        assert r.json()["replayed_decision"]["replay_of"]
        assert ledger(shadow_client) == []

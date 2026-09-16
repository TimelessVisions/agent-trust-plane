"""Red-team tests: each one is an attempt to get an action executed without a
valid authorization for *that* action. Every test asserts both the reason code
and that the ledger stays empty (or has exactly the expected entries)."""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi.testclient import TestClient

from atp_gateway import Runtime
from atp_gateway.grants import GrantSigner, new_grant_claims

from gateway_fixtures import (
    ATTACKER_ACCOUNT,
    DOC_AGENT,
    Clock,
    payment_envelope,
    seed_chain,
)


def _authorize(client: TestClient, env: dict[str, Any]) -> dict[str, Any]:
    r = client.post("/authorize", json=env)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _execute(client: TestClient, env: dict[str, Any], token: str | None) -> dict[str, Any]:
    r = client.post("/execute", json={"envelope": env, "execution_grant": token})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _ledger(client: TestClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = client.get("/ledger/payments").json()
    return rows


class TestDirectExecutionBypass:
    def test_execute_without_authorize(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="480.00")
        res = _execute(client, env, None)
        assert res["status"] == "blocked" and res["reason_code"] == "GRANT_MISSING"
        assert _ledger(client) == []

    def test_client_asserted_authorized_flag_is_rejected(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], authorized=True)
        r = client.post("/execute", json={"envelope": env, "execution_grant": None})
        assert r.status_code == 422  # extra field forbidden by the envelope schema
        r = client.post("/authorize", json=env)
        assert r.status_code == 422
        assert _ledger(client) == []

    def test_extra_top_level_execute_fields_are_rejected(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"])
        r = client.post("/execute", json={"envelope": env, "authorized": True})
        assert r.status_code == 422


class TestForgedGrants:
    def test_grant_signed_with_wrong_key(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"])
        # Attacker knows the token format and builds a perfectly-shaped grant.
        from atp_core import ActionEnvelope

        parsed = ActionEnvelope.model_validate(env)
        claims = new_grant_claims(
            trace_id=parsed.trace_id,
            decision_id="dec_forged",
            envelope_id=parsed.envelope_id,
            action_hash=parsed.action_hash,
            agent_id=parsed.agent.id,
            policy_set_version="payments-v2",
            ttl_seconds=3600,
        )
        forged = GrantSigner(b"attacker-controlled-key-of-32-bytes!!").mint(claims)
        res = _execute(client, env, forged)
        assert res["status"] == "blocked"
        assert res["reason_code"] == "GRANT_SIGNATURE_INVALID"
        assert _ledger(client) == []

    def test_grant_with_edited_expiry(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"])
        token = _authorize(client, env)["execution_grant"]["token"]
        body_b64, sig = token.split(".")
        body = json.loads(base64.urlsafe_b64decode(body_b64 + "=" * (-len(body_b64) % 4)))
        body["expires_at"] = "2099-01-01T00:00:00+00:00"
        edited = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
        res = _execute(client, env, f"{edited}.{sig}")
        assert res["reason_code"] == "GRANT_SIGNATURE_INVALID"
        assert _ledger(client) == []

    def test_garbage_token(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"])
        res = _execute(client, env, "definitely.not.a.grant")
        assert res["status"] == "blocked"
        assert res["reason_code"] in {"GRANT_MALFORMED", "GRANT_SIGNATURE_INVALID"}


class TestModifiedActionAfterAuthorization:
    def test_amount_changed_after_authorize(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="480.00")
        token = _authorize(client, env)["execution_grant"]["token"]
        tampered = {**env, "arguments": {"amount": "12500.00", "currency": "USD"}}
        res = _execute(client, tampered, token)
        assert res["status"] == "blocked"
        assert res["reason_code"] == "GRANT_ENVELOPE_MISMATCH"
        assert _ledger(client) == []

    def test_destination_changed_after_authorize(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="480.00")
        token = _authorize(client, env)["execution_grant"]["token"]
        tampered = {
            **env,
            "arguments": {**env["arguments"], "destination_account": ATTACKER_ACCOUNT},
        }
        res = _execute(client, tampered, token)
        assert res["reason_code"] == "GRANT_ENVELOPE_MISMATCH"
        assert _ledger(client) == []

    def test_resource_changed_after_authorize(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="480.00")
        token = _authorize(client, env)["execution_grant"]["token"]
        res = _execute(client, {**env, "resource": "vendor:999"}, token)
        assert res["reason_code"] == "GRANT_ENVELOPE_MISMATCH"

    def test_grant_reused_for_a_different_envelope(self, client: TestClient) -> None:
        """Two identical-looking payments: the grant for one cannot execute the other."""
        grants = seed_chain(client)
        first = payment_envelope(grants["ap"], amount="480.00")
        second = payment_envelope(grants["ap"], amount="480.00")
        token = _authorize(client, first)["execution_grant"]["token"]
        res = _execute(client, second, token)
        assert res["reason_code"] == "GRANT_ENVELOPE_MISMATCH"
        assert _ledger(client) == []


class TestGrantReplay:
    def test_grant_cannot_be_used_twice(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="480.00")
        token = _authorize(client, env)["execution_grant"]["token"]
        assert _execute(client, env, token)["status"] == "completed"
        res = _execute(client, env, token)
        assert res["status"] == "blocked"
        assert res["reason_code"] == "GRANT_ALREADY_CONSUMED"
        assert len(_ledger(client)) == 1

    def test_grant_expires(self, client: TestClient, clock: Clock) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="480.00")
        token = _authorize(client, env)["execution_grant"]["token"]
        clock.advance(seconds=121)
        res = _execute(client, env, token)
        assert res["reason_code"] == "GRANT_EXPIRED"
        assert _ledger(client) == []

    def test_grant_from_another_gateway_instance_is_unknown(
        self, client: TestClient, runtime: Runtime
    ) -> None:
        """Valid signature (same key) but no server-side record: e.g. a token
        minted before a database reset. State, not just signature, is required."""
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="480.00")
        from atp_core import ActionEnvelope

        parsed = ActionEnvelope.model_validate(env)
        claims = new_grant_claims(
            trace_id=parsed.trace_id,
            decision_id="dec_phantom",
            envelope_id=parsed.envelope_id,
            action_hash=parsed.action_hash,
            agent_id=parsed.agent.id,
            policy_set_version="payments-v2",
            ttl_seconds=120,
            now=runtime.trust_plane.clock(),
        )
        token = runtime.trust_plane.signer.mint(claims)  # signed with the real key
        res = _execute(client, env, token)
        assert res["reason_code"] == "GRANT_NOT_FOUND"
        assert _ledger(client) == []


class TestAuthorityBoundaries:
    def test_compromised_child_uses_own_grant_to_pay(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["doc"], agent=DOC_AGENT, amount="900.00")
        auth = _authorize(client, env)
        assert auth["decision"]["outcome"] == "DENY"
        assert auth["decision"]["reason_code"] == "CAPABILITY_NOT_GRANTED"
        assert auth["execution_grant"] is None

    def test_compromised_child_presents_parents_grant(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], agent=DOC_AGENT, amount="900.00")
        auth = _authorize(client, env)
        assert auth["decision"]["reason_code"] == "DELEGATION_GRANTEE_MISMATCH"

    def test_compromised_child_cannot_widen_its_own_grant(self, client: TestClient) -> None:
        grants = seed_chain(client)
        r = client.post(
            "/delegations",
            json={
                "label": "self-upgrade",
                "grantor": DOC_AGENT.model_dump(mode="json"),
                "grantee": {"id": "document-agent-v2", "kind": "agent"},
                "parent_grant_id": grants["doc"],
                "capabilities": ["read:invoice", "pay:vendor"],
                "resource_scope": ["invoice:*", "vendor:*"],
                "constraints": {"max_amount": {"amount": "5000", "currency": "USD"}},
                "expires_at": "2026-09-16T12:30:00Z",
            },
        )
        assert r.status_code == 422
        assert r.json()["reason_code"] == "DELEGATION_EXCEEDS_PARENT_CAPABILITIES"

    def test_resource_mismatch(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], resource="payroll:employee-7", amount="50.00")
        auth = _authorize(client, env)
        assert auth["decision"]["outcome"] == "DENY"
        codes = {e["reason_code"] for e in auth["decision"]["evaluations"]}
        assert "RESOURCE_OUT_OF_SCOPE" in codes

    def test_expired_delegation(self, client: TestClient, clock: Clock) -> None:
        grants = seed_chain(client)
        clock.advance(days=2)  # AP grant lasted 1 day
        env = payment_envelope(grants["ap"], amount="50.00")
        auth = _authorize(client, env)
        assert auth["decision"]["reason_code"] == "DELEGATION_EXPIRED"
        assert auth["execution_grant"] is None

    def test_delegation_revoked_between_authorize_and_execute(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="480.00")
        token = _authorize(client, env)["execution_grant"]["token"]
        assert client.post(f"/delegations/{grants['orch']}/revoke").status_code == 200
        res = _execute(client, env, token)
        assert res["status"] == "blocked"
        assert res["reason_code"] == "DELEGATION_REVOKED"
        assert _ledger(client) == []

    def test_unknown_grant_id(self, client: TestClient) -> None:
        env = payment_envelope("grt_forged_id", amount="1.00")
        auth = _authorize(client, env)
        assert auth["decision"]["reason_code"] == "DELEGATION_NOT_FOUND"

    def test_orchestrator_cannot_use_ap_agents_grant(self, client: TestClient) -> None:
        """Even the parent cannot act under a child's grant; grants bind to grantees."""
        from gateway_fixtures import ORCHESTRATOR

        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], agent=ORCHESTRATOR, amount="480.00")
        auth = _authorize(client, env)
        assert auth["decision"]["reason_code"] == "DELEGATION_GRANTEE_MISMATCH"


class TestTraceIntegrity:
    def test_tampering_with_stored_event_is_detected(
        self, client: TestClient, runtime: Runtime
    ) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="12500.00")
        client.post("/authorize", json=env)
        store = runtime.trust_plane.traces
        # Reach behind the store's API to simulate a database-level edit.
        events = store._events  # type: ignore[attr-defined]
        idx = next(i for i, e in enumerate(events) if e.event_type.value == "decision_made")
        import copy

        payload = copy.deepcopy(events[idx].payload)
        payload["decision"]["outcome"] = "ALLOW"
        payload["decision"]["reason_code"] = "ALLOWED"
        events[idx] = events[idx].model_copy(update={"payload": payload})
        trace = client.get(f"/traces/{env['trace_id']}").json()
        assert trace["integrity"]["valid"] is False
        assert trace["integrity"]["first_bad_seq"] == events[idx].seq


class TestPolicySelection:
    """An agent must not be able to pick which policy set judges it."""

    def test_agent_cannot_select_weaker_policy_set(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="640.00", destination=ATTACKER_ACCOUNT)
        r = client.post("/authorize?policy_set_version=payments-v1", json=env)
        assert r.status_code == 403
        assert r.json()["reason_code"] == "POLICY_SET_OVERRIDE_FORBIDDEN"
        assert _ledger(client) == []

    def test_wrong_operator_key_is_rejected(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="640.00", destination=ATTACKER_ACCOUNT)
        r = client.post(
            "/authorize?policy_set_version=payments-v1",
            json=env,
            headers={"X-ATP-Operator-Key": "guess"},
        )
        assert r.status_code == 403

    def test_operator_key_permits_override(self, client: TestClient, runtime: Runtime) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="640.00", destination=ATTACKER_ACCOUNT)
        r = client.post(
            "/authorize?policy_set_version=payments-v1",
            json=env,
            headers={"X-ATP-Operator-Key": runtime.operator_key},
        )
        assert r.status_code == 200
        assert r.json()["decision"]["policy_set_version"] == "payments-v1"

    def test_default_policy_set_needs_no_key(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="640.00", destination=ATTACKER_ACCOUNT)
        r = client.post("/authorize", json=env)
        assert r.status_code == 200
        assert r.json()["decision"]["outcome"] == "DENY"


class TestInputHardening:
    def test_sub_cent_padding_cannot_slip_under_the_limit(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"], amount="1000.004")
        auth = _authorize(client, env)
        assert auth["decision"]["outcome"] == "DENY"
        assert auth["decision"]["reason_code"] == "PAYMENT_ARGUMENTS_INVALID"

    def test_oversized_arguments_are_rejected(self, client: TestClient) -> None:
        grants = seed_chain(client)
        env = payment_envelope(grants["ap"])
        env["arguments"]["memo"] = "x" * 20_000
        r = client.post("/authorize", json=env)
        assert r.status_code == 422

    def test_agent_cannot_write_events_as_the_gateway(self, client: TestClient) -> None:
        r = client.post(
            "/traces/dddddddddddd/events",
            json={"event_type": "task_received", "actor": "gateway", "payload": {}},
        )
        assert r.status_code == 409
        assert r.json()["reason_code"] == "EVENT_ACTOR_RESERVED"

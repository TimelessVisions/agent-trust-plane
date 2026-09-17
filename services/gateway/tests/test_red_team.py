"""Red-team tests: each one is an attempt to get an action executed without a
valid authorization for *that* action. Every test asserts both the reason code
and that the ledger stays empty (or has exactly the expected entries)."""

from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from atp_core import ActionEnvelope
from atp_gateway import Runtime
from atp_gateway.grants import GrantSigner, new_grant_claims

from gateway_fixtures import (
    ATTACKER_ACCOUNT,
    DOC_AGENT,
    ORCHESTRATOR,
    Clock,
    authorize,
    bearer,
    execute,
    ledger,
    op,
    payment_envelope,
    seed_chain,
)


class TestDirectExecutionBypass:
    def test_execute_without_authorize(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        res = execute(client, env, None, g["tokens"]["ap"])
        assert res["status"] == "blocked" and res["reason_code"] == "GRANT_MISSING"
        assert ledger(client) == []

    def test_client_asserted_authorized_flag_is_rejected(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], authorized=True)
        h = bearer(g["tokens"]["ap"])
        r = client.post("/execute", json={"envelope": env, "execution_grant": None}, headers=h)
        assert r.status_code == 422  # extra field forbidden by the envelope schema
        r = client.post("/authorize", json=env, headers=h)
        assert r.status_code == 422
        assert ledger(client) == []

    def test_extra_top_level_execute_fields_are_rejected(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"])
        r = client.post(
            "/execute",
            json={"envelope": env, "authorized": True},
            headers=bearer(g["tokens"]["ap"]),
        )
        assert r.status_code == 422


class TestForgedGrants:
    def test_grant_signed_with_wrong_key(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"])
        # Attacker knows the token format and builds a perfectly-shaped grant.
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
        res = execute(client, env, forged, g["tokens"]["ap"])
        assert res["status"] == "blocked"
        assert res["reason_code"] == "GRANT_SIGNATURE_INVALID"
        assert ledger(client) == []

    def test_grant_with_edited_expiry(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"])
        token = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        body_b64, sig = token.split(".")
        body = json.loads(base64.urlsafe_b64decode(body_b64 + "=" * (-len(body_b64) % 4)))
        body["expires_at"] = "2099-01-01T00:00:00+00:00"
        edited = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
        res = execute(client, env, f"{edited}.{sig}", g["tokens"]["ap"])
        assert res["reason_code"] == "GRANT_SIGNATURE_INVALID"
        assert ledger(client) == []

    def test_garbage_token(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"])
        res = execute(client, env, "definitely.not.a.grant", g["tokens"]["ap"])
        assert res["status"] == "blocked"
        assert res["reason_code"] in {"GRANT_MALFORMED", "GRANT_SIGNATURE_INVALID"}


class TestModifiedActionAfterAuthorization:
    def test_amount_changed_after_authorize(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        token = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        tampered = {**env, "arguments": {"amount": "12500.00", "currency": "USD"}}
        res = execute(client, tampered, token, g["tokens"]["ap"])
        assert res["status"] == "blocked"
        assert res["reason_code"] == "GRANT_ENVELOPE_MISMATCH"
        assert ledger(client) == []

    def test_destination_changed_after_authorize(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        token = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        tampered = {
            **env,
            "arguments": {**env["arguments"], "destination_account": ATTACKER_ACCOUNT},
        }
        res = execute(client, tampered, token, g["tokens"]["ap"])
        assert res["reason_code"] == "GRANT_ENVELOPE_MISMATCH"
        assert ledger(client) == []

    def test_resource_changed_after_authorize(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        token = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        res = execute(client, {**env, "resource": "vendor:999"}, token, g["tokens"]["ap"])
        assert res["reason_code"] == "GRANT_ENVELOPE_MISMATCH"

    def test_grant_reused_for_a_different_envelope(self, client: TestClient) -> None:
        """Two identical-looking payments: the grant for one cannot execute the other."""
        g = seed_chain(client)
        first = payment_envelope(g["ap"], amount="480.00")
        second = payment_envelope(g["ap"], amount="480.00")
        token = authorize(client, first, g["tokens"]["ap"])["execution_grant"]["token"]
        res = execute(client, second, token, g["tokens"]["ap"])
        assert res["reason_code"] == "GRANT_ENVELOPE_MISMATCH"
        assert ledger(client) == []


class TestGrantReplay:
    def test_grant_cannot_be_used_twice(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        token = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        assert execute(client, env, token, g["tokens"]["ap"])["status"] == "completed"
        res = execute(client, env, token, g["tokens"]["ap"])
        assert res["status"] == "blocked"
        assert res["reason_code"] == "GRANT_ALREADY_CONSUMED"
        assert len(ledger(client)) == 1

    def test_grant_expires(self, client: TestClient, clock: Clock) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        token = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        clock.advance(seconds=121)
        res = execute(client, env, token, g["tokens"]["ap"])
        assert res["reason_code"] == "GRANT_EXPIRED"
        assert ledger(client) == []

    def test_grant_from_another_gateway_instance_is_unknown(
        self, client: TestClient, runtime: Runtime
    ) -> None:
        """Valid signature (same key) but no server-side record: e.g. a token
        minted before a database reset. State, not just signature, is required."""
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
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
        res = execute(client, env, token, g["tokens"]["ap"])
        assert res["reason_code"] == "GRANT_NOT_FOUND"
        assert ledger(client) == []


class TestAuthorityBoundaries:
    def test_compromised_child_uses_own_grant_to_pay(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["doc"], agent=DOC_AGENT, amount="900.00")
        auth = authorize(client, env, g["tokens"]["doc"])
        assert auth["decision"]["outcome"] == "DENY"
        assert auth["decision"]["reason_code"] == "CAPABILITY_NOT_GRANTED"
        assert auth["execution_grant"] is None

    def test_compromised_child_presents_parents_grant(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], agent=DOC_AGENT, amount="900.00")
        auth = authorize(client, env, g["tokens"]["doc"])
        assert auth["decision"]["reason_code"] == "DELEGATION_GRANTEE_MISMATCH"

    def test_compromised_child_cannot_widen_its_own_grant(self, client: TestClient) -> None:
        g = seed_chain(client)
        r = client.post(
            "/delegations",
            json={
                "label": "self-upgrade",
                "grantor": DOC_AGENT.model_dump(mode="json"),
                "grantee": {"id": "document-agent-v2", "kind": "agent"},
                "parent_grant_id": g["doc"],
                "capabilities": ["read:invoice", "pay:vendor"],
                "resource_scope": ["invoice:*", "vendor:*"],
                "constraints": {"max_amount": {"amount": "5000", "currency": "USD"}},
                "expires_at": "2026-09-16T12:30:00Z",
            },
            headers=bearer(g["tokens"]["doc"]),
        )
        assert r.status_code == 422
        assert r.json()["reason_code"] == "DELEGATION_EXCEEDS_PARENT_CAPABILITIES"

    def test_resource_mismatch(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], resource="payroll:employee-7", amount="50.00")
        auth = authorize(client, env, g["tokens"]["ap"])
        assert auth["decision"]["outcome"] == "DENY"
        codes = {e["reason_code"] for e in auth["decision"]["evaluations"]}
        assert "RESOURCE_OUT_OF_SCOPE" in codes

    def test_expired_delegation(self, client: TestClient, clock: Clock) -> None:
        g = seed_chain(client)
        clock.advance(days=2)  # AP grant lasted 1 day
        env = payment_envelope(g["ap"], amount="50.00")
        auth = authorize(client, env, g["tokens"]["ap"])
        assert auth["decision"]["reason_code"] == "DELEGATION_EXPIRED"
        assert auth["execution_grant"] is None

    def test_delegation_revoked_between_authorize_and_execute(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        token = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        assert client.post(f"/delegations/{g['orch']}/revoke", headers=op()).status_code == 200
        res = execute(client, env, token, g["tokens"]["ap"])
        assert res["status"] == "blocked"
        assert res["reason_code"] == "DELEGATION_REVOKED"
        assert ledger(client) == []

    def test_unknown_grant_id(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope("grt_forged_id", amount="1.00")
        auth = authorize(client, env, g["tokens"]["ap"])
        assert auth["decision"]["reason_code"] == "DELEGATION_NOT_FOUND"

    def test_orchestrator_cannot_use_ap_agents_grant(self, client: TestClient) -> None:
        """Even the parent cannot act under a child's grant; grants bind to grantees."""
        g = seed_chain(client)
        env = payment_envelope(g["ap"], agent=ORCHESTRATOR, amount="480.00")
        auth = authorize(client, env, g["tokens"]["orch"])
        assert auth["decision"]["reason_code"] == "DELEGATION_GRANTEE_MISMATCH"


class TestPolicySelection:
    """An agent must not be able to pick which policy set judges it."""

    def test_agent_cannot_select_weaker_policy_set(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="640.00", destination=ATTACKER_ACCOUNT)
        r = client.post(
            "/authorize?policy_set_version=payments-v1", json=env, headers=bearer(g["tokens"]["ap"])
        )
        assert r.status_code == 403
        assert r.json()["reason_code"] == "POLICY_SET_OVERRIDE_FORBIDDEN"
        assert ledger(client) == []

    def test_wrong_operator_key_is_rejected(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="640.00", destination=ATTACKER_ACCOUNT)
        r = client.post(
            "/authorize?policy_set_version=payments-v1",
            json=env,
            headers={**bearer(g["tokens"]["ap"]), "X-ATP-Operator-Key": "guess"},
        )
        assert r.status_code == 403

    def test_operator_key_alone_is_not_an_agent(self, client: TestClient) -> None:
        """The operator key is not an agent credential; /authorize still needs one."""
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="10.00")
        r = client.post("/authorize?policy_set_version=payments-v1", json=env, headers=op())
        assert r.status_code == 401
        assert r.json()["reason_code"] == "AGENT_CREDENTIAL_MISSING"

    def test_default_policy_set_needs_no_key(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="640.00", destination=ATTACKER_ACCOUNT)
        auth = authorize(client, env, g["tokens"]["ap"])
        assert auth["decision"]["outcome"] == "DENY"


class TestInputHardening:
    def test_sub_cent_padding_cannot_slip_under_the_limit(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="1000.004")
        auth = authorize(client, env, g["tokens"]["ap"])
        assert auth["decision"]["outcome"] == "DENY"
        assert auth["decision"]["reason_code"] == "PAYMENT_ARGUMENTS_INVALID"

    def test_oversized_arguments_are_rejected(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"])
        env["arguments"]["memo"] = "x" * 20_000
        r = client.post("/authorize", json=env, headers=bearer(g["tokens"]["ap"]))
        assert r.status_code == 422


class TestTraceIntegrity:
    def test_tampering_with_stored_event_is_detected(
        self, client: TestClient, runtime: Runtime
    ) -> None:
        if runtime.conn is not None:
            self._tamper_sqlite(client, runtime)
        else:
            self._tamper_memory(client, runtime)

    def _tamper_memory(self, client: TestClient, runtime: Runtime) -> None:
        import copy

        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="12500.00")
        authorize(client, env, g["tokens"]["ap"])
        events = runtime.trust_plane.traces._events  # type: ignore[attr-defined]
        idx = next(i for i, e in enumerate(events) if e.event_type.value == "decision_made")
        payload = copy.deepcopy(events[idx].payload)
        payload["decision"]["outcome"] = "ALLOW"
        payload["decision"]["reason_code"] = "ALLOWED"
        events[idx] = events[idx].model_copy(update={"payload": payload})
        trace = client.get(f"/traces/{env['trace_id']}", headers=op()).json()
        assert trace["integrity"]["valid"] is False
        assert trace["integrity"]["first_bad_seq"] == events[idx].seq

    def _tamper_sqlite(self, client: TestClient, runtime: Runtime) -> None:
        """A database-level edit (what an insider with DB access would do)."""
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="12500.00")
        authorize(client, env, g["tokens"]["ap"])
        conn = runtime.conn
        assert conn is not None
        row = conn.execute(
            "SELECT seq, payload FROM trace_events WHERE trace_id = ? AND event_type = ?",
            (env["trace_id"], "decision_made"),
        ).fetchone()
        payload = json.loads(row[1])
        payload["decision"]["outcome"] = "ALLOW"
        conn.execute(
            "UPDATE trace_events SET payload = ? WHERE seq = ?", (json.dumps(payload), row[0])
        )
        conn.commit()
        trace = client.get(f"/traces/{env['trace_id']}", headers=op()).json()
        assert trace["integrity"]["valid"] is False
        assert trace["integrity"]["first_bad_seq"] == row[0]

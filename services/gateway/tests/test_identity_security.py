"""Security regression tests for authenticated agent identity.

Every test here is a concrete impersonation, forgery, or bypass attempt made
through the real HTTP routes with real credentials. Nothing is mocked; a DENY
or 401/403 comes from the gateway's own checks and is confirmed against the
ledger and the trace.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atp_core import PrincipalKind, PrincipalRef, ReasonCode
from atp_gateway import GatewaySettings, Runtime, build_runtime, create_app
from atp_gateway.grants import SqliteGrantStore, new_grant_claims
from atp_gateway.tools import PaymentsTool
from atp_identity import CredentialService, InMemoryCredentialStore

from gateway_fixtures import (
    AP_AGENT,
    DOC_AGENT,
    HUMAN,
    NOW,
    OPERATOR_KEY,
    ORCHESTRATOR,
    SIGNING_KEY,
    Clock,
    authorize,
    bearer,
    execute,
    issue_credential,
    ledger,
    op,
    payment_envelope,
    seed_chain,
)

STRANGER = PrincipalRef(id="some-other-agent", kind=PrincipalKind.AGENT)


# ------------------------------------------------------------ impersonation
class TestImpersonation:
    def test_agent_a_impersonating_agent_b(self, client: TestClient) -> None:
        """Doc agent (valid credential) submits an envelope claiming to be the AP agent."""
        g = seed_chain(client)
        env = payment_envelope(g["ap"], agent=AP_AGENT, amount="480.00")
        r = client.post("/authorize", json=env, headers=bearer(g["tokens"]["doc"]))
        assert r.status_code == 403
        assert r.json()["reason_code"] == "AGENT_IDENTITY_MISMATCH"
        assert ledger(client) == []
        # The attempt is on the record, attributed to the real credential.
        trace = client.get(f"/traces/{env['trace_id']}", headers=op()).json()
        assert trace["events"][0]["event_type"] == "identity_rejected"
        assert trace["events"][0]["payload"]["credential_id"] == g["creds"]["doc"]
        assert trace["events"][0]["payload"]["authenticated_agent"]["id"] == DOC_AGENT.id
        assert trace["events"][0]["payload"]["claimed_agent"]["id"] == AP_AGENT.id
        assert trace["integrity"]["valid"]

    def test_agent_a_using_agent_b_delegation_honestly(self, client: TestClient) -> None:
        """Doc agent names itself but presents the AP agent's grant."""
        g = seed_chain(client)
        env = payment_envelope(g["ap"], agent=DOC_AGENT, amount="480.00")
        auth = authorize(client, env, g["tokens"]["doc"])
        assert auth["decision"]["outcome"] == "DENY"
        assert auth["decision"]["reason_code"] == "DELEGATION_GRANTEE_MISMATCH"
        assert auth["execution_grant"] is None

    def test_stranger_with_valid_credential_and_stolen_grant_id(self, client: TestClient) -> None:
        g = seed_chain(client)
        stranger = issue_credential(client, STRANGER)["token"]
        env = payment_envelope(g["ap"], agent=STRANGER, amount="1.00")
        auth = authorize(client, env, stranger)
        assert auth["decision"]["reason_code"] == "DELEGATION_GRANTEE_MISMATCH"
        env2 = payment_envelope(g["ap"], agent=AP_AGENT, amount="1.00")
        assert client.post("/authorize", json=env2, headers=bearer(stranger)).status_code == 403

    def test_execute_with_someone_elses_grant_token(self, client: TestClient) -> None:
        """AP agent authorizes; doc agent steals the execution grant *and* the envelope."""
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        grant = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        r = client.post(
            "/execute",
            json={"envelope": env, "execution_grant": grant},
            headers=bearer(g["tokens"]["doc"]),
        )
        assert r.status_code == 403
        # The stolen envelope carries the AP agent's trace, so trace ownership
        # fires first; either refusal is correct and both are 403.
        assert r.json()["reason_code"] in {"TRACE_OWNED_BY_OTHER_AGENT", "AGENT_IDENTITY_MISMATCH"}
        assert ledger(client) == []
        # And the rightful agent can still use it exactly once.
        assert execute(client, env, grant, g["tokens"]["ap"])["status"] == "completed"

    def test_grant_audience_is_enforced_even_if_identity_binding_passed(
        self, client: TestClient, runtime: Runtime
    ) -> None:
        """Defence in depth: a grant whose claims name another agent is refused
        at the audience check, independently of the envelope binding."""
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        from atp_core import ActionEnvelope

        parsed = ActionEnvelope.model_validate(env)
        claims = new_grant_claims(
            trace_id=parsed.trace_id,
            decision_id="dec_x",
            envelope_id=parsed.envelope_id,
            action_hash=parsed.action_hash,
            agent_id=DOC_AGENT.id,  # audience: document agent
            policy_set_version="payments-v2",
            ttl_seconds=120,
            now=runtime.trust_plane.clock(),
        )
        runtime.trust_plane.grants.issue(claims)
        token = runtime.trust_plane.signer.mint(claims)
        res = execute(client, env, token, g["tokens"]["ap"])
        assert res["reason_code"] == "GRANT_AUDIENCE_MISMATCH"
        assert ledger(client) == []


# ------------------------------------------------------------------ forgery
class TestForgery:
    def test_forging_the_human_principal(self, client: TestClient) -> None:
        """AP agent claims to act for a different human than the chain's root."""
        g = seed_chain(client)
        other = PrincipalRef(id="ceo", kind=PrincipalKind.HUMAN)
        env = payment_envelope(g["ap"], principal=other, amount="480.00")
        auth = authorize(client, env, g["tokens"]["ap"])
        assert auth["decision"]["outcome"] == "DENY"
        assert auth["decision"]["reason_code"] == "DELEGATION_PRINCIPAL_MISMATCH"

    def test_forging_human_authority_via_delegation(self, client: TestClient) -> None:
        """An agent tries to issue a grant in the human's name (grantor = human)."""
        g = seed_chain(client)
        r = client.post(
            "/delegations",
            json={
                "label": "forged",
                "grantor": HUMAN.model_dump(mode="json"),
                "grantee": AP_AGENT.model_dump(mode="json"),
                "parent_grant_id": g["root"],
                "capabilities": ["admin:vendors"],
                "resource_scope": ["vendor:*"],
                "constraints": {"max_amount": {"amount": "10000", "currency": "USD"}},
                "expires_at": "2026-09-17T00:00:00Z",
            },
            headers=bearer(g["tokens"]["ap"]),
        )
        assert r.status_code == 403
        assert r.json()["reason_code"] == "OPERATOR_KEY_REQUIRED"

    def test_delegating_on_behalf_of_another_agent(self, client: TestClient) -> None:
        g = seed_chain(client)
        r = client.post(
            "/delegations",
            json={
                "label": "as-orchestrator",
                "grantor": ORCHESTRATOR.model_dump(mode="json"),
                "grantee": DOC_AGENT.model_dump(mode="json"),
                "parent_grant_id": g["orch"],
                "capabilities": ["pay:vendor"],
                "resource_scope": ["vendor:*"],
                "constraints": {"max_amount": {"amount": "9000", "currency": "USD"}},
                "expires_at": "2026-09-17T00:00:00Z",
            },
            headers=bearer(g["tokens"]["doc"]),
        )
        assert r.status_code == 403
        assert r.json()["reason_code"] == "AGENT_IDENTITY_MISMATCH"

    def test_forging_audit_actor(self, client: TestClient) -> None:
        """There is no actor field; the actor is whoever authenticated."""
        g = seed_chain(client)
        r = client.post(
            "/traces/aaaaaaaaaaaa/events",
            json={"event_type": "task_received", "actor": "gateway", "payload": {}},
            headers=bearer(g["tokens"]["doc"]),
        )
        assert r.status_code == 422  # unknown field
        r = client.post(
            "/traces/aaaaaaaaaaaa/events",
            json={"event_type": "task_received", "payload": {"actor": "gateway"}},
            headers=bearer(g["tokens"]["doc"]),
        )
        assert r.status_code == 200
        assert r.json()["actor"] == DOC_AGENT.id
        assert r.json()["payload"]["credential_id"] == g["creds"]["doc"]

    def test_unauthenticated_provenance_is_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/traces/aaaaaaaaaaaa/events", json={"event_type": "task_received", "payload": {}}
        )
        assert r.status_code == 401
        assert (
            client.get("/traces/aaaaaaaaaaaa", headers=op()).status_code == 404
        )  # nothing written


# ------------------------------------------------------------- credentials
class TestCredentialEnforcement:
    def test_execute_without_identity(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        grant = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        r = client.post("/execute", json={"envelope": env, "execution_grant": grant})
        assert r.status_code == 401
        assert r.json()["reason_code"] == "AGENT_CREDENTIAL_MISSING"
        assert r.headers["WWW-Authenticate"] == "Bearer"
        assert ledger(client) == []

    @pytest.mark.parametrize(
        "header",
        [
            "Bearer nope",
            "Bearer atpa_cred_00000000000000000000000000000000.secret",
            "Basic YWJj",
            "atpa_x.y",
        ],
    )
    def test_malformed_or_unknown_credentials(self, client: TestClient, header: str) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"])
        r = client.post("/authorize", json=env, headers={"Authorization": header})
        assert r.status_code == 401
        assert r.json()["reason_code"] == "AGENT_CREDENTIAL_INVALID"

    def test_wrong_secret_for_real_credential_id(self, client: TestClient) -> None:
        g = seed_chain(client)
        cred_id = g["creds"]["ap"]
        env = payment_envelope(g["ap"])
        r = client.post("/authorize", json=env, headers=bearer(f"atpa_{cred_id}.wrong-secret"))
        assert r.status_code == 401
        assert r.json()["reason_code"] == "AGENT_CREDENTIAL_INVALID"

    def test_revoked_credential(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        grant = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        assert (
            client.post(f"/credentials/{g['creds']['ap']}/revoke", headers=op()).status_code == 200
        )
        r = client.post(
            "/execute",
            json={"envelope": env, "execution_grant": grant},
            headers=bearer(g["tokens"]["ap"]),
        )
        assert r.status_code == 401
        assert r.json()["reason_code"] == "AGENT_CREDENTIAL_REVOKED"
        assert ledger(client) == []
        # Revocation is enforced everywhere, not just on execute.
        r = client.post(
            "/authorize", json=payment_envelope(g["ap"]), headers=bearer(g["tokens"]["ap"])
        )
        assert r.status_code == 401

    def test_expired_credential(self, client: TestClient, clock: Clock) -> None:
        r = client.post(
            "/agents/short-lived/credentials",
            json={
                "agent": {"id": "short-lived", "kind": "agent"},
                "label": "ttl",
                "expires_at": (NOW.replace(hour=13)).isoformat(),
            },
            headers=op(),
        )
        token = r.json()["token"]
        clock.advance(hours=2)
        r = client.post(
            "/traces/aaaaaaaaaaaa/events",
            json={"event_type": "task_received", "payload": {}},
            headers=bearer(token),
        )
        assert r.status_code == 401
        assert r.json()["reason_code"] == "AGENT_CREDENTIAL_EXPIRED"

    def test_secrets_never_appear_in_responses_or_traces(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        grant = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        execute(client, env, grant, g["tokens"]["ap"])
        import json

        blobs = [
            json.dumps(client.get(f"/traces/{env['trace_id']}", headers=op()).json()),
            json.dumps(client.get("/traces", headers=op()).json()),
            json.dumps(
                client.get("/agents/accounts-payable-agent/credentials", headers=op()).json()
            ),
            json.dumps(client.get("/delegations", headers=op()).json()),
            json.dumps(client.get("/health", headers=op()).json()),
        ]
        for blob in blobs:
            for secret in (*g["tokens"].values(), OPERATOR_KEY, SIGNING_KEY):
                assert secret not in blob
            assert "secret_hash" not in blob

    def test_error_messages_do_not_echo_credentials(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"])
        bad = "atpa_cred_deadbeef.this-secret-must-not-be-echoed"
        r = client.post("/authorize", json=env, headers=bearer(bad))
        assert "this-secret-must-not-be-echoed" not in r.text
        r = client.post(
            "/authorize?policy_set_version=payments-v1",
            json=env,
            headers={**bearer(g["tokens"]["ap"]), "X-ATP-Operator-Key": "guessed-operator-key"},
        )
        assert "guessed-operator-key" not in r.text


# -------------------------------------------------------- concurrency / atomicity
class TestConcurrentGrantConsumption:
    def test_simultaneous_execution_against_one_grant(self, runtime: Runtime) -> None:
        """Eight threads race to execute the same grant through the real app.
        Exactly one may settle."""
        app = create_app(runtime.settings, runtime=runtime)
        with TestClient(app) as setup:
            g = seed_chain(setup)
            env = payment_envelope(g["ap"], amount="480.00")
            grant = authorize(setup, env, g["tokens"]["ap"])["execution_grant"]["token"]

        n = 8
        barrier = threading.Barrier(n)
        results: list[dict[str, Any]] = []
        lock = threading.Lock()

        def attempt() -> None:
            with TestClient(app) as c:
                barrier.wait()
                r = c.post(
                    "/execute",
                    json={"envelope": env, "execution_grant": grant},
                    headers=bearer(g["tokens"]["ap"]),
                )
                with lock:
                    results.append(r.json())

        with ThreadPoolExecutor(max_workers=n) as pool:
            for _ in range(n):
                pool.submit(attempt)
        statuses = sorted(r["status"] for r in results)
        assert statuses.count("completed") == 1, results
        assert statuses.count("blocked") == n - 1
        assert {r["reason_code"] for r in results if r["status"] == "blocked"} == {
            "GRANT_ALREADY_CONSUMED"
        }
        with TestClient(app) as check:
            assert len(ledger(check)) == 1
            trace = check.get(f"/traces/{env['trace_id']}", headers=op()).json()
            assert trace["integrity"]["valid"]
            assert [e["event_type"] for e in trace["events"]].count("execution_completed") == 1

    def test_store_level_consume_is_atomic_without_the_service_lock(self, tmp_path: Path) -> None:
        """The SQLite conditional UPDATE alone must be single-winner, so
        atomicity does not depend on the TrustPlane lock."""
        import sqlite3

        path = tmp_path / "grants.db"
        conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        store = SqliteGrantStore(conn)
        claims = new_grant_claims(
            trace_id="a" * 12,
            decision_id="d",
            envelope_id="e",
            action_hash="f" * 64,
            agent_id="x",
            policy_set_version="payments-v2",
            ttl_seconds=60,
            now=NOW,
        )
        store.issue(claims)
        n = 16
        barrier = threading.Barrier(n)
        wins: list[bool] = []
        lock = threading.Lock()

        def consume() -> None:
            barrier.wait()
            try:
                store.consume(claims.grant_id, NOW)
                ok = True
            except Exception:
                ok = False
            with lock:
                wins.append(ok)

        with ThreadPoolExecutor(max_workers=n) as pool:
            for _ in range(n):
                pool.submit(consume)
        assert wins.count(True) == 1
        conn.close()


# --------------------------------------------------- revocation race, direct tool
class TestRevocationAndBypass:
    def test_execute_after_delegation_revoked_by_grantor(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        grant = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        # The orchestrator (grantor of the AP grant) revokes it with its own credential.
        r = client.post(f"/delegations/{g['ap']}/revoke", headers=bearer(g["tokens"]["orch"]))
        assert r.status_code == 200
        res = execute(client, env, grant, g["tokens"]["ap"])
        assert res["reason_code"] == "DELEGATION_REVOKED"
        assert ledger(client) == []

    def test_non_grantor_cannot_revoke(self, client: TestClient) -> None:
        g = seed_chain(client)
        r = client.post(f"/delegations/{g['ap']}/revoke", headers=bearer(g["tokens"]["doc"]))
        assert r.status_code == 403
        assert client.post(f"/delegations/{g['ap']}/revoke").status_code == 403

    def test_reads_are_operator_only(self, client: TestClient) -> None:
        """Traces, ledger and delegations expose decisions and accounts; a
        public deployment must not serve them anonymously."""
        g = seed_chain(client)
        env = payment_envelope(g["ap"])
        authorize(client, env, g["tokens"]["ap"])
        for path in (
            "/traces",
            f"/traces/{env['trace_id']}",
            "/ledger/payments",
            f"/delegations/{g['ap']}",
            f"/delegations/{g['ap']}/chain",
            "/vendors",
            "/evals/results",
        ):
            assert client.get(path).status_code == 403, path
            assert client.get(path, headers=bearer(g["tokens"]["ap"])).status_code == 403, path
            assert client.get(path, headers=op()).status_code == 200, path
        assert client.post(f"/replay/{env['trace_id']}", json={}).status_code == 403
        health = client.get("/health").json()
        assert "signing_key_fingerprint" not in health

    def test_agent_cannot_append_to_another_agents_trace(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        authorize(client, env, g["tokens"]["ap"])
        # doc agent tries to add provenance to the AP agent's trace
        r = client.post(
            f"/traces/{env['trace_id']}/events",
            json={"event_type": "task_received", "payload": {"task": "planted"}},
            headers=bearer(g["tokens"]["doc"]),
        )
        assert r.status_code == 403
        assert r.json()["reason_code"] == "TRACE_OWNED_BY_OTHER_AGENT"
        # and cannot trigger an identity_rejected event onto it either
        planted = payment_envelope(g["ap"], agent=AP_AGENT, trace_id=env["trace_id"])
        r = client.post("/authorize", json=planted, headers=bearer(g["tokens"]["doc"]))
        assert r.status_code == 403
        assert r.json()["reason_code"] == "TRACE_OWNED_BY_OTHER_AGENT"
        trace = client.get(f"/traces/{env['trace_id']}", headers=op()).json()
        assert all(e["actor"] in {AP_AGENT.id, "gateway"} for e in trace["events"])
        assert not any(e["event_type"] == "identity_rejected" for e in trace["events"])

    def test_revoked_credential_is_rechecked_under_the_lock(
        self, client: TestClient, runtime: Runtime
    ) -> None:
        """Even if the HTTP-layer check is bypassed (simulated by calling the
        service directly with a stale AuthenticatedAgent), a revoked credential
        cannot execute."""
        from atp_core import ActionEnvelope
        from atp_identity import AuthenticatedAgent, AuthError

        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")
        grant = authorize(client, env, g["tokens"]["ap"])["execution_grant"]["token"]
        stale = AuthenticatedAgent(agent=AP_AGENT, credential_id=g["creds"]["ap"])
        client.post(f"/credentials/{g['creds']['ap']}/revoke", headers=op())
        with pytest.raises(AuthError) as exc:
            runtime.trust_plane.execute(ActionEnvelope.model_validate(env), grant, stale)
        assert exc.value.reason_code is ReasonCode.AGENT_CREDENTIAL_REVOKED
        assert ledger(client) == []

    def test_no_route_reaches_a_tool_without_the_gateway(self, client: TestClient) -> None:
        """The only HTTP path to a tool is /execute. Nothing else mentions tools."""
        paths = {getattr(r, "path", "") for r in client.app.routes}  # type: ignore[attr-defined]
        assert not any("tool" in p or ("payment" in p and "ledger" not in p) for p in paths)

    def test_in_process_tool_call_is_not_protected(self, runtime: Runtime) -> None:
        """Documented limitation, not a claim: code that holds a direct
        reference to a tool can call it. The trust boundary is the gateway
        process; real tools must only accept calls from it (network policy,
        tool-side credentials held by the gateway). See docs/threat-model.md."""
        tool = runtime.trust_plane.tools.get("payments")
        assert isinstance(tool, PaymentsTool)
        from atp_core import ActionEnvelope

        env = ActionEnvelope.model_validate(payment_envelope("grt_none", amount="1.00"))
        before = len(runtime.ledger.all())
        tool.execute(env)  # no authorize, no grant, no identity
        assert len(runtime.ledger.all()) == before + 1


# ----------------------------------------------------------- configuration
class TestSecureDefaults:
    def test_persistent_gateway_refuses_to_start_without_keys(self, tmp_path: Path) -> None:
        from atp_gateway.settings import InsecureConfigurationError

        settings = GatewaySettings(
            database_path=str(tmp_path / "x.db"), grant_signing_key="", operator_key=""
        )
        with pytest.raises(InsecureConfigurationError):
            build_runtime(settings)

    def test_short_keys_are_refused(self, tmp_path: Path) -> None:
        from atp_gateway.settings import InsecureConfigurationError

        settings = GatewaySettings(
            database_path=str(tmp_path / "x.db"), grant_signing_key="short", operator_key="short"
        )
        with pytest.raises(InsecureConfigurationError):
            build_runtime(settings)

    def test_ephemeral_gateway_generates_keys(self) -> None:
        rt = build_runtime(GatewaySettings(database_path=":memory:"))
        assert len(rt.operator_key) >= 32
        rt.close()


class TestCredentialServiceUnit:
    def test_timing_safe_path_for_unknown_id(self) -> None:
        svc = CredentialService(InMemoryCredentialStore())
        with pytest.raises(Exception) as exc:
            svc.authenticate("atpa_cred_unknown.secret", now=NOW)
        assert getattr(exc.value, "reason_code", None) is ReasonCode.AGENT_CREDENTIAL_INVALID

    def test_token_round_trip_and_dump_excludes_hash(self) -> None:
        svc = CredentialService(InMemoryCredentialStore())
        cred, token = svc.issue(AP_AGENT, label="t", now=NOW)
        who = svc.authenticate(token, now=NOW)
        assert who.agent == AP_AGENT and who.credential_id == cred.credential_id
        assert "secret_hash" not in cred.model_dump()
        assert "secret_hash" not in repr(cred)

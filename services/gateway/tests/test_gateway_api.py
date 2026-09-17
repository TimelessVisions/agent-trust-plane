"""End-to-end behaviour of the gateway over HTTP: the happy path, the primary
demo denial, trace inspection, and replay. Every agent call is authenticated."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gateway_fixtures import (
    ATTACKER_ACCOUNT,
    DOC_AGENT,
    authorize,
    bearer,
    execute,
    ledger,
    op,
    payment_envelope,
    seed_chain,
)


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["default_policy_set"] == "payments-v2"
    assert body["tools"] == ["payments"]


class TestHappyPath:
    def test_normal_payment_authorizes_and_executes(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="480.00")

        auth = authorize(client, env, g["tokens"]["ap"])
        assert auth["decision"]["outcome"] == "ALLOW"
        assert auth["decision"]["reason_code"] == "ALLOWED"
        assert auth["execution_grant"] is not None
        token = auth["execution_grant"]["token"]

        result = execute(client, env, token, g["tokens"]["ap"])
        assert result["status"] == "completed"
        assert result["reason_code"] == "EXECUTION_COMPLETED"
        assert result["result"]["status"] == "settled"
        assert result["result"]["destination_account"] == "acct-nw-4471"

        rows = ledger(client)
        assert len(rows) == 1
        assert rows[0]["amount"] == "480.00"

        trace = client.get(f"/traces/{env['trace_id']}").json()
        types = [e["event_type"] for e in trace["events"]]
        assert types == [
            "action_proposed",
            "delegation_resolved",
            "policy_evaluated",
            "decision_made",
            "grant_issued",
            "execution_attempted",
            "execution_completed",
        ]
        assert trace["integrity"]["valid"] is True
        assert trace["execution"]["event_type"] == "execution_completed"
        assert len(trace["delegation_chain"]) == 3
        # The trace records which credential authenticated the proposal, never the secret.
        proposed = trace["events"][0]["payload"]
        assert proposed["credential_id"] == g["creds"]["ap"]
        assert g["tokens"]["ap"] not in trace_text(trace)


def trace_text(trace: dict[str, object]) -> str:
    import json

    return json.dumps(trace)


class TestPrimaryDemo:
    def test_injected_12500_payment_is_denied_and_never_executes(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="12500.00", destination=ATTACKER_ACCOUNT)

        auth = authorize(client, env, g["tokens"]["ap"])
        decision = auth["decision"]
        assert decision["outcome"] == "DENY"
        assert decision["reason_code"] == "PAYMENT_EXCEEDS_DELEGATED_AUTHORITY"
        assert decision["matched_policy"] == {"id": "payments.vendor.max_amount", "version": "v1"}
        assert decision["effective_authority"]["constraints"]["max_amount"] == {
            "amount": "1000.00",
            "currency": "USD",
        }
        assert auth["execution_grant"] is None

        # The agent tries anyway, with no grant.
        res = execute(client, env, None, g["tokens"]["ap"])
        assert res["status"] == "blocked"
        assert res["reason_code"] == "GRANT_MISSING"

        assert ledger(client) == []

        trace = client.get(f"/traces/{env['trace_id']}").json()
        types = [e["event_type"] for e in trace["events"]]
        assert types == [
            "action_proposed",
            "delegation_resolved",
            "policy_evaluated",
            "decision_made",
            "execution_attempted",
            "execution_blocked",
        ]

    def test_at_limit_requires_approval_and_issues_no_grant(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="1000.00")
        auth = authorize(client, env, g["tokens"]["ap"])
        assert auth["decision"]["outcome"] == "REQUIRE_APPROVAL"
        assert auth["decision"]["approval"]["approver_role"] == "finance-manager"
        assert auth["execution_grant"] is None
        trace = client.get(f"/traces/{env['trace_id']}").json()
        assert "approval_requested" in [e["event_type"] for e in trace["events"]]


class TestTraces:
    def test_unknown_trace_is_404(self, client: TestClient) -> None:
        r = client.get("/traces/000000000000")
        assert r.status_code == 404
        assert r.json()["reason_code"] == "TRACE_NOT_FOUND"

    def test_agent_can_record_provenance_but_not_gateway_events(self, client: TestClient) -> None:
        g = seed_chain(client)
        trace_id = "b" * 12
        r = client.post(
            f"/traces/{trace_id}/events",
            json={
                "event_type": "task_received",
                "payload": {"task": "Review invoice INV-2291 and pay if correct"},
            },
            headers=bearer(g["tokens"]["ap"]),
        )
        assert r.status_code == 200
        assert r.json()["actor"] == "accounts-payable-agent"
        r = client.post(
            f"/traces/{trace_id}/events",
            json={"event_type": "decision_made", "payload": {}},
            headers=bearer(g["tokens"]["ap"]),
        )
        assert r.status_code == 409
        assert r.json()["reason_code"] == "EVENT_TYPE_RESERVED"

    def test_list_traces(self, client: TestClient) -> None:
        g = seed_chain(client)
        for amount in ("10.00", "20.00"):
            authorize(client, payment_envelope(g["ap"], amount=amount), g["tokens"]["ap"])
        summaries = client.get("/traces").json()
        assert len(summaries) == 2
        assert summaries[0]["event_count"] == 5  # ALLOW path incl. grant_issued


class TestReplay:
    def test_replay_same_policy_reproduces_decision(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="12500.00")
        original = authorize(client, env, g["tokens"]["ap"])["decision"]
        r = client.post(f"/replay/{env['trace_id']}", json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["outcome_changed"] is False
        assert body["replayed_decision"]["outcome"] == "DENY"
        assert body["replayed_decision"]["reason_code"] == original["reason_code"]
        assert body["replayed_decision"]["replay_of"] == original["decision_id"]

    def test_replay_under_hardened_policy_flips_a_missed_attack(self, client: TestClient) -> None:
        """FAILURE -> POLICY CHANGE -> REPLAY -> PROVE IMPROVEMENT.

        Under payments-v1 an under-limit payment redirected to an attacker's
        account is allowed. Replaying the same trace under payments-v2 denies it.
        """
        g = seed_chain(client)
        env = payment_envelope(g["ap"], amount="640.00", destination=ATTACKER_ACCOUNT)
        auth = authorize(
            client,
            env,
            g["tokens"]["ap"],
            params={"policy_set_version": "payments-v1"},
            headers={**bearer(g["tokens"]["ap"]), **op()},
        )
        assert auth["decision"]["outcome"] == "ALLOW"
        assert auth["decision"]["policy_set_version"] == "payments-v1"

        r = client.post(f"/replay/{env['trace_id']}", json={"policy_set_version": "payments-v2"})
        body = r.json()
        assert body["outcome_changed"] is True
        assert body["replayed_decision"]["outcome"] == "DENY"
        assert body["replayed_decision"]["reason_code"] == "PAYMENT_DESTINATION_RESOURCE_MISMATCH"
        assert "payments-v1: ALLOW" in body["summary"] and "payments-v2: DENY" in body["summary"]

        trace = client.get(f"/traces/{env['trace_id']}").json()
        assert trace["events"][-1]["event_type"] == "replay_performed"
        assert trace["replays"][0]["execution"] == "not permitted on replay"
        assert trace["integrity"]["valid"] is True
        # Replay never touched the ledger.
        assert ledger(client) == []

    def test_replay_unknown_policy_set(self, client: TestClient) -> None:
        g = seed_chain(client)
        env = payment_envelope(g["ap"])
        authorize(client, env, g["tokens"]["ap"])
        r = client.post(f"/replay/{env['trace_id']}", json={"policy_set_version": "nope"})
        assert r.status_code == 404
        assert r.json()["reason_code"] == "POLICY_SET_NOT_FOUND"

    def test_replay_of_trace_without_proposal(self, client: TestClient) -> None:
        g = seed_chain(client)
        trace_id = "c" * 12
        client.post(
            f"/traces/{trace_id}/events",
            json={"event_type": "task_received", "payload": {}},
            headers=bearer(g["tokens"]["ap"]),
        )
        r = client.post(f"/replay/{trace_id}", json={})
        assert r.status_code == 409
        assert r.json()["reason_code"] == "TRACE_HAS_NO_PROPOSAL"


class TestDelegationApi:
    def test_chain_endpoint(self, client: TestClient) -> None:
        g = seed_chain(client)
        r = client.get(f"/delegations/{g['doc']}/chain")
        assert r.status_code == 200
        body = r.json()
        assert [x["grantee"]["id"] for x in body["grants"]][-1] == DOC_AGENT.id
        assert body["authority"]["capabilities"] == ["read:invoice"]

    def test_escalation_is_422_with_reason(self, client: TestClient) -> None:
        g = seed_chain(client)
        r = client.post(
            "/delegations",
            json={
                "label": "escalate",
                "grantor": {"id": "finance-orchestrator", "kind": "agent"},
                "grantee": {"id": "accounts-payable-agent", "kind": "agent"},
                "parent_grant_id": g["orch"],
                "capabilities": ["pay:vendor"],
                "resource_scope": ["vendor:*"],
                "constraints": {"max_amount": {"amount": "50000", "currency": "USD"}},
                "expires_at": "2026-09-17T00:00:00Z",
            },
            headers=bearer(g["tokens"]["orch"]),
        )
        assert r.status_code == 422
        assert r.json()["reason_code"] == "DELEGATION_EXCEEDS_PARENT_AMOUNT"

    def test_list_delegations_is_operator_only(self, client: TestClient) -> None:
        g = seed_chain(client)
        assert client.get("/delegations").status_code == 403
        assert client.get("/delegations", headers=bearer(g["tokens"]["ap"])).status_code == 403
        r = client.get("/delegations", headers=op())
        assert r.status_code == 200 and len(r.json()) == 4

    def test_policy_sets_catalog(self, client: TestClient) -> None:
        body = client.get("/policy-sets").json()
        versions = {p["version"]: p for p in body}
        assert versions["payments-v2"]["is_default"] is True
        assert len(versions["payments-v2"]["policies"]) == 8
        assert len(versions["payments-v1"]["policies"]) == 6


class TestCredentialLifecycle:
    def test_issue_list_revoke(self, client: TestClient) -> None:
        g = seed_chain(client)
        listed = client.get("/agents/accounts-payable-agent/credentials", headers=op()).json()
        assert [c["credential_id"] for c in listed] == [g["creds"]["ap"]]
        assert "token" not in listed[0] and "secret_hash" not in listed[0]
        r = client.post(f"/credentials/{g['creds']['ap']}/revoke", headers=op())
        assert r.status_code == 200 and r.json()["revoked_at"] is not None

    def test_credential_endpoints_need_operator(self, client: TestClient) -> None:
        g = seed_chain(client)
        body = {"agent": {"id": "x", "kind": "agent"}, "label": "l"}
        assert client.post("/agents/x/credentials", json=body).status_code == 403
        assert (
            client.post(
                "/agents/x/credentials", json=body, headers=bearer(g["tokens"]["ap"])
            ).status_code
            == 403
        )
        assert client.get("/agents/x/credentials").status_code == 403
        assert client.post(f"/credentials/{g['creds']['ap']}/revoke").status_code == 403

    def test_humans_do_not_get_credentials(self, client: TestClient) -> None:
        r = client.post(
            "/agents/company-user-42/credentials",
            json={"agent": {"id": "company-user-42", "kind": "human"}, "label": "no"},
            headers=op(),
        )
        assert r.status_code == 409
        assert r.json()["reason_code"] == "CREDENTIAL_SUBJECT_INVALID"

    def test_evals_run_is_operator_only(self, client: TestClient) -> None:
        assert client.post("/evals/run").status_code == 403

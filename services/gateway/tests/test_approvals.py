"""REQUIRE_APPROVAL -> POST /approvals/{trace} -> identical retry -> one grant.

Review Focus 4: an approval for action hash A cannot authorize B; an expired
approval or an approver without the role denies; one approval, one grant.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from atp_core import ActionEnvelope
from atp_gateway import GatewaySettings, Runtime, build_runtime, create_app

from gateway_fixtures import (
    GRANT_KEY_SETTINGS,
    OPERATOR_KEY,
    Clock,
    authorize,
    bearer,
    execute,
    ledger,
    op,
    payment_envelope,
    seed_chain,
)

ALICE = {"id": "alice", "kind": "human"}
MALLORY = {"id": "mallory", "kind": "human"}


def _setup(client: TestClient, runtime: Runtime) -> tuple[dict[str, Any], str, dict[str, Any]]:
    runtime.trust_plane.approver_roles = {
        "human:alice": frozenset({"finance-manager"}),
        "human:mallory": frozenset({"intern"}),
    }
    seed = seed_chain(client)
    token = seed["tokens"]["ap"]
    env = payment_envelope(seed["ap"], amount="1000.00")
    first = authorize(client, env, token)
    assert first["decision"]["outcome"] == "REQUIRE_APPROVAL"
    assert first["execution_grant"] is None
    return seed, token, env


def _approve(client: TestClient, trace_id: str, **body: Any) -> Any:
    payload = {"approver": ALICE, "decision": "approve", "expires_in": "15m", **body}
    return client.post(f"/approvals/{trace_id}", json=payload, headers=op())


def _events(client: TestClient, trace_id: str) -> list[str]:
    r = client.get(f"/traces/{trace_id}", headers=op())
    return [e["event_type"] for e in r.json()["events"]]


def test_approve_then_retry_issues_one_grant(client: TestClient, runtime: Runtime) -> None:
    _, token, env = _setup(client, runtime)
    r = _approve(client, env["trace_id"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["approver_role"] == "finance-manager"
    assert body["kid"] == runtime.trust_plane.signer.kid and body["signature"]

    retry = authorize(client, env, token)
    assert retry["decision"]["outcome"] == "ALLOW"
    assert retry["execution_grant"]["token"]
    done = execute(client, env, retry["execution_grant"]["token"], token)
    assert done["status"] == "completed"
    assert len(ledger(client)) == 1
    events = _events(client, env["trace_id"])
    assert "approval_granted" in events
    assert events.count("grant_issued") == 1


def test_approval_bound_to_action_hash(client: TestClient, runtime: Runtime) -> None:
    _, token, env = _setup(client, runtime)
    assert _approve(client, env["trace_id"]).status_code == 201
    modified = {**env, "arguments": {**env["arguments"], "amount": "999.00"}}
    out = authorize(client, modified, token)
    assert out["decision"]["outcome"] != "ALLOW"
    assert out["execution_grant"] is None
    # The approved action itself still works, once.
    assert authorize(client, env, token)["execution_grant"] is not None


def test_expired_approval_denies(client: TestClient, runtime: Runtime, clock: Clock) -> None:
    _, token, env = _setup(client, runtime)
    assert _approve(client, env["trace_id"], expires_in="60s").status_code == 201
    clock.advance(seconds=61)
    out = authorize(client, env, token)
    assert out["decision"]["outcome"] == "DENY"
    assert out["decision"]["reason_code"] == "APPROVAL_EXPIRED"
    assert out["execution_grant"] is None


def test_approver_without_role_rejected(client: TestClient, runtime: Runtime) -> None:
    _, token, env = _setup(client, runtime)
    for who in (MALLORY, {"id": "nobody", "kind": "human"}):
        r = _approve(client, env["trace_id"], approver=who)
        assert r.status_code == 403
        assert r.json()["reason_code"] == "APPROVER_ROLE_MISSING"
    # Operator key is required as well.
    r = client.post(
        f"/approvals/{env['trace_id']}", json={"approver": ALICE}, headers=bearer(token)
    )
    assert r.status_code == 403
    assert r.json()["reason_code"] == "OPERATOR_KEY_REQUIRED"
    assert authorize(client, env, token)["decision"]["outcome"] == "REQUIRE_APPROVAL"
    assert "approval_granted" not in _events(client, env["trace_id"])


def test_second_retry_is_already_used(client: TestClient, runtime: Runtime) -> None:
    _, token, env = _setup(client, runtime)
    assert _approve(client, env["trace_id"]).status_code == 201
    assert authorize(client, env, token)["execution_grant"] is not None
    again = authorize(client, env, token)
    assert again["decision"]["outcome"] == "DENY"
    assert again["decision"]["reason_code"] == "APPROVAL_ALREADY_USED"
    assert again["execution_grant"] is None


def test_deny_is_recorded_and_final(client: TestClient, runtime: Runtime) -> None:
    _, token, env = _setup(client, runtime)
    r = _approve(client, env["trace_id"], decision="deny")
    assert r.status_code == 201 and r.json()["status"] == "denied"
    assert "approval_denied" in _events(client, env["trace_id"])
    out = authorize(client, env, token)
    assert out["decision"]["outcome"] == "DENY"
    assert out["decision"]["reason_code"] == "APPROVAL_DENIED"
    again = _approve(client, env["trace_id"])
    assert again.status_code == 409
    assert again.json()["reason_code"] == "APPROVAL_ALREADY_DECIDED"
    assert authorize(client, env, token)["execution_grant"] is None


def test_approve_needs_a_require_approval_trace(client: TestClient, runtime: Runtime) -> None:
    seed, token, _ = _setup(client, runtime)
    small = payment_envelope(seed["ap"], amount="10.00")
    assert authorize(client, small, token)["decision"]["outcome"] == "ALLOW"
    r = _approve(client, small["trace_id"])
    assert r.status_code == 409 and r.json()["reason_code"] == "APPROVAL_NOT_REQUESTED"
    r = _approve(client, "0123456789ab")
    assert r.status_code == 404


def test_concurrent_retries_mint_one_grant(tmp_path: Path) -> None:
    """Two gateways on one SQLite file (two connections, as two processes
    would have) race the identical retry: exactly one gets a grant."""
    settings = GatewaySettings(
        database_path=str(tmp_path / "atp.db"),
        **GRANT_KEY_SETTINGS,
        operator_key=OPERATOR_KEY,
        approver_roles="human:alice=finance-manager",
    )
    a, b = build_runtime(settings), build_runtime(settings)
    clock = Clock()
    a.trust_plane.clock = b.trust_plane.clock = clock
    try:
        with TestClient(create_app(settings, runtime=a)) as client:
            seed = seed_chain(client)
            token = seed["tokens"]["ap"]
            env = payment_envelope(seed["ap"], amount="1000.00")
            assert authorize(client, env, token)["decision"]["outcome"] == "REQUIRE_APPROVAL"
            assert _approve(client, env["trace_id"]).status_code == 201

        envelope = ActionEnvelope.model_validate(env)
        results: list[Any] = []
        barrier = threading.Barrier(2)

        def retry(rt: Runtime) -> None:
            tp = rt.trust_plane
            caller = tp.identity.authenticate({"authorization": f"Bearer {token}"}, now=tp.clock())
            barrier.wait()
            results.append(tp.authorize(envelope, caller))

        threads = [threading.Thread(target=retry, args=(rt,)) for rt in (a, b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(results) == 2
        grants = [r for r in results if r.execution_grant is not None]
        assert len(grants) == 1
        loser = next(r for r in results if r.execution_grant is None)
        assert loser.decision.reason_code.value == "APPROVAL_ALREADY_USED"
    finally:
        a.close()
        b.close()

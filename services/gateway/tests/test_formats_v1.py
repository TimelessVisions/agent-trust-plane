"""1.0 file formats: versioned evidence bundles, a declared trace export
format, and a 422 that names fields without echoing what was sent."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from atp_core import canonical_hash
from atp_gateway.evidence import BUNDLE_VERSION, build_bundle, verify_bundle

from gateway_fixtures import authorize, op, payment_envelope, seed_chain


def _trace_id(client: TestClient) -> str:
    g = seed_chain(client)
    env = payment_envelope(g["ap"], amount="480.00")
    authorize(client, env, g["tokens"]["ap"])
    return str(env["trace_id"])


def _bundle(client: TestClient) -> dict[str, Any]:
    tp = client.app.state.runtime.trust_plane  # type: ignore[attr-defined]
    view = tp.get_trace(_trace_id(client))
    return build_bundle(view).model_dump(mode="json")


def test_bundle_v1_still_verifies(client: TestClient) -> None:
    current = _bundle(client)
    assert current["bundle_version"] == BUNDLE_VERSION == 2
    ok, detail = verify_bundle(current)
    assert ok, detail
    # A v1 bundle, exactly the shape 0.3.x wrote: no v2-only fields.
    v1 = {k: v for k, v in current.items() if k not in {"bundle_hash", "trace_format"}}
    v1["bundle_version"] = 1
    v1["bundle_hash"] = canonical_hash(v1)
    ok, detail = verify_bundle(v1)
    assert ok, detail


def test_unknown_bundle_version_rejected(client: TestClient) -> None:
    data = _bundle(client)
    for version in (0, 3, 99):
        body = {k: v for k, v in data.items() if k != "bundle_hash"}
        body["bundle_version"] = version
        body["bundle_hash"] = canonical_hash(body)
        ok, detail = verify_bundle(body)
        assert not ok
        assert "unsupported bundle_version" in detail


def test_trace_export_has_format(client: TestClient) -> None:
    trace_id = _trace_id(client)
    body = client.get(f"/traces/{trace_id}", headers=op()).json()
    assert body["format"] == "atp-trace/1"
    tp = client.app.state.runtime.trust_plane  # type: ignore[attr-defined]
    assert tp.get_trace(trace_id).model_dump(mode="json")["format"] == "atp-trace/1"
    assert _bundle(client)["trace_format"] == "atp-trace/1"


def test_422_does_not_echo_input(client: TestClient) -> None:
    secret = "sk-live-FAKE-0123456789abcdef"
    r = client.post(
        "/delegations",
        headers=op(),
        json={"principal": secret, "agent_id": 12345, "capabilities": secret},
    )
    assert r.status_code == 422
    assert secret not in r.text
    body = r.json()
    assert body["error"] == "request_invalid"
    assert isinstance(body["fields"], list) and body["fields"]
    assert all(isinstance(f, str) for f in body["fields"])
    # Malformed JSON is a 422 too, and still echoes nothing.
    r = client.post(
        "/delegations",
        headers={**op(), "content-type": "application/json"},
        content=b'{"x": "' + secret.encode() + b'"',
    )
    assert r.status_code == 422
    assert secret not in r.text
    # An invalid approval TTL must not be echoed either.
    trace_id = _trace_id(client)
    r = client.post(
        f"/approvals/{trace_id}",
        headers=op(),
        json={"approver": "human:alice", "decision": "approve", "expires_in": secret},
    )
    assert secret not in r.text
    json.loads(r.text)


def test_bundle_without_redactions_rejected(client: TestClient) -> None:
    # 0.3.x always wrote `redactions` (possibly empty); a bundle missing it
    # was not written by any ATP release, in either version.
    data = _bundle(client)
    for version in (1, 2):
        body = {k: v for k, v in data.items() if k not in {"bundle_hash", "redactions"}}
        if version == 1:
            body.pop("trace_format")
        body["bundle_version"] = version
        body["bundle_hash"] = canonical_hash(body)
        ok, detail = verify_bundle(body)
        assert not ok
        assert "redactions" in detail


def test_bundle_trace_format_is_a_literal(client: TestClient) -> None:
    data = _bundle(client)
    body = {k: v for k, v in data.items() if k != "bundle_hash"}
    body["trace_format"] = "atp-trace/99"
    body["bundle_hash"] = canonical_hash(body)
    ok, detail = verify_bundle(body)
    assert not ok
    assert "trace_format" in detail

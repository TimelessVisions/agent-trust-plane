"""C5 over HTTP: the operator key alone cannot create a root grant for a human."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from atp_identity import InMemoryPrincipalKeys, sign_root_request

from gateway_fixtures import HUMAN, NOW, op, sign_root_body


def _root_body() -> dict[str, Any]:
    return {
        "label": "Human authority",
        "grantor": HUMAN.model_dump(mode="json"),
        "grantee": HUMAN.model_dump(mode="json"),
        "capabilities": ["pay:vendor"],
        "resource_scope": ["vendor:*"],
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
    }


def test_operator_cannot_forge_root(client: TestClient) -> None:
    # The operator key alone: no signature.
    r = client.post("/delegations", json=_root_body(), headers=op())
    assert r.status_code == 422, r.text
    assert r.json()["reason_code"] == "DELEGATION_ROOT_UNSIGNED"

    # The operator signs with a key of its own making: not the human's key.
    mine = InMemoryPrincipalKeys()
    mine.add(HUMAN.id, Ed25519PrivateKey.generate())
    forged = sign_root_request(_root_body(), mine, now=NOW)
    assert forged["signature"]
    r = client.post("/delegations", json=forged, headers=op())
    assert r.status_code == 422, r.text
    assert r.json()["reason_code"] == "DELEGATION_ROOT_SIGNATURE_INVALID"

    # A real signature over different content: widened after signing.
    signed = sign_root_body(_root_body())
    widened = {**signed, "capabilities": ["pay:vendor", "admin:vendors"]}
    r = client.post("/delegations", json=widened, headers=op())
    assert r.json()["reason_code"] == "DELEGATION_ROOT_SIGNATURE_INVALID"

    # The human's signature still needs the operator to register it.
    r = client.post("/delegations", json=signed)
    assert r.json()["reason_code"] == "OPERATOR_KEY_REQUIRED"

    r = client.post("/delegations", json=signed, headers=op())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["grant_id"] == signed["grant_id"]
    assert body["signature"] == signed["signature"] and body["signer_kid"]
    chain = client.get(f"/delegations/{body['grant_id']}/chain", headers=op())
    assert chain.status_code == 200, chain.text

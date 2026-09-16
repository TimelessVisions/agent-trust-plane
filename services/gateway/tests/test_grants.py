"""Unit tests for the execution grant primitive."""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Iterator
from datetime import timedelta

import pytest

from atp_core import GrantError, ReasonCode
from atp_gateway.grants import (
    GrantClaims,
    GrantSigner,
    GrantStatus,
    GrantStore,
    InMemoryGrantStore,
    SqliteGrantStore,
    new_grant_claims,
)

from gateway_fixtures import NOW

KEY = b"k" * 32
OTHER_KEY = b"x" * 32


def claims() -> GrantClaims:
    return new_grant_claims(
        trace_id="a" * 12,
        decision_id="dec_1",
        envelope_id="env_1",
        action_hash="f" * 64,
        agent_id="accounts-payable-agent",
        policy_set_version="payments-v2",
        ttl_seconds=120,
        now=NOW,
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest) -> Iterator[GrantStore]:
    if request.param == "memory":
        yield InMemoryGrantStore()
    else:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        yield SqliteGrantStore(conn)
        conn.close()


class TestSigner:
    def test_round_trip(self) -> None:
        signer = GrantSigner(KEY)
        c = claims()
        token = signer.mint(c)
        assert signer.verify(token) == c

    def test_wrong_key_is_rejected(self) -> None:
        token = GrantSigner(KEY).mint(claims())
        with pytest.raises(GrantError) as exc:
            GrantSigner(OTHER_KEY).verify(token)
        assert exc.value.reason_code is ReasonCode.GRANT_SIGNATURE_INVALID

    def test_tampered_body_is_rejected(self) -> None:
        signer = GrantSigner(KEY)
        token = signer.mint(claims())
        body_b64, sig_b64 = token.split(".")
        body = json.loads(base64.urlsafe_b64decode(body_b64 + "=" * (-len(body_b64) % 4)))
        body["expires_at"] = (NOW + timedelta(days=365)).isoformat()
        forged_body = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
        with pytest.raises(GrantError) as exc:
            signer.verify(f"{forged_body}.{sig_b64}")
        assert exc.value.reason_code is ReasonCode.GRANT_SIGNATURE_INVALID

    @pytest.mark.parametrize("token", ["", "garbage", "a.b", "a.b.c", "not-base64!.x"])
    def test_malformed_tokens(self, token: str) -> None:
        with pytest.raises(GrantError) as exc:
            GrantSigner(KEY).verify(token)
        assert exc.value.reason_code in {
            ReasonCode.GRANT_MALFORMED,
            ReasonCode.GRANT_SIGNATURE_INVALID,
        }

    def test_short_key_rejected(self) -> None:
        with pytest.raises(ValueError):
            GrantSigner(b"short")


class TestStore:
    def test_single_use(self, store: GrantStore) -> None:
        c = claims()
        store.issue(c)
        first = store.consume(c.grant_id, NOW)
        assert first.status is GrantStatus.CONSUMED
        with pytest.raises(GrantError) as exc:
            store.consume(c.grant_id, NOW)
        assert exc.value.reason_code is ReasonCode.GRANT_ALREADY_CONSUMED

    def test_unknown_grant(self, store: GrantStore) -> None:
        with pytest.raises(GrantError) as exc:
            store.consume("xg_nope", NOW)
        assert exc.value.reason_code is ReasonCode.GRANT_NOT_FOUND

    def test_revoked_grant(self, store: GrantStore) -> None:
        c = claims()
        store.issue(c)
        store.revoke(c.grant_id)
        with pytest.raises(GrantError) as exc:
            store.consume(c.grant_id, NOW)
        assert exc.value.reason_code is ReasonCode.GRANT_REVOKED

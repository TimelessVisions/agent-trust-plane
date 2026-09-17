"""Exhaustive check of the grant state machine in docs/formal/grant-lifecycle.md.

Every sequence of operations up to length 5 over {consume, revoke, tick}
is run against both store implementations and compared with the abstract
model: ``issued -> consumed`` and ``issued -> revoked`` are the only
transitions, both are absorbing, and a consume succeeds exactly once and
only before expiry."""

from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Iterator
from datetime import timedelta

import pytest

from atp_core import GrantError, ReasonCode
from atp_gateway.grants import (
    GrantStatus,
    GrantStore,
    InMemoryGrantStore,
    SqliteGrantStore,
    new_grant_claims,
)
from gateway_fixtures import NOW

OPS = ("consume", "revoke", "tick")


def _stores() -> Iterator[GrantStore]:
    yield InMemoryGrantStore()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    yield SqliteGrantStore(conn)


def _model(sequence: tuple[str, ...]) -> list[str]:
    """Abstract model: returns the expected result of each op."""
    status = "issued"
    now = 0
    out: list[str] = []
    for op in sequence:
        if op == "tick":
            now += 100  # ttl is 120 s; two ticks expire the grant
            out.append("ok")
        elif op == "revoke":
            status = "revoked" if status == "issued" else status
            out.append(status)
        else:  # consume
            if status == "consumed":
                out.append("GRANT_ALREADY_CONSUMED")
            elif status == "revoked":
                out.append("GRANT_REVOKED")
            elif now >= 120:
                out.append("GRANT_EXPIRED")
            else:
                status = "consumed"
                out.append("consumed")
    return out


@pytest.mark.parametrize("length", [1, 2, 3, 4, 5])
def test_every_sequence_matches_the_model(length: int) -> None:
    for sequence in itertools.product(OPS, repeat=length):
        expected = _model(sequence)
        for store in _stores():
            claims = new_grant_claims(
                trace_id="t" * 12,
                decision_id="dec_x",
                envelope_id="env_x",
                action_hash="a" * 64,
                agent_id="agent",
                policy_set_version="payments-v2",
                ttl_seconds=120,
                now=NOW,
            )
            store.issue(claims)
            now = NOW
            observed: list[str] = []
            for op in sequence:
                if op == "tick":
                    now = now + timedelta(seconds=100)
                    observed.append("ok")
                elif op == "revoke":
                    rec = store.revoke(claims.grant_id)
                    assert rec is not None
                    observed.append(rec.status.value)
                else:
                    record = store.get(claims.grant_id)
                    assert record is not None
                    if claims.is_expired(now) and record.status is GrantStatus.ISSUED:
                        # The service checks expiry before touching the store.
                        observed.append("GRANT_EXPIRED")
                        continue
                    try:
                        rec = store.consume(claims.grant_id, now)
                        observed.append(rec.status.value)
                    except GrantError as exc:
                        observed.append(exc.reason_code.value)
            assert observed == expected, (sequence, type(store).__name__)
            final = store.get(claims.grant_id)
            assert final is not None
            consumed_events = sum(
                1
                for op, res in zip(sequence, observed, strict=True)
                if op == "consume" and res == "consumed"
            )
            assert consumed_events <= 1
            assert (final.status is GrantStatus.CONSUMED) == (consumed_events == 1)


def test_consume_of_unknown_grant_is_not_found() -> None:
    for store in _stores():
        with pytest.raises(GrantError) as exc:
            store.consume("grt_missing", NOW)
        assert exc.value.reason_code is ReasonCode.GRANT_NOT_FOUND

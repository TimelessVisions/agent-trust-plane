from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from decimal import Decimal

import pytest

from atp_audit import (
    GENESIS_HASH,
    EventType,
    InMemoryTraceStore,
    SqliteTraceStore,
    TraceStore,
    verify_events,
)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest) -> Iterator[TraceStore]:
    if request.param == "memory":
        yield InMemoryTraceStore()
    else:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        yield SqliteTraceStore(conn)
        conn.close()


def test_chain_links_and_verifies(store: TraceStore) -> None:
    a = store.append("t1", EventType.TASK_RECEIVED, "agent", {"task": "pay"})
    b = store.append("t1", EventType.ACTION_PROPOSED, "agent", {"amount": Decimal("1.50")})
    assert a.prev_hash == GENESIS_HASH
    assert b.prev_hash == a.hash
    assert b.payload == {"amount": "1.50"}  # Decimals are stored canonically
    report = store.verify("t1")
    assert report.valid and report.event_count == 2 and report.head_hash == b.hash


def test_traces_are_independent_chains(store: TraceStore) -> None:
    store.append("t1", EventType.TASK_RECEIVED, "a", {})
    c = store.append("t2", EventType.TASK_RECEIVED, "a", {})
    assert c.prev_hash == GENESIS_HASH
    assert [e.trace_id for e in store.events("t2")] == ["t2"]


def test_tampering_is_detected() -> None:
    store = InMemoryTraceStore()
    store.append("t1", EventType.TASK_RECEIVED, "a", {"x": 1})
    e2 = store.append("t1", EventType.DECISION_MADE, "gateway", {"outcome": "DENY"})
    store.append("t1", EventType.EXECUTION_BLOCKED, "gateway", {})
    tampered = e2.model_copy(update={"payload": {"outcome": "ALLOW"}})
    events = store.events("t1")
    events[1] = tampered
    report = verify_events("t1", events)
    assert not report.valid
    assert report.first_bad_seq == e2.seq
    assert "does not match" in (report.detail or "")


def test_deleting_a_middle_event_breaks_the_chain() -> None:
    store = InMemoryTraceStore()
    store.append("t1", EventType.TASK_RECEIVED, "a", {})
    store.append("t1", EventType.DECISION_MADE, "gateway", {})
    store.append("t1", EventType.EXECUTION_BLOCKED, "gateway", {})
    events = store.events("t1")
    del events[1]
    report = verify_events("t1", events)
    assert not report.valid
    assert "prev_hash" in (report.detail or "")


def test_list_traces_and_find(store: TraceStore) -> None:
    store.append("t1", EventType.TASK_RECEIVED, "a", {})
    store.append("t2", EventType.TASK_RECEIVED, "a", {})
    store.append("t2", EventType.DECISION_MADE, "gateway", {"outcome": "DENY"})
    summaries = store.list_traces()
    assert [s.trace_id for s in summaries] == ["t2", "t1"]
    assert summaries[0].event_count == 2
    assert summaries[0].last_event_type is EventType.DECISION_MADE
    assert len(store.find("t2", EventType.DECISION_MADE)) == 1


def test_store_has_no_mutation_api(store: TraceStore) -> None:
    for name in ("update", "delete", "remove", "truncate", "clear"):
        assert not hasattr(store, name)


def test_empty_trace_verifies_to_genesis(store: TraceStore) -> None:
    report = store.verify("nothing")
    assert report.valid and report.event_count == 0 and report.head_hash == GENESIS_HASH

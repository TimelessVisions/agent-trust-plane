"""Append-only trace stores.

The interface deliberately has no update or delete. Append-only semantics are
enforced by the application (this module) rather than the database; see
docs/threat-model.md for what stronger tamper-evidence would require.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from atp_audit.events import GENESIS_HASH, EventType, IntegrityReport, TraceEvent
from atp_core import utcnow


class TraceSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    started_at: datetime
    last_event_at: datetime
    event_count: int
    last_event_type: EventType
    head_hash: str


def _to_jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    """Round-trip through JSON so the stored payload is exactly what gets hashed
    and exactly what a reader will see."""
    from atp_core import canonical_json

    result: dict[str, Any] = json.loads(canonical_json(payload))
    return result


class TraceStore(Protocol):
    def append(
        self, trace_id: str, event_type: EventType, actor: str, payload: dict[str, Any]
    ) -> TraceEvent: ...

    def events(self, trace_id: str) -> list[TraceEvent]: ...

    def find(self, trace_id: str, event_type: EventType) -> list[TraceEvent]: ...

    def list_traces(self, limit: int = 50) -> list[TraceSummary]: ...

    def verify(self, trace_id: str) -> IntegrityReport: ...


def verify_events(trace_id: str, events: list[TraceEvent]) -> IntegrityReport:
    prev = GENESIS_HASH
    for ev in events:
        if ev.prev_hash != prev:
            return IntegrityReport(
                trace_id=trace_id,
                valid=False,
                event_count=len(events),
                head_hash=events[-1].hash,
                first_bad_seq=ev.seq,
                detail=f"event {ev.seq} prev_hash does not link to the preceding event",
            )
        if ev.recompute() != ev.hash:
            return IntegrityReport(
                trace_id=trace_id,
                valid=False,
                event_count=len(events),
                head_hash=events[-1].hash,
                first_bad_seq=ev.seq,
                detail=f"event {ev.seq} content does not match its recorded hash",
            )
        prev = ev.hash
    return IntegrityReport(
        trace_id=trace_id,
        valid=True,
        event_count=len(events),
        head_hash=events[-1].hash if events else GENESIS_HASH,
    )


class InMemoryTraceStore:
    def __init__(self) -> None:
        self._events: list[TraceEvent] = []
        self._lock = threading.RLock()

    def append(
        self, trace_id: str, event_type: EventType, actor: str, payload: dict[str, Any]
    ) -> TraceEvent:
        with self._lock:
            prior = [e for e in self._events if e.trace_id == trace_id]
            prev_hash = prior[-1].hash if prior else GENESIS_HASH
            ts = utcnow()
            body = _to_jsonable(payload)
            event = TraceEvent(
                seq=len(self._events) + 1,
                trace_id=trace_id,
                event_type=event_type,
                ts=ts,
                actor=actor,
                payload=body,
                prev_hash=prev_hash,
                hash=TraceEvent.compute_hash(
                    trace_id=trace_id,
                    event_type=event_type,
                    ts=ts,
                    actor=actor,
                    payload=body,
                    prev_hash=prev_hash,
                ),
            )
            self._events.append(event)
            return event

    def events(self, trace_id: str) -> list[TraceEvent]:
        with self._lock:
            return [e for e in self._events if e.trace_id == trace_id]

    def find(self, trace_id: str, event_type: EventType) -> list[TraceEvent]:
        return [e for e in self.events(trace_id) if e.event_type is event_type]

    def list_traces(self, limit: int = 50) -> list[TraceSummary]:
        with self._lock:
            by_trace: dict[str, list[TraceEvent]] = {}
            for e in self._events:
                by_trace.setdefault(e.trace_id, []).append(e)
        summaries = [
            TraceSummary(
                trace_id=tid,
                started_at=evs[0].ts,
                last_event_at=evs[-1].ts,
                event_count=len(evs),
                last_event_type=evs[-1].event_type,
                head_hash=evs[-1].hash,
            )
            for tid, evs in by_trace.items()
        ]
        summaries.sort(key=lambda s: s.started_at, reverse=True)
        return summaries[:limit]

    def verify(self, trace_id: str) -> IntegrityReport:
        return verify_events(trace_id, self.events(trace_id))


class SqliteTraceStore:
    _DDL = """
    CREATE TABLE IF NOT EXISTS trace_events (
        seq        INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id   TEXT NOT NULL,
        event_type TEXT NOT NULL,
        ts         TEXT NOT NULL,
        actor      TEXT NOT NULL,
        payload    TEXT NOT NULL,
        prev_hash  TEXT NOT NULL,
        hash       TEXT NOT NULL UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events (trace_id, seq);
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        with self._lock:
            conn.executescript(self._DDL)
            conn.commit()

    def append(
        self, trace_id: str, event_type: EventType, actor: str, payload: dict[str, Any]
    ) -> TraceEvent:
        with self._lock:
            row = self._conn.execute(
                "SELECT hash FROM trace_events WHERE trace_id = ? ORDER BY seq DESC LIMIT 1",
                (trace_id,),
            ).fetchone()
            prev_hash = row[0] if row else GENESIS_HASH
            ts = utcnow()
            body = _to_jsonable(payload)
            digest = TraceEvent.compute_hash(
                trace_id=trace_id,
                event_type=event_type,
                ts=ts,
                actor=actor,
                payload=body,
                prev_hash=prev_hash,
            )
            cur = self._conn.execute(
                "INSERT INTO trace_events (trace_id, event_type, ts, actor, payload, prev_hash, "
                "hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    trace_id,
                    event_type.value,
                    ts.isoformat(),
                    actor,
                    json.dumps(body, sort_keys=True, separators=(",", ":")),
                    prev_hash,
                    digest,
                ),
            )
            self._conn.commit()
            seq = cur.lastrowid
            assert seq is not None
            return TraceEvent(
                seq=seq,
                trace_id=trace_id,
                event_type=event_type,
                ts=ts,
                actor=actor,
                payload=body,
                prev_hash=prev_hash,
                hash=digest,
            )

    def events(self, trace_id: str) -> list[TraceEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, trace_id, event_type, ts, actor, payload, prev_hash, hash "
                "FROM trace_events WHERE trace_id = ? ORDER BY seq",
                (trace_id,),
            ).fetchall()
        return [_row_to_event(r) for r in rows]

    def find(self, trace_id: str, event_type: EventType) -> list[TraceEvent]:
        return [e for e in self.events(trace_id) if e.event_type is event_type]

    def list_traces(self, limit: int = 50) -> list[TraceSummary]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT t.trace_id, MIN(t.ts), MAX(t.ts), COUNT(*),
                       (SELECT event_type FROM trace_events x WHERE x.trace_id = t.trace_id
                        ORDER BY seq DESC LIMIT 1),
                       (SELECT hash FROM trace_events x WHERE x.trace_id = t.trace_id
                        ORDER BY seq DESC LIMIT 1)
                FROM trace_events t GROUP BY t.trace_id ORDER BY MIN(t.seq) DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            TraceSummary(
                trace_id=r[0],
                started_at=datetime.fromisoformat(r[1]),
                last_event_at=datetime.fromisoformat(r[2]),
                event_count=r[3],
                last_event_type=EventType(r[4]),
                head_hash=r[5],
            )
            for r in rows
        ]

    def verify(self, trace_id: str) -> IntegrityReport:
        return verify_events(trace_id, self.events(trace_id))


def _row_to_event(r: tuple[Any, ...]) -> TraceEvent:
    return TraceEvent(
        seq=r[0],
        trace_id=r[1],
        event_type=EventType(r[2]),
        ts=datetime.fromisoformat(r[3]),
        actor=r[4],
        payload=json.loads(r[5]),
        prev_hash=r[6],
        hash=r[7],
    )

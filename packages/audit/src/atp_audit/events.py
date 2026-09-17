from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atp_core import canonical_hash


class EventType(StrEnum):
    TASK_RECEIVED = "task_received"
    EXTERNAL_CONTENT_INGESTED = "external_content_ingested"
    IDENTITY_REJECTED = "identity_rejected"
    ACTION_PROPOSED = "action_proposed"
    DELEGATION_RESOLVED = "delegation_resolved"
    DELEGATION_RESOLUTION_FAILED = "delegation_resolution_failed"
    POLICY_EVALUATED = "policy_evaluated"
    DECISION_MADE = "decision_made"
    APPROVAL_REQUESTED = "approval_requested"
    GRANT_ISSUED = "grant_issued"
    EXECUTION_ATTEMPTED = "execution_attempted"
    EXECUTION_BLOCKED = "execution_blocked"
    EXECUTION_RELEASED = "execution_released"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    REPLAY_PERFORMED = "replay_performed"


GENESIS_HASH = "0" * 64


class TraceEvent(BaseModel):
    """One append-only record. ``hash`` commits to every field and to the
    previous event's hash, forming a per-trace chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int = Field(description="Global append order; strictly increasing.")
    trace_id: str
    event_type: EventType
    ts: datetime
    actor: str = Field(description="Who produced the event: an agent id or 'gateway'.")
    payload: dict[str, Any]
    prev_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @staticmethod
    def compute_hash(
        *,
        trace_id: str,
        event_type: EventType,
        ts: datetime,
        actor: str,
        payload: dict[str, Any],
        prev_hash: str,
    ) -> str:
        return canonical_hash(
            {
                "trace_id": trace_id,
                "event_type": event_type.value,
                "ts": ts.isoformat(),
                "actor": actor,
                "payload": payload,
                "prev_hash": prev_hash,
            }
        )

    def recompute(self) -> str:
        return self.compute_hash(
            trace_id=self.trace_id,
            event_type=self.event_type,
            ts=self.ts,
            actor=self.actor,
            payload=self.payload,
            prev_hash=self.prev_hash,
        )


class IntegrityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    valid: bool
    event_count: int
    head_hash: str
    first_bad_seq: int | None = None
    detail: str | None = None

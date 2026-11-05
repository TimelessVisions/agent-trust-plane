"""Human approvals for REQUIRE_APPROVAL decisions.

An approval is a signed record bound to one trace and one ``action_hash``:

    {approval_id, trace_id, envelope_id, action_hash, decision_id,
     approver, approver_role, decision, issued_at, expires_at, kid}

signed with the active grant key (Ed25519) over
``b"atp-approval/1\\n" + canonical_json(record)``. The prefix separates the
signature domain from grant tokens, so an approval signature can never be
replayed as a grant signature or the other way round.

Re-authorization: when the same agent re-submits the identical envelope (same
``action_hash``), the gateway finds the approval, checks signature, role and
expiry, and *uses* it with a conditional ``UPDATE ... WHERE status='approved'``
inside the authorize transaction. Exactly one caller wins that update, so one
approval mints at most one grant; every later retry is APPROVAL_ALREADY_USED.
"""

from __future__ import annotations

import base64
import json
import re
import sqlite3
import threading
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from atp_core import PrincipalRef, canonical_json
from atp_core.sqlite import commit_if_implicit

SIGNATURE_DOMAIN = b"atp-approval/1\n"
MAX_APPROVAL_TTL = timedelta(hours=24)
DEFAULT_APPROVAL_TTL = "15m"
_DURATION = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$")
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> timedelta:
    """``"15m"``, ``"900s"``, ``"1h"``, ``"900"`` (seconds). 1 s .. 24 h."""
    m = _DURATION.match(text or "")
    if not m:
        raise ValueError(f"invalid duration {text!r}; use e.g. 15m, 900s, 1h")
    delta = timedelta(seconds=int(m.group(1)) * _UNITS[m.group(2)])
    if delta <= timedelta(0) or delta > MAX_APPROVAL_TTL:
        raise ValueError(f"duration {text!r} must be between 1s and 24h")
    return delta


def parse_approver_roles(text: str) -> dict[str, frozenset[str]]:
    """``"human:alice=finance-manager,approver; human:bob=approver"`` ->
    ``{"human:alice": {...}, "human:bob": {...}}``. A bare id means ``human:<id>``."""
    out: dict[str, frozenset[str]] = {}
    for entry in (text or "").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"approver role entry {entry!r} must look like human:alice=role")
        who, roles = entry.split("=", 1)
        who = who.strip()
        if ":" not in who:
            who = f"human:{who}"
        names = frozenset(r.strip() for r in roles.split(",") if r.strip())
        if not names:
            raise ValueError(f"approver role entry {entry!r} names no role")
        out[who] = out.get(who, frozenset()) | names
    return out


class ApprovalStatus(StrEnum):
    APPROVED = "approved"
    DENIED = "denied"
    USED = "used"


class ApprovalClaims(BaseModel):
    """What the signature covers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str
    trace_id: str
    envelope_id: str
    action_hash: str
    decision_id: str
    approver: PrincipalRef
    approver_role: str
    decision: Literal["approve", "deny"]
    issued_at: datetime
    expires_at: datetime
    kid: str

    def signing_input(self) -> bytes:
        return SIGNATURE_DOMAIN + canonical_json(self.model_dump(mode="json"))

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: ApprovalClaims
    signature: str  # base64url, no padding
    status: ApprovalStatus
    used_at: datetime | None = None


def encode_signature(sig: bytes) -> str:
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")


def decode_signature(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class ApprovalStore(Protocol):
    def put(self, record: ApprovalRecord) -> None: ...

    def for_trace(self, trace_id: str) -> list[ApprovalRecord]: ...

    def use(self, approval_id: str, now: datetime) -> bool:
        """Move ``approved`` -> ``used``. True for exactly one caller."""
        ...


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = threading.Lock()

    def put(self, record: ApprovalRecord) -> None:
        with self._lock:
            if record.claims.approval_id in self._records:
                raise ValueError("approval id already exists")
            self._records[record.claims.approval_id] = record

    def for_trace(self, trace_id: str) -> list[ApprovalRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.claims.trace_id == trace_id]

    def use(self, approval_id: str, now: datetime) -> bool:
        with self._lock:
            record = self._records.get(approval_id)
            if record is None or record.status is not ApprovalStatus.APPROVED:
                return False
            self._records[approval_id] = record.model_copy(
                update={"status": ApprovalStatus.USED, "used_at": now}
            )
            return True


class SqliteApprovalStore:
    _DDL = """
    CREATE TABLE IF NOT EXISTS approvals (
        approval_id TEXT PRIMARY KEY,
        trace_id    TEXT NOT NULL,
        status      TEXT NOT NULL,
        claims      TEXT NOT NULL,
        signature   TEXT NOT NULL,
        used_at     TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_approvals_trace ON approvals (trace_id);
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        with self._lock:
            conn.executescript(self._DDL)
            commit_if_implicit(conn)

    def put(self, record: ApprovalRecord) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO approvals (approval_id, trace_id, status, claims, signature) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.claims.approval_id,
                    record.claims.trace_id,
                    record.status.value,
                    record.claims.model_dump_json(),
                    record.signature,
                ),
            )
            commit_if_implicit(self._conn)

    def for_trace(self, trace_id: str) -> list[ApprovalRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, claims, signature, used_at FROM approvals WHERE trace_id = ? "
                "ORDER BY rowid",
                (trace_id,),
            ).fetchall()
        return [
            ApprovalRecord(
                claims=ApprovalClaims.model_validate(json.loads(r[1])),
                signature=r[2],
                status=ApprovalStatus(r[0]),
                used_at=datetime.fromisoformat(r[3]) if r[3] else None,
            )
            for r in rows
        ]

    def use(self, approval_id: str, now: datetime) -> bool:
        """Single-use by a conditional UPDATE: within one SQLite file only one
        caller (thread or process) moves the row from ``approved`` to ``used``."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE approvals SET status = ?, used_at = ? WHERE approval_id = ? AND status = ?",
                (
                    ApprovalStatus.USED.value,
                    now.isoformat(),
                    approval_id,
                    ApprovalStatus.APPROVED.value,
                ),
            )
            commit_if_implicit(self._conn)
            return cur.rowcount == 1


def roles_for(roles: Mapping[str, frozenset[str]], who: PrincipalRef) -> frozenset[str]:
    return roles.get(str(who), frozenset())

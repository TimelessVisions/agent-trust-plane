"""Execution grants: how an ALLOW decision is bound to a single execution.

Threats this mechanism is designed to stop, and which check stops each:

* call /execute without ever calling /authorize      -> no token: GRANT_MISSING
* invent or edit a token                              -> HMAC: GRANT_SIGNATURE_INVALID
* authorize $480 then execute $12,500 with the token  -> action_hash: GRANT_ENVELOPE_MISMATCH
* hold a token and use it later                       -> expires_at: GRANT_EXPIRED
* use a token twice                                   -> atomic consume: GRANT_ALREADY_CONSUMED
* use a token issued to a different trace/envelope    -> action_hash covers both ids

The token is ``atp-grant/1`` = base64url(canonical claims) "." base64url(HMAC-SHA256).
See ADR-0001 D5 for why HMAC + server-side state rather than either alone.
"""

from __future__ import annotations

import base64
import hmac
import json
import sqlite3
import threading
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from atp_core import GrantError, ReasonCode, canonical_json, new_id, utcnow

TOKEN_VERSION: Final[Literal["atp-grant/1"]] = "atp-grant/1"


class GrantClaims(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    v: Literal["atp-grant/1"] = TOKEN_VERSION
    grant_id: str
    trace_id: str
    decision_id: str
    envelope_id: str
    action_hash: str
    agent_id: str
    policy_set_version: str
    issued_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


class GrantSigner:
    """HMAC-SHA256 over the canonical claims. Symmetric because authorizer and
    executor are the same process in the MVP; the token format is versioned so
    an asymmetric scheme can replace it without changing callers."""

    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("grant signing key must be at least 32 bytes")
        self._key = key

    @property
    def key_fingerprint(self) -> str:
        return sha256(self._key).hexdigest()[:16]

    def mint(self, claims: GrantClaims) -> str:
        body = canonical_json(claims.model_dump(mode="json"))
        sig = hmac.new(self._key, body, sha256).digest()
        return f"{_b64e(body)}.{_b64e(sig)}"

    def verify(self, token: str) -> GrantClaims:
        try:
            body_b64, sig_b64 = token.strip().split(".", 1)
            body = _b64d(body_b64)
            sig = _b64d(sig_b64)
        except (ValueError, TypeError) as exc:
            raise GrantError(ReasonCode.GRANT_MALFORMED, "execution grant is malformed") from exc
        expected = hmac.new(self._key, body, sha256).digest()
        if not hmac.compare_digest(sig, expected):
            raise GrantError(
                ReasonCode.GRANT_SIGNATURE_INVALID,
                "execution grant signature does not verify; the grant was forged or altered",
            )
        try:
            claims = GrantClaims.model_validate(json.loads(body))
        except (ValidationError, ValueError) as exc:
            raise GrantError(
                ReasonCode.GRANT_MALFORMED, "execution grant claims are malformed"
            ) from exc
        # Belt and braces: the signature must have been computed over the canonical form.
        if canonical_json(claims.model_dump(mode="json")) != body:
            raise GrantError(
                ReasonCode.GRANT_SIGNATURE_INVALID, "execution grant body is not canonical"
            )
        return claims


class GrantStatus(StrEnum):
    ISSUED = "issued"
    CONSUMED = "consumed"
    REVOKED = "revoked"


class GrantRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: GrantClaims
    status: GrantStatus
    consumed_at: datetime | None = None


class GrantStore(Protocol):
    def issue(self, claims: GrantClaims) -> GrantRecord: ...

    def get(self, grant_id: str) -> GrantRecord | None: ...

    def consume(self, grant_id: str, now: datetime) -> GrantRecord: ...

    def revoke(self, grant_id: str) -> GrantRecord | None: ...


def _consume_failure(record: GrantRecord | None) -> GrantError:
    if record is None:
        return GrantError(
            ReasonCode.GRANT_NOT_FOUND, "execution grant is not known to this gateway"
        )
    if record.status is GrantStatus.CONSUMED:
        return GrantError(
            ReasonCode.GRANT_ALREADY_CONSUMED,
            f"execution grant was already used at "
            f"{record.consumed_at.isoformat() if record.consumed_at else '?'}",
        )
    return GrantError(ReasonCode.GRANT_REVOKED, "execution grant was revoked")


class InMemoryGrantStore:
    def __init__(self) -> None:
        self._records: dict[str, GrantRecord] = {}
        self._lock = threading.Lock()

    def issue(self, claims: GrantClaims) -> GrantRecord:
        record = GrantRecord(claims=claims, status=GrantStatus.ISSUED)
        with self._lock:
            self._records[claims.grant_id] = record
        return record

    def get(self, grant_id: str) -> GrantRecord | None:
        with self._lock:
            return self._records.get(grant_id)

    def consume(self, grant_id: str, now: datetime) -> GrantRecord:
        with self._lock:
            record = self._records.get(grant_id)
            if record is None or record.status is not GrantStatus.ISSUED:
                raise _consume_failure(record)
            consumed = record.model_copy(
                update={"status": GrantStatus.CONSUMED, "consumed_at": now}
            )
            self._records[grant_id] = consumed
            return consumed

    def revoke(self, grant_id: str) -> GrantRecord | None:
        with self._lock:
            record = self._records.get(grant_id)
            if record is None:
                return None
            if record.status is not GrantStatus.ISSUED:
                # consumed and revoked are absorbing: a side effect that
                # happened must stay recorded as consumed.
                return record
            revoked = record.model_copy(update={"status": GrantStatus.REVOKED})
            self._records[grant_id] = revoked
            return revoked


class SqliteGrantStore:
    _DDL = """
    CREATE TABLE IF NOT EXISTS execution_grants (
        grant_id    TEXT PRIMARY KEY,
        status      TEXT NOT NULL,
        claims      TEXT NOT NULL,
        consumed_at TEXT
    );
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        with self._lock:
            conn.executescript(self._DDL)
            conn.commit()

    def issue(self, claims: GrantClaims) -> GrantRecord:
        with self._lock:
            self._conn.execute(
                "INSERT INTO execution_grants (grant_id, status, claims) VALUES (?, ?, ?)",
                (claims.grant_id, GrantStatus.ISSUED.value, claims.model_dump_json()),
            )
            self._conn.commit()
        return GrantRecord(claims=claims, status=GrantStatus.ISSUED)

    def get(self, grant_id: str) -> GrantRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status, claims, consumed_at FROM execution_grants WHERE grant_id = ?",
                (grant_id,),
            ).fetchone()
        if row is None:
            return None
        return GrantRecord(
            claims=GrantClaims.model_validate_json(row[1]),
            status=GrantStatus(row[0]),
            consumed_at=datetime.fromisoformat(row[2]) if row[2] else None,
        )

    def consume(self, grant_id: str, now: datetime) -> GrantRecord:
        """Single-use is enforced by the conditional UPDATE: only one caller can
        move the row from ``issued`` to ``consumed``."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE execution_grants SET status = ?, consumed_at = ? "
                "WHERE grant_id = ? AND status = ?",
                (GrantStatus.CONSUMED.value, now.isoformat(), grant_id, GrantStatus.ISSUED.value),
            )
            self._conn.commit()
            if cur.rowcount != 1:
                raise _consume_failure(self.get(grant_id))
            record = self.get(grant_id)
            assert record is not None
            return record

    def revoke(self, grant_id: str) -> GrantRecord | None:
        with self._lock:
            self._conn.execute(
                "UPDATE execution_grants SET status = ? WHERE grant_id = ? AND status = ?",
                (GrantStatus.REVOKED.value, grant_id, GrantStatus.ISSUED.value),
            )
            self._conn.commit()
            return self.get(grant_id)


def new_grant_claims(
    *,
    trace_id: str,
    decision_id: str,
    envelope_id: str,
    action_hash: str,
    agent_id: str,
    policy_set_version: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> GrantClaims:
    issued = now or utcnow()
    from datetime import timedelta

    return GrantClaims(
        grant_id=new_id("xg"),
        trace_id=trace_id,
        decision_id=decision_id,
        envelope_id=envelope_id,
        action_hash=action_hash,
        agent_id=agent_id,
        policy_set_version=policy_set_version,
        issued_at=issued,
        expires_at=issued + timedelta(seconds=ttl_seconds),
    )

"""Execution grants: how an ALLOW decision is bound to a single execution.

Threats this mechanism is designed to stop, and which check stops each:

* call /execute without ever calling /authorize      -> no token: GRANT_MISSING
* invent or edit a token                              -> Ed25519: GRANT_SIGNATURE_INVALID
* sign with a key the gateway does not hold           -> unknown kid: GRANT_SIGNATURE_INVALID
* authorize $480 then execute $12,500 with the token  -> action_hash: GRANT_ENVELOPE_MISMATCH
* hold a token and use it later                       -> expires_at: GRANT_EXPIRED
* use a token twice                                   -> atomic consume: GRANT_ALREADY_CONSUMED
* use a token issued to a different trace/envelope    -> action_hash covers both ids

The token is ``atp-grant/2``::

    base64url(header) "." base64url(canonical claims) "." base64url(Ed25519 signature)

with ``header = {"alg": "EdDSA", "kid": <kid>, "v": "atp-grant/2"}``. The
signature covers ``base64url(header) "." base64url(claims)``. ``kid`` is the
first 16 hex characters of SHA-256 over the raw 32-byte public key, so a
verifier can hold several public keys (key rotation) and pick one without
trying them all. ``atp-grant/1`` (HMAC-SHA256) tokens are rejected as
GRANT_MALFORMED: grants are single-use and short-lived, so no compatibility
window is needed. See ADR-0001 D5 for why a signature plus server-side state
rather than either alone.
"""

from __future__ import annotations

import base64
import binascii
import json
import sqlite3
import threading
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final, Literal, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import BaseModel, ConfigDict, ValidationError

from atp_core import GrantError, ReasonCode, canonical_json, new_id, utcnow
from atp_core.sqlite import commit_if_implicit

TOKEN_VERSION: Final[Literal["atp-grant/2"]] = "atp-grant/2"
LEGACY_TOKEN_VERSION: Final = "atp-grant/1"
ALG: Final = "EdDSA"


class GrantClaims(BaseModel):
    """What a grant binds. The token version lives in the token header, not here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

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
    """Strict base64url without padding: a segment must be exactly what
    ``_b64e`` would produce, so no two strings decode to the same token."""
    pad = "=" * (-len(text) % 4)
    data = base64.urlsafe_b64decode(text + pad)
    if _b64e(data) != text:
        raise ValueError("non-canonical base64url")
    return data


def kid_for(public_key: Ed25519PublicKey) -> str:
    """``sha256(raw public key).hexdigest()[:16]``."""
    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return sha256(raw).hexdigest()[:16]


def _malformed(message: str = "execution grant is malformed") -> GrantError:
    return GrantError(ReasonCode.GRANT_MALFORMED, message)


def _invalid(message: str) -> GrantError:
    return GrantError(ReasonCode.GRANT_SIGNATURE_INVALID, message)


class GrantSigner:
    """Mints ``atp-grant/2`` tokens with one Ed25519 private key."""

    def __init__(self, private_key: Ed25519PrivateKey, kid: str) -> None:
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("grant signing key must be an Ed25519 private key")
        actual = kid_for(private_key.public_key())
        if kid != actual:
            raise ValueError(f"grant signing key does not match kid {kid!r} (it is {actual!r})")
        self._key = private_key
        self._kid = kid

    @property
    def kid(self) -> str:
        return self._kid

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._key.public_key()

    def mint(self, claims: GrantClaims) -> str:
        header = _b64e(canonical_json({"alg": ALG, "kid": self._kid, "v": TOKEN_VERSION}))
        body = _b64e(canonical_json(claims.model_dump(mode="json")))
        signing_input = f"{header}.{body}".encode("ascii")
        return f"{header}.{body}.{_b64e(self._key.sign(signing_input))}"


class GrantVerifier:
    """Verifies ``atp-grant/2`` tokens against a set of public keys by ``kid``.

    ``not_after`` maps a retired kid to the moment it stops verifying (its
    retirement plus one grant TTL); ``clock`` reads the current time.
    """

    def __init__(
        self,
        public_keys: Mapping[str, Ed25519PublicKey],
        *,
        not_after: Mapping[str, datetime] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._keys = dict(public_keys)
        self._not_after = dict(not_after or {})
        self._clock = clock

    @property
    def kids(self) -> frozenset[str]:
        return frozenset(self._keys)

    def verify(self, token: str, *, now: datetime | None = None) -> GrantClaims:
        """``now`` (default: the clock) decides whether a retired kid still verifies;
        expiry of the grant itself is the caller's check."""
        parts = token.strip().split(".")
        if len(parts) == 2:
            raise _malformed(
                f"execution grant uses the retired {LEGACY_TOKEN_VERSION} (HMAC) format; "
                f"this gateway accepts only {TOKEN_VERSION}"
            )
        if len(parts) != 3:
            raise _malformed()
        header_b64, body_b64, sig_b64 = parts
        try:
            header: Any = json.loads(_b64d(header_b64))
            body = _b64d(body_b64)
            sig = _b64d(sig_b64)
        except (ValueError, TypeError, binascii.Error) as exc:
            raise _malformed() from exc
        if (
            not isinstance(header, dict)
            or set(header) != {"alg", "kid", "v"}
            or header["alg"] != ALG
            or header["v"] != TOKEN_VERSION
            or not isinstance(header["kid"], str)
        ):
            raise _malformed(f"execution grant header is not an {TOKEN_VERSION} EdDSA header")
        kid: str = header["kid"]
        key = self._keys.get(kid)
        if key is None:
            raise _invalid(f"execution grant kid {kid!r} is not a key this gateway trusts")
        deadline = self._not_after.get(kid)
        if deadline is not None and (now or self._clock()) >= deadline:
            raise _invalid(f"execution grant kid {kid!r} was retired")
        try:
            key.verify(sig, f"{header_b64}.{body_b64}".encode("ascii"))
        except InvalidSignature as exc:
            raise _invalid(
                "execution grant signature does not verify; the grant was forged or altered"
            ) from exc
        try:
            claims = GrantClaims.model_validate(json.loads(body))
        except (ValidationError, ValueError) as exc:
            raise _malformed("execution grant claims are malformed") from exc
        # Belt and braces: the signature must have been computed over the canonical form.
        if canonical_json(claims.model_dump(mode="json")) != body:
            raise _invalid("execution grant body is not canonical")
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
            commit_if_implicit(conn)

    def issue(self, claims: GrantClaims) -> GrantRecord:
        with self._lock:
            self._conn.execute(
                "INSERT INTO execution_grants (grant_id, status, claims) VALUES (?, ?, ?)",
                (claims.grant_id, GrantStatus.ISSUED.value, claims.model_dump_json()),
            )
            commit_if_implicit(self._conn)
        return GrantRecord(claims=claims, status=GrantStatus.ISSUED)

    def get(self, grant_id: str) -> GrantRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status, claims, consumed_at FROM execution_grants WHERE grant_id = ?",
                (grant_id,),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row[1])
        # Rows written by 0.3.x carry ``v: atp-grant/1`` inside the claims; the
        # version now lives in the token header, and the row itself is unchanged.
        data.pop("v", None)
        return GrantRecord(
            claims=GrantClaims.model_validate(data),
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
            commit_if_implicit(self._conn)
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
            commit_if_implicit(self._conn)
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

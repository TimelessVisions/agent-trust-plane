"""Server-managed agent credentials.

An agent authenticates with a bearer token of the form
``atpa_<credential_id>.<secret>``. The gateway stores only the SHA-256 of
the secret, looks the credential up by id, and compares hashes in constant
time. Tokens are returned exactly once, at issuance, and never appear in
traces, logs, or read endpoints.

This is deliberately the smallest thing that makes ``envelope.agent`` a
verified claim instead of an asserted one. It is not an identity platform:
there is no federation, no key rotation protocol, no mutual TLS. See
docs/security/threat-model.md for what that leaves open.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from atp_core import ATPError, PrincipalKind, PrincipalRef, ReasonCode, ensure_aware, new_id, utcnow

TOKEN_PREFIX = "atpa_"


class AuthError(ATPError):
    """Raised when a caller cannot be authenticated or is not who they claim."""


class AgentCredential(BaseModel):
    """What the gateway stores. Never contains the secret."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_id: str
    agent: PrincipalRef
    label: str = Field(max_length=200)
    secret_hash: str = Field(pattern=r"^[0-9a-f]{64}$", exclude=True, repr=False)
    issued_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at


class AuthenticatedAgent(BaseModel):
    """The result of successful authentication. Safe to log and to trace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: PrincipalRef
    credential_id: str


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class CredentialStore(Protocol):
    def put(self, credential: AgentCredential) -> None: ...

    def get(self, credential_id: str) -> AgentCredential | None: ...

    def revoke(self, credential_id: str, at: datetime) -> AgentCredential | None: ...

    def for_agent(self, agent_id: str) -> list[AgentCredential]: ...


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._rows: dict[str, AgentCredential] = {}
        self._lock = threading.Lock()

    def put(self, credential: AgentCredential) -> None:
        with self._lock:
            self._rows[credential.credential_id] = credential

    def get(self, credential_id: str) -> AgentCredential | None:
        with self._lock:
            return self._rows.get(credential_id)

    def revoke(self, credential_id: str, at: datetime) -> AgentCredential | None:
        with self._lock:
            cred = self._rows.get(credential_id)
            if cred is None:
                return None
            if cred.revoked_at is None:
                cred = cred.model_copy(update={"revoked_at": at})
                self._rows[credential_id] = cred
            return cred

    def for_agent(self, agent_id: str) -> list[AgentCredential]:
        with self._lock:
            return [c for c in self._rows.values() if c.agent.id == agent_id]


class SqliteCredentialStore:
    _DDL = """
    CREATE TABLE IF NOT EXISTS agent_credentials (
        credential_id TEXT PRIMARY KEY,
        agent_id      TEXT NOT NULL,
        agent_kind    TEXT NOT NULL,
        label         TEXT NOT NULL,
        secret_hash   TEXT NOT NULL,
        issued_at     TEXT NOT NULL,
        expires_at    TEXT,
        revoked_at    TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_agent_credentials_agent ON agent_credentials (agent_id);
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        with self._lock:
            conn.executescript(self._DDL)
            conn.commit()

    def put(self, credential: AgentCredential) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_credentials (credential_id, agent_id, agent_kind, label, "
                "secret_hash, issued_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    credential.credential_id,
                    credential.agent.id,
                    credential.agent.kind.value,
                    credential.label,
                    credential.secret_hash,
                    credential.issued_at.isoformat(),
                    credential.expires_at.isoformat() if credential.expires_at else None,
                    credential.revoked_at.isoformat() if credential.revoked_at else None,
                ),
            )
            self._conn.commit()

    def get(self, credential_id: str) -> AgentCredential | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT credential_id, agent_id, agent_kind, label, secret_hash, issued_at, "
                "expires_at, revoked_at FROM agent_credentials WHERE credential_id = ?",
                (credential_id,),
            ).fetchone()
        return _row(row) if row else None

    def revoke(self, credential_id: str, at: datetime) -> AgentCredential | None:
        with self._lock:
            self._conn.execute(
                "UPDATE agent_credentials SET revoked_at = ? WHERE credential_id = ? "
                "AND revoked_at IS NULL",
                (at.isoformat(), credential_id),
            )
            self._conn.commit()
            return self.get(credential_id)

    def for_agent(self, agent_id: str) -> list[AgentCredential]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT credential_id, agent_id, agent_kind, label, secret_hash, issued_at, "
                "expires_at, revoked_at FROM agent_credentials WHERE agent_id = ? ORDER BY rowid",
                (agent_id,),
            ).fetchall()
        return [_row(r) for r in rows]


def _row(r: tuple[str, str, str, str, str, str, str | None, str | None]) -> AgentCredential:
    return AgentCredential(
        credential_id=r[0],
        agent=PrincipalRef(id=r[1], kind=PrincipalKind(r[2])),
        label=r[3],
        secret_hash=r[4],
        issued_at=datetime.fromisoformat(r[5]),
        expires_at=datetime.fromisoformat(r[6]) if r[6] else None,
        revoked_at=datetime.fromisoformat(r[7]) if r[7] else None,
    )


class CredentialService:
    def __init__(self, store: CredentialStore) -> None:
        self._store = store

    @property
    def store(self) -> CredentialStore:
        return self._store

    def issue(
        self,
        agent: PrincipalRef,
        *,
        label: str,
        expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> tuple[AgentCredential, str]:
        """Create a credential. Returns the record and the bearer token; the
        token is not recoverable afterwards."""
        if agent.kind is PrincipalKind.HUMAN:
            raise ATPError(
                ReasonCode.CREDENTIAL_SUBJECT_INVALID,
                "humans do not hold agent credentials; human authority is exercised by operators",
            )
        now = now or utcnow()
        credential_id = new_id("cred")
        secret = secrets.token_urlsafe(32)
        credential = AgentCredential(
            credential_id=credential_id,
            agent=agent,
            label=label,
            secret_hash=_hash_secret(secret),
            issued_at=now,
            expires_at=ensure_aware(expires_at) if expires_at else None,
        )
        self._store.put(credential)
        return credential, f"{TOKEN_PREFIX}{credential_id}.{secret}"

    def authenticate(self, token: str | None, *, now: datetime | None = None) -> AuthenticatedAgent:
        if not token:
            raise AuthError(ReasonCode.AGENT_CREDENTIAL_MISSING, "agent credential required")
        if not token.startswith(TOKEN_PREFIX) or "." not in token:
            raise AuthError(ReasonCode.AGENT_CREDENTIAL_INVALID, "agent credential is malformed")
        credential_id, _, secret = token[len(TOKEN_PREFIX) :].partition(".")
        credential = self._store.get(credential_id)
        # Compare against a dummy hash when the id is unknown so timing does not
        # distinguish "no such credential" from "wrong secret".
        expected = credential.secret_hash if credential else "0" * 64
        if not hmac.compare_digest(_hash_secret(secret), expected) or credential is None:
            raise AuthError(ReasonCode.AGENT_CREDENTIAL_INVALID, "agent credential is not valid")
        now = now or utcnow()
        if credential.is_revoked():
            raise AuthError(ReasonCode.AGENT_CREDENTIAL_REVOKED, "agent credential was revoked")
        if credential.is_expired(now):
            raise AuthError(ReasonCode.AGENT_CREDENTIAL_EXPIRED, "agent credential has expired")
        return AuthenticatedAgent(agent=credential.agent, credential_id=credential.credential_id)

    def revoke(self, credential_id: str, *, now: datetime | None = None) -> AgentCredential:
        credential = self._store.revoke(credential_id, now or utcnow())
        if credential is None:
            raise AuthError(
                ReasonCode.AGENT_CREDENTIAL_INVALID, f"credential {credential_id} not found"
            )
        return credential

    def list_for_agent(self, agent_id: str) -> list[AgentCredential]:
        return self._store.for_agent(agent_id)

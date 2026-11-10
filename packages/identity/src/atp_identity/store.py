"""Grant persistence.

Two implementations share one interface: an in-memory store for tests and a
SQLite store for the gateway. Neither exposes an update path other than
``revoke``; grants are otherwise immutable once issued.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from atp_core import utcnow
from atp_core.sqlite import commit_if_implicit
from atp_identity.grants import DelegationGrant


class DelegationStore(Protocol):
    def put(self, grant: DelegationGrant) -> None: ...

    def get(self, grant_id: str) -> DelegationGrant | None: ...

    def revoke(self, grant_id: str, at: datetime | None = None) -> DelegationGrant | None: ...

    def all(self) -> Iterable[DelegationGrant]: ...

    def sign_unsigned_root(self, grant_id: str, signature: str, signer_kid: str) -> bool:
        """Migration only: attach a signature to a root stored without one
        (0.3.x). Never replaces an existing signature. True when it changed."""
        ...


class InMemoryDelegationStore:
    def __init__(self) -> None:
        self._grants: dict[str, DelegationGrant] = {}

    def put(self, grant: DelegationGrant) -> None:
        if grant.grant_id in self._grants:
            raise ValueError(f"grant already exists: {grant.grant_id}")
        self._grants[grant.grant_id] = grant

    def get(self, grant_id: str) -> DelegationGrant | None:
        return self._grants.get(grant_id)

    def revoke(self, grant_id: str, at: datetime | None = None) -> DelegationGrant | None:
        grant = self._grants.get(grant_id)
        if grant is None:
            return None
        revoked = grant.model_copy(update={"revoked_at": at or utcnow()})
        self._grants[grant_id] = revoked
        return revoked

    def all(self) -> Iterable[DelegationGrant]:
        return list(self._grants.values())

    def sign_unsigned_root(self, grant_id: str, signature: str, signer_kid: str) -> bool:
        grant = self._grants.get(grant_id)
        if grant is None or not grant.is_root or grant.signature is not None:
            return False
        self._grants[grant_id] = grant.model_copy(
            update={"signature": signature, "signer_kid": signer_kid}
        )
        return True


class SqliteDelegationStore:
    _DDL = """
    CREATE TABLE IF NOT EXISTS delegation_grants (
        grant_id   TEXT PRIMARY KEY,
        grantee_id TEXT NOT NULL,
        parent_id  TEXT,
        body       TEXT NOT NULL,
        revoked_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_grants_grantee ON delegation_grants (grantee_id);
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        with self._lock:
            conn.executescript(self._DDL)
            commit_if_implicit(conn)

    def put(self, grant: DelegationGrant) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO delegation_grants (grant_id, grantee_id, parent_id, body, "
                    "revoked_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        grant.grant_id,
                        grant.grantee.id,
                        grant.parent_grant_id,
                        grant.model_dump_json(),
                        grant.revoked_at.isoformat() if grant.revoked_at else None,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"grant already exists: {grant.grant_id}") from exc
            commit_if_implicit(self._conn)

    def get(self, grant_id: str) -> DelegationGrant | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body, revoked_at FROM delegation_grants WHERE grant_id = ?", (grant_id,)
            ).fetchone()
        if row is None:
            return None
        grant = DelegationGrant.model_validate_json(row[0])
        if row[1] and grant.revoked_at is None:
            grant = grant.model_copy(update={"revoked_at": datetime.fromisoformat(row[1])})
        return grant

    def revoke(self, grant_id: str, at: datetime | None = None) -> DelegationGrant | None:
        when = at or utcnow()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE delegation_grants SET revoked_at = ? WHERE grant_id = ? "
                "AND revoked_at IS NULL",
                (when.isoformat(), grant_id),
            )
            commit_if_implicit(self._conn)
            if cur.rowcount == 0:
                return self.get(grant_id)
        return self.get(grant_id)

    def sign_unsigned_root(self, grant_id: str, signature: str, signer_kid: str) -> bool:
        with self._lock:
            grant = self.get(grant_id)
            if grant is None or not grant.is_root or grant.signature is not None:
                return False
            # The body keeps its own revoked_at (the column is authoritative on read).
            row = self._conn.execute(
                "SELECT body FROM delegation_grants WHERE grant_id = ?", (grant_id,)
            ).fetchone()
            stored = DelegationGrant.model_validate_json(row[0])
            signed = stored.model_copy(update={"signature": signature, "signer_kid": signer_kid})
            self._conn.execute(
                "UPDATE delegation_grants SET body = ? WHERE grant_id = ?",
                (signed.model_dump_json(), grant_id),
            )
            commit_if_implicit(self._conn)
            return True

    def all(self) -> Iterable[DelegationGrant]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT grant_id FROM delegation_grants ORDER BY rowid"
            ).fetchall()
        out: list[DelegationGrant] = []
        for (gid,) in rows:
            grant = self.get(gid)
            if grant is not None:
                out.append(grant)
        return out

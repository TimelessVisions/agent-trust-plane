"""Shared SQLite helpers for the stores.

All stores in a persistent gateway share one connection opened in autocommit
mode (``isolation_level=None``). The gateway wraps each kernel operation
(authorize, execute, outcome, provenance, replay) in one explicit
``BEGIN IMMEDIATE … COMMIT`` so its trace events and grant-state change are
durable together (one fsync) or not at all. Stores therefore commit only when
the connection runs in the default implicit-transaction mode (tests that
open their own connection); inside an explicit transaction a store-level
commit would end the unit of work early.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any


def commit_if_implicit(conn: sqlite3.Connection) -> None:
    if conn.isolation_level is not None:
        conn.commit()


class SqliteUnitOfWork:
    """Re-entrant explicit transaction on an autocommit connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        if conn.isolation_level is not None:
            raise ValueError("SqliteUnitOfWork needs a connection opened with isolation_level=None")
        self._conn = conn
        self._depth = 0
        self._lock = threading.RLock()

    @contextmanager
    def __call__(self) -> Iterator[None]:
        with self._lock:
            if self._depth == 0:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self._conn.execute("COMMIT")


def no_transaction() -> Any:
    return nullcontext()

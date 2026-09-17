"""Storage for evaluation reports so the dashboard can show the latest run.

The report shape is owned by ``atp_evals``; the gateway stores it opaquely.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Protocol

from atp_core import utcnow
from atp_core.sqlite import commit_if_implicit


class EvalReportStore(Protocol):
    def save(self, report: dict[str, Any]) -> None: ...

    def latest(self) -> dict[str, Any] | None: ...


class InMemoryEvalReportStore:
    def __init__(self) -> None:
        self._latest: dict[str, Any] | None = None

    def save(self, report: dict[str, Any]) -> None:
        self._latest = report

    def latest(self) -> dict[str, Any] | None:
        return self._latest


class SqliteEvalReportStore:
    _DDL = """
    CREATE TABLE IF NOT EXISTS eval_reports (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        saved_at TEXT NOT NULL,
        body    TEXT NOT NULL
    );
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        with self._lock:
            conn.executescript(self._DDL)
            commit_if_implicit(conn)

    def save(self, report: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO eval_reports (saved_at, body) VALUES (?, ?)",
                (utcnow().isoformat(), json.dumps(report)),
            )
            commit_if_implicit(self._conn)

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body FROM eval_reports ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        body: dict[str, Any] = json.loads(row[0])
        return body

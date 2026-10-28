"""Opt-in, outbound-only watcher for new ATP denial traces.

A separate process polls the existing append-only trace store. It does not
participate in authorize/execute and never changes the decision or grants.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Any

from atp_cli.photon import PHONE_RE, PhotonAlertError, PhotonClient, denial_alert


class AlertJournal:
    """Durable at-most-one-attempt journal per ATP home/project/recipient.

    Claiming occurs before network I/O. A crash or ambiguous response leaves
    the attempt recorded as unknown. Operators must reconcile manually rather
    than risk a duplicate or unexpectedly delivered alert.
    """

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(path, timeout=10)
        self._conn.execute("PRAGMA busy_timeout = 10000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS photon_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS photon_attempts ("
            "trace_id TEXT PRIMARY KEY, status TEXT NOT NULL, message_id TEXT)"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def initialize(self, traces: list[str], project_id: str, recipient: str) -> bool:
        """Skip history on first start; refuse reuse with different recipients."""
        target = hashlib.sha256(f"{project_id}\0{recipient}".encode()).hexdigest()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            prior = self._conn.execute(
                "SELECT value FROM photon_meta WHERE key = 'target'"
            ).fetchone()
            if prior is not None and prior[0] != target:
                raise PhotonAlertError(
                    "Photon watcher is already bound to another project/recipient; "
                    "use a separate ATP home"
                )
            if prior is None:
                self._conn.execute(
                    "INSERT INTO photon_meta (key, value) VALUES ('target', ?)", (target,)
                )
                self._conn.executemany(
                    "INSERT OR IGNORE INTO photon_attempts "
                    "(trace_id, status) VALUES (?, 'baseline')",
                    [(trace_id,) for trace_id in traces],
                )
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        return prior is None

    def claim(self, trace_id: str) -> bool:
        """Atomic claim for a single trace, even with two active watchers."""
        with self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO photon_attempts (trace_id, status) "
                "VALUES (?, 'unknown')",
                (trace_id,),
            )
        return cur.rowcount == 1

    def mark_accepted(self, trace_id: str, message_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE photon_attempts SET status = 'accepted', message_id = ? "
                "WHERE trace_id = ? AND status = 'unknown'",
                (message_id, trace_id),
            )

    def status(self, trace_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM photon_attempts WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        return row[0] if row else None


def process_new_denials(
    trust_plane: Any, journal: AlertJournal, client: PhotonClient, recipient: str
) -> tuple[int, int]:
    """Poll recent traces; return (API accepted, unknown/unconfirmed attempts)."""
    accepted = unknown = 0
    # A bounded scan is sufficient for a small one-line demo, not high volume.
    for summary in reversed(trust_plane.list_traces(limit=500)):
        if journal.status(summary.trace_id) is not None:
            continue
        view = trust_plane.get_trace(summary.trace_id)
        try:
            alert = denial_alert(view)
        except PhotonAlertError:
            # Non-denials or incomplete traces aren't eligible. Re-check on
            # the next poll, e.g. when an action proposal gains a decision.
            continue
        if not journal.claim(view.trace_id):
            continue
        try:
            message_id = client.send_denial(recipient, view.trace_id, alert)
        except PhotonAlertError:
            # Keep the claim as UNKNOWN; never auto-retry an uncertain send.
            unknown += 1
        else:
            journal.mark_accepted(view.trace_id, message_id)
            accepted += 1
    return accepted, unknown


def watch(
    *,
    trust_plane: Any,
    home: Path,
    client: PhotonClient,
    recipient: str,
    poll_seconds: float,
    once: bool = False,
) -> None:
    """Start from *now*, not from historic denials. Ctrl+C stops the process."""
    if not PHONE_RE.fullmatch(recipient):
        raise PhotonAlertError("recipient must be a valid E.164 phone number")
    if not 1.0 <= poll_seconds <= 60.0:
        raise PhotonAlertError("poll interval must be between 1 and 60 seconds")
    home.mkdir(parents=True, exist_ok=True)
    journal = AlertJournal(home / "photon-alerts.db")
    try:
        initial = [s.trace_id for s in trust_plane.list_traces(limit=500)]
        fresh = journal.initialize(initial, client.credentials.project_id, recipient)
        if fresh:
            print("Photon watcher initialized; existing trace history will not be sent.")
        print("Watching new ATP denials; replies cannot authorize actions. Press Ctrl+C to stop.")
        while True:
            accepted, unknown = process_new_denials(trust_plane, journal, client, recipient)
            if accepted or unknown:
                print(
                    f"Photon requests accepted: {accepted}; uncertain: {unknown}. "
                    "Inspect Photon dashboard/device to confirm delivery."
                )
            if once:
                return
            time.sleep(poll_seconds)
    finally:
        journal.close()

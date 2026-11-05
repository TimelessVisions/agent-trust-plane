"""Cumulative budgets: reservations against spend per UTC calendar period.

Lifecycle of a reservation (its id is the execution grant id):

* ``reserve`` at mint. Atomic: the sum check and the insert run in one
  ``BEGIN IMMEDIATE`` transaction (SQLite) or under one lock (in memory), so
  two concurrent reservations can never together exceed a budget.
* ``settle`` on a successful outcome: the reservation becomes spend, counted
  at ``actual`` (default: the reserved amount).
* ``release`` on a failed outcome: it stops counting.
* ``hold`` once the grant is consumed (the gateway hands the action to a tool
  or an external executor): the reservation is exempt from expiry and counts
  until ``settle`` or ``release``. Money released to an external executor
  can move after the grant expires, so only the outcome report ends it.
* Expiry: a reservation whose grant was never consumed is released lazily
  when the grant expires, on the next ``reserve`` (and whenever the gateway
  lists traces).
* ``settle`` also applies to a RELEASED reservation: the outcome is recorded
  as spent, because the money really moved, even when that takes the period
  past its limit. A RELEASED row can only come from a grant never used or an
  explicit failure, so this is a reconciliation path, not a way round a limit.

An operator reconciles a held reservation whose executor never reports by
calling ``settle`` or ``release`` on the store with the grant id.

Spend is bucketed by ``(budget key, period, period start, currency)``. The
key is ``"<root principal>><grantee>"`` of the grant that declares the
budget, so it survives new sessions and sibling grants to the same grantee.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from atp_core import BudgetPeriod, ChainBudget, Money, PrincipalRef

RESERVED = "reserved"
SETTLED = "settled"
RELEASED = "released"
HELD = "held"
_ZERO = Decimal("0.00")


class BudgetLine(BaseModel):
    """One budget to check, placed in the period that contains ``now``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    grant_id: str
    period: BudgetPeriod
    period_start: datetime
    limit: Money

    @property
    def bucket(self) -> tuple[str, str, str, str]:
        return (self.key, self.period, _ts(self.period_start), self.limit.currency)


class BudgetUsage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    line: BudgetLine
    spent: Decimal
    reserved: Decimal
    requested: Money

    @property
    def remaining(self) -> Decimal:
        return self.line.limit.amount - self.spent - self.reserved

    @property
    def exceeded(self) -> bool:
        return self.requested.amount > self.remaining


class ReservationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    usages: tuple[BudgetUsage, ...]

    @property
    def binding(self) -> BudgetUsage | None:
        """The budget that decides: the one with the least room left after
        this request (an exceeded one when the result is not ok)."""
        if not self.usages:
            return None
        return min(self.usages, key=lambda u: u.remaining - u.requested.amount)


def budget_key(root: PrincipalRef, grantee: PrincipalRef) -> str:
    return f"{root}>{grantee}"


def budget_lines(
    budgets: Iterable[ChainBudget], root: PrincipalRef, now: datetime
) -> list[BudgetLine]:
    """One line per (key, period, currency); where a chain repeats one, the
    tightest limit is kept."""
    lines: dict[tuple[str, str, str], BudgetLine] = {}
    for cb in budgets:
        line = BudgetLine(
            key=budget_key(root, cb.grantee),
            grant_id=cb.grant_id,
            period=cb.budget.period,
            period_start=cb.budget.period_start(now),
            limit=cb.budget.amount,
        )
        k = (line.key, line.period, line.limit.currency)
        if k not in lines or line.limit.amount < lines[k].limit.amount:
            lines[k] = line
    return list(lines.values())


def _ts(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="microseconds")


class ReservationStore(Protocol):
    def usage(
        self, lines: Sequence[BudgetLine], amount: Money, now: datetime, *, release: bool = True
    ) -> ReservationResult:
        """What reserving ``amount`` would see, without reserving."""
        ...

    def reserve(
        self,
        reservation_id: str,
        lines: Sequence[BudgetLine],
        amount: Money,
        *,
        expires_at: datetime,
        now: datetime,
    ) -> ReservationResult:
        """Atomically: release expired reservations, then reserve ``amount``
        against every line, or against none if any line would be exceeded."""
        ...

    def hold(self, reservation_id: str) -> None:
        """Exempt a (consumed) reservation from expiry until settled or released."""
        ...

    def settle(self, reservation_id: str, actual: Money | None = None) -> None: ...

    def release(self, reservation_id: str) -> None: ...

    def release_expired(self, now: datetime) -> int: ...


def _result(
    lines: Sequence[BudgetLine], amount: Money, sums: list[tuple[Decimal, Decimal]]
) -> ReservationResult:
    usages = tuple(
        BudgetUsage(line=line, spent=s, reserved=r, requested=amount)
        for line, (s, r) in zip(lines, sums, strict=True)
    )
    return ReservationResult(ok=not any(u.exceeded for u in usages), usages=usages)


def _check_currency(lines: Sequence[BudgetLine], amount: Money) -> None:
    for line in lines:
        if line.limit.currency != amount.currency:
            raise ValueError(f"budget is in {line.limit.currency}; amount is in {amount.currency}")


@dataclass
class _Row:
    reservation_id: str
    bucket: tuple[str, str, str, str]
    amount: Decimal
    expires_at: datetime
    status: str = RESERVED
    actual: Decimal | None = None


class InMemoryReservationStore:
    def __init__(self) -> None:
        self._rows: list[_Row] = []
        self._lock = threading.RLock()

    def _sums(self, line: BudgetLine) -> tuple[Decimal, Decimal]:
        spent, reserved = _ZERO, _ZERO
        for row in self._rows:
            if row.bucket != line.bucket:
                continue
            if row.status == SETTLED:
                spent += row.actual if row.actual is not None else row.amount
            elif row.status in (RESERVED, HELD):
                reserved += row.amount
        return spent, reserved

    def usage(
        self, lines: Sequence[BudgetLine], amount: Money, now: datetime, *, release: bool = True
    ) -> ReservationResult:
        _check_currency(lines, amount)
        with self._lock:
            if release:
                self.release_expired(now)
            return _result(lines, amount, [self._sums(line) for line in lines])

    def reserve(
        self,
        reservation_id: str,
        lines: Sequence[BudgetLine],
        amount: Money,
        *,
        expires_at: datetime,
        now: datetime,
    ) -> ReservationResult:
        _check_currency(lines, amount)
        with self._lock:
            self.release_expired(now)
            result = _result(lines, amount, [self._sums(line) for line in lines])
            if result.ok:
                if any(r.reservation_id == reservation_id for r in self._rows):
                    raise ValueError(f"reservation {reservation_id} already exists")
                for line in lines:
                    self._rows.append(_Row(reservation_id, line.bucket, amount.amount, expires_at))
            return result

    def hold(self, reservation_id: str) -> None:
        with self._lock:
            for row in self._rows:
                if row.reservation_id == reservation_id and row.status == RESERVED:
                    row.status = HELD

    def settle(self, reservation_id: str, actual: Money | None = None) -> None:
        with self._lock:
            for row in self._rows:
                if row.reservation_id == reservation_id and row.status in (
                    RESERVED,
                    HELD,
                    RELEASED,
                ):
                    if actual is not None and actual.currency != row.bucket[3]:
                        raise ValueError("settlement currency differs from the reservation")
                    row.status = SETTLED
                    row.actual = actual.amount if actual is not None else row.amount

    def release(self, reservation_id: str) -> None:
        with self._lock:
            for row in self._rows:
                if row.reservation_id == reservation_id and row.status in (RESERVED, HELD):
                    row.status = RELEASED

    def release_expired(self, now: datetime) -> int:
        with self._lock:
            n = 0
            for row in self._rows:
                if row.status == RESERVED and row.expires_at <= now:
                    row.status = RELEASED
                    n += 1
            return n


class SqliteReservationStore:
    _DDL = """
    CREATE TABLE IF NOT EXISTS budget_reservations (
        reservation_id TEXT NOT NULL,
        budget_key     TEXT NOT NULL,
        period         TEXT NOT NULL,
        period_start   TEXT NOT NULL,
        currency       TEXT NOT NULL,
        amount         TEXT NOT NULL,
        actual         TEXT,
        status         TEXT NOT NULL,
        expires_at     TEXT NOT NULL,
        PRIMARY KEY (reservation_id, budget_key, period, currency)
    );
    CREATE INDEX IF NOT EXISTS idx_budget_bucket
        ON budget_reservations (budget_key, period, period_start, currency, status);
    CREATE INDEX IF NOT EXISTS idx_budget_expiry ON budget_reservations (status, expires_at);
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        with self._lock:
            conn.executescript(self._DDL)
            if conn.in_transaction:
                conn.commit()

    @contextmanager
    def _immediate(self) -> Iterator[None]:
        """``BEGIN IMMEDIATE`` takes SQLite's write lock before the sum is read,
        so no other connection can insert between our check and our insert.
        Inside the gateway's unit of work (already ``BEGIN IMMEDIATE``) the
        caller's transaction covers us."""
        with self._lock:
            if self._conn.in_transaction:
                yield
                return
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _sums(self, line: BudgetLine) -> tuple[Decimal, Decimal]:
        rows = self._conn.execute(
            "SELECT status, amount, actual FROM budget_reservations WHERE budget_key = ? "
            "AND period = ? AND period_start = ? AND currency = ? AND status IN (?, ?, ?)",
            (*line.bucket, RESERVED, HELD, SETTLED),
        ).fetchall()
        spent, reserved = _ZERO, _ZERO
        for status, amount, actual in rows:
            if status == SETTLED:
                spent += Decimal(actual if actual is not None else amount)
            else:
                reserved += Decimal(amount)
        return spent, reserved

    def usage(
        self, lines: Sequence[BudgetLine], amount: Money, now: datetime, *, release: bool = True
    ) -> ReservationResult:
        _check_currency(lines, amount)
        with self._immediate():
            if release:
                self._release_expired(now)
            return _result(lines, amount, [self._sums(line) for line in lines])

    def reserve(
        self,
        reservation_id: str,
        lines: Sequence[BudgetLine],
        amount: Money,
        *,
        expires_at: datetime,
        now: datetime,
    ) -> ReservationResult:
        _check_currency(lines, amount)
        with self._immediate():
            self._release_expired(now)
            result = _result(lines, amount, [self._sums(line) for line in lines])
            if result.ok:
                try:
                    self._conn.executemany(
                        "INSERT INTO budget_reservations (reservation_id, budget_key, period, "
                        "period_start, currency, amount, status, expires_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            (
                                reservation_id,
                                *line.bucket,
                                str(amount.amount),
                                RESERVED,
                                _ts(expires_at),
                            )
                            for line in lines
                        ],
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError(f"reservation {reservation_id} already exists") from exc
            return result

    def settle(self, reservation_id: str, actual: Money | None = None) -> None:
        with self._immediate():
            if actual is not None:
                row = self._conn.execute(
                    "SELECT currency FROM budget_reservations WHERE reservation_id = ? LIMIT 1",
                    (reservation_id,),
                ).fetchone()
                if row is not None and row[0] != actual.currency:
                    raise ValueError("settlement currency differs from the reservation")
            self._conn.execute(
                "UPDATE budget_reservations SET status = ?, actual = COALESCE(?, amount) "
                "WHERE reservation_id = ? AND status IN (?, ?, ?)",
                (
                    SETTLED,
                    str(actual.amount) if actual is not None else None,
                    reservation_id,
                    RESERVED,
                    HELD,
                    RELEASED,
                ),
            )

    def hold(self, reservation_id: str) -> None:
        with self._immediate():
            self._conn.execute(
                "UPDATE budget_reservations SET status = ? WHERE reservation_id = ? AND status = ?",
                (HELD, reservation_id, RESERVED),
            )

    def release(self, reservation_id: str) -> None:
        with self._immediate():
            self._conn.execute(
                "UPDATE budget_reservations SET status = ? "
                "WHERE reservation_id = ? AND status IN (?, ?)",
                (RELEASED, reservation_id, RESERVED, HELD),
            )

    def release_expired(self, now: datetime) -> int:
        with self._immediate():
            return self._release_expired(now)

    def _release_expired(self, now: datetime) -> int:
        cur = self._conn.execute(
            "UPDATE budget_reservations SET status = ? WHERE status = ? AND expires_at <= ?",
            (RELEASED, RESERVED, _ts(now)),
        )
        return cur.rowcount

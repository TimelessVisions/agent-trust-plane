"""Tool execution behind the control boundary.

Tools only ever run from ``TrustPlane.execute`` after a grant has been
verified and consumed. The payments tool writes to a local ledger so tests and
the dashboard can prove what did and did not execute.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from atp_core import ActionEnvelope, ReasonCode, ToolError, new_id, utcnow
from atp_policy import VendorDirectory
from atp_policy.policies import PaymentArguments


class Tool(Protocol):
    name: str

    def execute(self, envelope: ActionEnvelope) -> dict[str, Any]: ...


class ExternalTool:
    """A tool the gateway does not run itself.

    Execution happens in a trusted executor outside the gateway process (for
    example the MCP proxy forwarding to an upstream server). The gateway still
    does everything that binds the decision to the execution: it verifies and
    consumes the grant, re-checks delegation and credential, and records the
    release. The executor then reports the outcome against the consumed grant.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, envelope: ActionEnvelope) -> dict[str, Any]:
        return {"status": "released", "executor": "external", "tool": envelope.tool}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._external_prefixes: list[str] = []

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_external_prefix(self, prefix: str) -> None:
        """Tools named ``<prefix>…`` are executed by an external executor."""
        self._external_prefixes.append(prefix)

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is not None:
            return tool
        if any(name.startswith(p) for p in self._external_prefixes):
            return ExternalTool(name)
        raise ToolError(ReasonCode.TOOL_NOT_REGISTERED, f"tool '{name}' is not registered")

    def is_external(self, name: str) -> bool:
        return name not in self._tools and any(name.startswith(p) for p in self._external_prefixes)

    def names(self) -> list[str]:
        return sorted(self._tools) + [f"{p}*" for p in self._external_prefixes]


class PaymentRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    payment_id: str
    trace_id: str
    envelope_id: str
    agent_id: str
    vendor_id: str
    destination_account: str
    amount: str
    currency: str
    memo: str | None
    settled_at: datetime


class PaymentLedger(Protocol):
    def record(self, payment: PaymentRecord) -> None: ...

    def all(self) -> list[PaymentRecord]: ...


class InMemoryPaymentLedger:
    def __init__(self) -> None:
        self._rows: list[PaymentRecord] = []
        self._lock = threading.Lock()

    def record(self, payment: PaymentRecord) -> None:
        with self._lock:
            self._rows.append(payment)

    def all(self) -> list[PaymentRecord]:
        with self._lock:
            return list(self._rows)


class SqlitePaymentLedger:
    _DDL = """
    CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        body       TEXT NOT NULL
    );
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        with self._lock:
            conn.executescript(self._DDL)
            conn.commit()

    def record(self, payment: PaymentRecord) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO payments (payment_id, body) VALUES (?, ?)",
                (payment.payment_id, payment.model_dump_json()),
            )
            self._conn.commit()

    def all(self) -> list[PaymentRecord]:
        with self._lock:
            rows = self._conn.execute("SELECT body FROM payments ORDER BY rowid").fetchall()
        return [PaymentRecord.model_validate_json(r[0]) for r in rows]


class PaymentsTool:
    """A sandboxed payments rail: settles into the local ledger."""

    name = "payments"

    def __init__(self, ledger: PaymentLedger, vendors: VendorDirectory) -> None:
        self._ledger = ledger
        self._vendors = vendors

    def execute(self, envelope: ActionEnvelope) -> dict[str, Any]:
        if envelope.action != "send_payment":
            raise ToolError(
                ReasonCode.EXECUTION_FAILED, f"payments tool has no action '{envelope.action}'"
            )
        try:
            args = PaymentArguments.model_validate(envelope.arguments)
        except ValidationError as exc:
            raise ToolError(
                ReasonCode.EXECUTION_FAILED, f"invalid payment arguments: {exc}"
            ) from exc
        vendor_id = envelope.resource.split(":", 1)[-1]
        vendor = self._vendors.lookup(vendor_id)
        destination = args.destination_account or (vendor.account_ref if vendor else None)
        if destination is None:
            raise ToolError(
                ReasonCode.EXECUTION_FAILED, f"no destination account for vendor '{vendor_id}'"
            )
        record = PaymentRecord(
            payment_id=new_id("pay"),
            trace_id=envelope.trace_id,
            envelope_id=envelope.envelope_id,
            agent_id=envelope.agent.id,
            vendor_id=vendor_id,
            destination_account=destination,
            amount=format(args.money.amount, "f"),
            currency=args.currency,
            memo=args.memo,
            settled_at=utcnow(),
        )
        self._ledger.record(record)
        return {"status": "settled", **record.model_dump(mode="json")}

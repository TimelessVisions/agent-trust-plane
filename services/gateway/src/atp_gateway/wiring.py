"""Compose a TrustPlane from settings. Kept separate from the HTTP layer so
tests and the eval harness can build one without FastAPI."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from atp_audit import InMemoryTraceStore, SqliteTraceStore, TraceStore
from atp_gateway.grants import GrantSigner, GrantStore, InMemoryGrantStore, SqliteGrantStore
from atp_gateway.reports import EvalReportStore, InMemoryEvalReportStore, SqliteEvalReportStore
from atp_gateway.service import TrustPlane
from atp_gateway.settings import GatewaySettings
from atp_gateway.tools import (
    InMemoryPaymentLedger,
    PaymentLedger,
    PaymentsTool,
    SqlitePaymentLedger,
    ToolRegistry,
)
from atp_identity import (
    DelegationService,
    DelegationStore,
    InMemoryDelegationStore,
    SqliteDelegationStore,
)
from atp_policy import InMemoryVendorDirectory, PolicySetRegistry, Vendor

# The approved-vendor directory the demo runs against. In a real deployment
# this is your ERP / vendor master, not a list in code.
DEMO_VENDORS = [
    Vendor(vendor_id="128", name="Northwind Office Supply", account_ref="acct-nw-4471"),
    Vendor(vendor_id="204", name="Contoso Cloud Services", account_ref="acct-cc-0912"),
    Vendor(vendor_id="311", name="Fabrikam Logistics", account_ref="acct-fl-7730"),
]


class Runtime:
    """Everything the API layer needs, bundled so it can be attached to app.state."""

    def __init__(
        self,
        *,
        trust_plane: TrustPlane,
        ledger: PaymentLedger,
        reports: EvalReportStore,
        vendors: InMemoryVendorDirectory,
        settings: GatewaySettings,
        conn: sqlite3.Connection | None,
    ) -> None:
        self.trust_plane = trust_plane
        self.ledger = ledger
        self.reports = reports
        self.vendors = vendors
        self.settings = settings
        self.conn = conn

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()


def build_runtime(settings: GatewaySettings | None = None) -> Runtime:
    settings = settings or GatewaySettings()
    conn: sqlite3.Connection | None
    delegation_store: DelegationStore
    trace_store: TraceStore
    grant_store: GrantStore
    ledger: PaymentLedger
    reports: EvalReportStore

    if settings.database_path == ":memory:":
        conn = None
        delegation_store = InMemoryDelegationStore()
        trace_store = InMemoryTraceStore()
        grant_store = InMemoryGrantStore()
        ledger = InMemoryPaymentLedger()
        reports = InMemoryEvalReportStore()
    else:
        path = Path(settings.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        delegation_store = SqliteDelegationStore(conn)
        trace_store = SqliteTraceStore(conn)
        grant_store = SqliteGrantStore(conn)
        ledger = SqlitePaymentLedger(conn)
        reports = SqliteEvalReportStore(conn)

    vendors = InMemoryVendorDirectory(DEMO_VENDORS)
    tools = ToolRegistry()
    tools.register(PaymentsTool(ledger, vendors))

    policy_sets = PolicySetRegistry.builtin()
    if settings.default_policy_set != policy_sets.default_version:
        policy_sets = PolicySetRegistry(policy_sets.versions(), settings.default_policy_set)

    trust_plane = TrustPlane(
        delegations=DelegationService(delegation_store),
        traces=trace_store,
        grants=grant_store,
        signer=GrantSigner(settings.signing_key_bytes()),
        policy_sets=policy_sets,
        vendors=vendors,
        tools=tools,
        grant_ttl_seconds=settings.grant_ttl_seconds,
    )
    return Runtime(
        trust_plane=trust_plane,
        ledger=ledger,
        reports=reports,
        vendors=vendors,
        settings=settings,
        conn=conn,
    )

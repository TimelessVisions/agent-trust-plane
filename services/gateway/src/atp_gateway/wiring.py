"""Compose a TrustPlane from settings. Kept separate from the HTTP layer so
tests and the eval harness can build one without FastAPI."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from atp_audit import InMemoryTraceStore, SqliteTraceStore, TraceStore
from atp_core.sqlite import SqliteUnitOfWork, no_transaction
from atp_gateway.approvals import (
    ApprovalStore,
    InMemoryApprovalStore,
    SqliteApprovalStore,
    parse_approver_roles,
)
from atp_gateway.grants import GrantStore, InMemoryGrantStore, SqliteGrantStore
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
    CredentialService,
    CredentialStore,
    DelegationService,
    DelegationStore,
    InMemoryCredentialStore,
    InMemoryDelegationStore,
    InMemoryReservationStore,
    PrincipalKeys,
    ReservationStore,
    SqliteCredentialStore,
    SqliteDelegationStore,
    SqliteReservationStore,
    sign_root_request,
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
        operator_key: str,
        principal_keys: PrincipalKeys | None = None,
    ) -> None:
        self.trust_plane = trust_plane
        self.ledger = ledger
        self.reports = reports
        self.vendors = vendors
        self.settings = settings
        self.conn = conn
        self.operator_key = operator_key
        self.principal_keys = principal_keys

    def root_signer(self) -> Callable[[dict[str, Any]], dict[str, Any]]:
        """Sign a root ``POST /delegations`` body with the grantor's key, where
        this process holds it (the ATP home's local human; any human on an
        ephemeral gateway). A client in this process passes it to
        ``TrustPlaneClient(sign_root=...)``; ``TrustPlaneClient.for_app`` picks it
        up by itself."""
        keys = self.principal_keys

        def sign(body: dict[str, Any]) -> dict[str, Any]:
            if keys is None:
                return dict(body)
            return sign_root_request(body, keys, now=self.trust_plane.clock())

        return sign

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()


def build_runtime(settings: GatewaySettings | None = None) -> Runtime:
    settings = settings or GatewaySettings()
    # Keys first: a misconfigured gateway refuses to start before touching the database.
    keyring = settings.grant_keyring()
    conn: sqlite3.Connection | None
    transaction: Any = no_transaction
    delegation_store: DelegationStore
    trace_store: TraceStore
    grant_store: GrantStore
    credential_store: CredentialStore
    ledger: PaymentLedger
    reports: EvalReportStore
    approvals: ApprovalStore
    reservations: ReservationStore
    principal_keys = settings.principal_keys()
    # Parsed before the database is touched: a bad role map refuses to start.
    approver_roles = parse_approver_roles(settings.approver_roles)

    if settings.database_path == ":memory:":
        conn = None
        delegation_store = InMemoryDelegationStore()
        trace_store = InMemoryTraceStore()
        grant_store = InMemoryGrantStore()
        credential_store = InMemoryCredentialStore()
        ledger = InMemoryPaymentLedger()
        reports = InMemoryEvalReportStore()
        approvals = InMemoryApprovalStore()
        reservations = InMemoryReservationStore()
    else:
        path = Path(settings.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        transaction = SqliteUnitOfWork(conn)
        delegation_store = SqliteDelegationStore(conn)
        trace_store = SqliteTraceStore(conn)
        grant_store = SqliteGrantStore(conn)
        credential_store = SqliteCredentialStore(conn)
        ledger = SqlitePaymentLedger(conn)
        reports = SqliteEvalReportStore(conn)
        approvals = SqliteApprovalStore(conn)
        reservations = SqliteReservationStore(conn)

    vendors = InMemoryVendorDirectory(DEMO_VENDORS)
    tools = ToolRegistry()
    tools.register(PaymentsTool(ledger, vendors))
    for prefix in settings.external_tool_prefix_list():
        tools.register_external_prefix(prefix)

    if settings.policy_file:
        policy_sets = PolicySetRegistry.with_file(
            settings.policy_file, default_version=settings.default_policy_set
        )
    else:
        policy_sets = PolicySetRegistry.builtin()
        if settings.default_policy_set != policy_sets.default_version:
            policy_sets = PolicySetRegistry(policy_sets.versions(), settings.default_policy_set)

    trust_plane = TrustPlane(
        delegations=DelegationService(delegation_store, principal_keys=principal_keys),
        credentials=CredentialService(credential_store),
        traces=trace_store,
        grants=grant_store,
        signer=keyring.signer,
        verifier=keyring.verifier,
        policy_sets=policy_sets,
        vendors=vendors,
        tools=tools,
        grant_ttl_seconds=settings.grant_ttl_seconds,
        enforcement_mode=settings.enforcement_mode,
        transaction=transaction,
        approvals=approvals,
        approver_roles=approver_roles,
        reservations=reservations,
    )
    return Runtime(
        trust_plane=trust_plane,
        ledger=ledger,
        reports=reports,
        vendors=vendors,
        settings=settings,
        conn=conn,
        operator_key=settings.operator_key_value(),
        principal_keys=principal_keys,
    )

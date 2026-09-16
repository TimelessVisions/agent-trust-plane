from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from atp_core import (
    ActionEnvelope,
    AuthorityConstraints,
    EffectiveAuthority,
    Money,
    PrincipalKind,
    PrincipalRef,
)
from atp_identity import DelegationRequest, DelegationService, InMemoryDelegationStore
from atp_policy import InMemoryVendorDirectory, PolicyContext, Vendor

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
HUMAN = PrincipalRef(id="company-user-42", kind=PrincipalKind.HUMAN)
ORCHESTRATOR = PrincipalRef(id="finance-orchestrator", kind=PrincipalKind.AGENT)
AP_AGENT = PrincipalRef(id="accounts-payable-agent", kind=PrincipalKind.AGENT)
DOC_AGENT = PrincipalRef(id="document-agent", kind=PrincipalKind.AGENT)

NORTHWIND = Vendor(vendor_id="128", name="Northwind Office Supply", account_ref="acct-nw-4471")
ATTACKER = "acct-offshore-9931"


def usd(amount: int | str) -> Money:
    return Money(amount=amount, currency="USD")


def vendors() -> InMemoryVendorDirectory:
    return InMemoryVendorDirectory([NORTHWIND])


def build_chain(service: DelegationService) -> dict[str, str]:
    """Human ($10k) -> orchestrator ($10k) -> AP agent ($1k) -> document agent (read-only)."""
    root = service.issue(
        DelegationRequest(
            label="Human authority: payments <= $10,000",
            grantor=HUMAN,
            grantee=HUMAN,
            capabilities=frozenset({"read:invoice", "pay:vendor", "admin:vendors"}),
            resource_scope=("vendor:*", "invoice:*"),
            constraints=AuthorityConstraints(max_amount=usd(10_000), currencies=frozenset({"USD"})),
            expires_at=NOW + timedelta(days=30),
        ),
        now=NOW,
    )
    orch = service.issue(
        DelegationRequest(
            label="Orchestrator: payments <= $10,000",
            grantor=HUMAN,
            grantee=ORCHESTRATOR,
            parent_grant_id=root.grant_id,
            capabilities=frozenset({"read:invoice", "pay:vendor"}),
            resource_scope=("vendor:*", "invoice:*"),
            constraints=AuthorityConstraints(max_amount=usd(10_000)),
            expires_at=NOW + timedelta(days=7),
        ),
        now=NOW,
    )
    ap = service.issue(
        DelegationRequest(
            label="AP agent: vendor payments <= $1,000",
            grantor=ORCHESTRATOR,
            grantee=AP_AGENT,
            parent_grant_id=orch.grant_id,
            capabilities=frozenset({"read:invoice", "pay:vendor"}),
            resource_scope=("vendor:*", "invoice:*"),
            constraints=AuthorityConstraints(max_amount=usd(1_000)),
            expires_at=NOW + timedelta(days=1),
        ),
        now=NOW,
    )
    doc = service.issue(
        DelegationRequest(
            label="Document agent: read-only invoice access",
            grantor=AP_AGENT,
            grantee=DOC_AGENT,
            parent_grant_id=ap.grant_id,
            capabilities=frozenset({"read:invoice"}),
            resource_scope=("invoice:*",),
            constraints=AuthorityConstraints(max_amount=usd(0)),
            expires_at=NOW + timedelta(hours=1),
        ),
        now=NOW,
    )
    return {"root": root.grant_id, "orch": orch.grant_id, "ap": ap.grant_id, "doc": doc.grant_id}


def payment_envelope(
    *,
    agent: PrincipalRef = AP_AGENT,
    grant_id: str,
    amount: str = "480.00",
    resource: str = "vendor:128",
    capability: str = "pay:vendor",
    destination: str | None = None,
    **extra_args: Any,
) -> ActionEnvelope:
    args: dict[str, Any] = {"amount": amount, "currency": "USD", **extra_args}
    if destination is not None:
        args["destination_account"] = destination
    return ActionEnvelope(
        principal=HUMAN,
        agent=agent,
        delegation_grant_id=grant_id,
        capability=capability,
        tool="payments",
        action="send_payment",
        resource=resource,
        arguments=args,
    )


def context_for(
    envelope: ActionEnvelope,
    service: DelegationService,
    *,
    now: datetime = NOW,
) -> PolicyContext:
    from atp_core import DelegationError

    authority: EffectiveAuthority | None = None
    error = None
    try:
        authority = service.resolve(
            envelope.delegation_grant_id,
            agent=envelope.agent,
            principal=envelope.principal,
            now=now,
        ).authority
    except DelegationError as exc:
        error = (exc.reason_code, exc.message)
    return PolicyContext(
        envelope=envelope, authority=authority, resolution_error=error, vendors=vendors(), now=now
    )


def fresh_service() -> DelegationService:
    return DelegationService(InMemoryDelegationStore())

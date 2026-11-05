from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atp_core import AuthorityConstraints, Money, PrincipalKind, PrincipalRef
from atp_identity import (
    DelegationGrant,
    DelegationRequest,
    DelegationService,
    InMemoryDelegationStore,
    InMemoryPrincipalKeys,
    SqliteDelegationStore,
    sign_root_request,
)

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)

HUMAN = PrincipalRef(id="company-user-42", kind=PrincipalKind.HUMAN)
ORCHESTRATOR = PrincipalRef(id="finance-orchestrator", kind=PrincipalKind.AGENT)
AP_AGENT = PrincipalRef(id="accounts-payable-agent", kind=PrincipalKind.AGENT)
DOC_AGENT = PrincipalRef(id="document-agent", kind=PrincipalKind.AGENT)


def usd(amount: int | str) -> Money:
    return Money(amount=amount, currency="USD")


# The human's own key: root grants are signed with it (C5).
HUMAN_KEYS = InMemoryPrincipalKeys()
HUMAN_KEYS.add(HUMAN.id, Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64))))


def signed(
    request: DelegationRequest, keys: InMemoryPrincipalKeys = HUMAN_KEYS
) -> DelegationRequest:
    """The root request as the human's own client signs it."""
    body = sign_root_request(request.model_dump(mode="json", exclude_none=True), keys, now=NOW)
    return DelegationRequest.model_validate(body)


@pytest.fixture(params=["memory", "sqlite"])
def service(request: pytest.FixtureRequest) -> Iterator[DelegationService]:
    if request.param == "memory":
        yield DelegationService(InMemoryDelegationStore(), principal_keys=HUMAN_KEYS)
    else:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        yield DelegationService(SqliteDelegationStore(conn), principal_keys=HUMAN_KEYS)
        conn.close()


@pytest.fixture
def root(service: DelegationService) -> DelegationGrant:
    return service.issue(
        signed(
            DelegationRequest(
                label="Human authority: payments <= $10,000",
                grantor=HUMAN,
                grantee=HUMAN,
                capabilities=frozenset({"read:invoice", "pay:vendor", "admin:vendors"}),
                resource_scope=("vendor:*", "invoice:*"),
                constraints=AuthorityConstraints(
                    max_amount=usd(10_000), currencies=frozenset({"USD"})
                ),
                expires_at=NOW + timedelta(days=30),
            )
        ),
        now=NOW,
    )


@pytest.fixture
def orchestrator_grant(service: DelegationService, root: DelegationGrant) -> DelegationGrant:
    return service.issue(
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


@pytest.fixture
def ap_grant(service: DelegationService, orchestrator_grant: DelegationGrant) -> DelegationGrant:
    return service.issue(
        DelegationRequest(
            label="AP agent: vendor payments <= $1,000",
            grantor=ORCHESTRATOR,
            grantee=AP_AGENT,
            parent_grant_id=orchestrator_grant.grant_id,
            capabilities=frozenset({"read:invoice", "pay:vendor"}),
            resource_scope=("vendor:*", "invoice:*"),
            constraints=AuthorityConstraints(max_amount=usd(1_000)),
            expires_at=NOW + timedelta(days=1),
        ),
        now=NOW,
    )


@pytest.fixture
def doc_grant(service: DelegationService, ap_grant: DelegationGrant) -> DelegationGrant:
    return service.issue(
        DelegationRequest(
            label="Document agent: read-only invoice access",
            grantor=AP_AGENT,
            grantee=DOC_AGENT,
            parent_grant_id=ap_grant.grant_id,
            capabilities=frozenset({"read:invoice"}),
            resource_scope=("invoice:*",),
            constraints=AuthorityConstraints(max_amount=usd(0)),
            expires_at=NOW + timedelta(hours=1),
        ),
        now=NOW,
    )

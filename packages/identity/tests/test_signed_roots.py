"""Root delegations are signed by the human's own key (C5).

A root grant (``parent_grant_id is None``) carries an Ed25519 signature by its
human grantor over the canonical JSON of the grant without ``signature``,
``signer_kid`` and ``revoked_at``. Resolution verifies it; child grants stay
server-resolved and unsigned.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atp_core import DelegationError, PrincipalKind, PrincipalRef, ReasonCode
from atp_identity import (
    DelegationGrant,
    DelegationRequest,
    DelegationService,
    DelegationStore,
    InMemoryDelegationStore,
    InMemoryPrincipalKeys,
    SqliteDelegationStore,
    kid_for,
    root_signing_bytes,
    sign_root,
)

from identity_fixtures import AP_AGENT, HUMAN, NOW

BOB = PrincipalRef(id="bob", kind=PrincipalKind.HUMAN)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest) -> Iterator[DelegationStore]:
    if request.param == "memory":
        yield InMemoryDelegationStore()
    else:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        yield SqliteDelegationStore(conn)
        conn.close()


@pytest.fixture
def keys() -> InMemoryPrincipalKeys:
    k = InMemoryPrincipalKeys()
    k.generate(HUMAN.id)
    k.generate(BOB.id)
    return k


def _root(**kw: object) -> DelegationGrant:
    fields: dict[str, object] = {
        "label": "root",
        "grantor": HUMAN,
        "grantee": HUMAN,
        "capabilities": frozenset({"pay:vendor"}),
        "resource_scope": ("vendor:*",),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(days=30),
        **kw,
    }
    return DelegationGrant.model_validate(fields)


def _request_for(grant: DelegationGrant) -> DelegationRequest:
    return DelegationRequest(
        label=grant.label,
        grantor=grant.grantor,
        grantee=grant.grantee,
        capabilities=grant.capabilities,
        resource_scope=grant.resource_scope,
        constraints=grant.constraints,
        expires_at=grant.expires_at,
        grant_id=grant.grant_id,
        issued_at=grant.issued_at,
        signature=grant.signature,
        signer_kid=grant.signer_kid,
    )


def _child(parent: str) -> DelegationRequest:
    return DelegationRequest(
        label="ap",
        grantor=HUMAN,
        grantee=AP_AGENT,
        parent_grant_id=parent,
        capabilities=frozenset({"pay:vendor"}),
        resource_scope=("vendor:*",),
        expires_at=NOW + timedelta(days=1),
    )


def test_unsigned_root_denied(store: DelegationStore, keys: InMemoryPrincipalKeys) -> None:
    service = DelegationService(store, principal_keys=keys)
    # Issued through the service without a signature: refused.
    with pytest.raises(DelegationError) as exc:
        service.issue(_request_for(_root()), now=NOW)
    assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_UNSIGNED
    # Written straight into the store (the operator's database access): resolution denies.
    unsigned = _root()
    store.put(unsigned)
    child = DelegationGrant(
        label="ap",
        grantor=HUMAN,
        grantee=AP_AGENT,
        parent_grant_id=unsigned.grant_id,
        capabilities=frozenset({"pay:vendor"}),
        resource_scope=("vendor:*",),
        issued_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    store.put(child)
    with pytest.raises(DelegationError) as exc:
        service.resolve(child.grant_id, now=NOW)
    assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_UNSIGNED
    # A signer_kid without a signature is just as unsigned.
    half = _root(signer_kid=kid_for(keys.require_private(HUMAN.id).public_key()))
    store.put(half)
    with pytest.raises(DelegationError) as exc:
        service.resolve(half.grant_id, now=NOW)
    assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_UNSIGNED


def test_root_signed_by_other_human_denied(
    store: DelegationStore, keys: InMemoryPrincipalKeys
) -> None:
    service = DelegationService(store, principal_keys=keys)
    forged = sign_root(_root(), keys.require_private(BOB.id))
    with pytest.raises(DelegationError) as exc:
        service.issue(_request_for(forged), now=NOW)
    assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_SIGNATURE_INVALID
    # Bob's signature with Bob's kid swapped for the human's: still invalid.
    relabelled = forged.model_copy(
        update={"signer_kid": kid_for(keys.require_private(HUMAN.id).public_key())}
    )
    store.put(relabelled)
    with pytest.raises(DelegationError) as exc:
        service.resolve(relabelled.grant_id, now=NOW)
    assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_SIGNATURE_INVALID
    # A key nobody registered for this human (e.g. the operator's own) is invalid too.
    stray = sign_root(_root(), Ed25519PrivateKey.generate())
    with pytest.raises(DelegationError) as exc:
        service.issue(_request_for(stray), now=NOW)
    assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_SIGNATURE_INVALID
    # A human with no registered key cannot have a valid root at all.
    nobody = DelegationService(store, principal_keys=InMemoryPrincipalKeys())
    signed = sign_root(_root(), keys.require_private(HUMAN.id))
    with pytest.raises(DelegationError) as exc:
        nobody.issue(_request_for(signed), now=NOW)
    assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_SIGNATURE_INVALID


def test_signed_root_resolves(store: DelegationStore, keys: InMemoryPrincipalKeys) -> None:
    service = DelegationService(store, principal_keys=keys)
    signed = sign_root(_root(), keys.require_private(HUMAN.id))
    assert signed.signer_kid == kid_for(keys.require_private(HUMAN.id).public_key())
    root = service.issue(_request_for(signed), now=NOW)
    assert (root.grant_id, root.signature, root.issued_at) == (
        signed.grant_id,
        signed.signature,
        signed.issued_at,
    )
    child = service.issue(_child(root.grant_id), now=NOW)
    assert child.signature is None  # children stay unsigned
    chain = service.resolve(child.grant_id, agent=AP_AGENT, principal=HUMAN, now=NOW)
    assert chain.root.grant_id == root.grant_id
    # Revocation does not touch the signed content: the root still verifies,
    # and resolution reports the revocation, not a bad signature.
    service.revoke(root.grant_id, now=NOW)
    with pytest.raises(DelegationError) as exc:
        service.resolve(child.grant_id, now=NOW)
    assert exc.value.reason_code is ReasonCode.DELEGATION_REVOKED


def test_signed_payload_excludes_signature_fields_and_covers_the_rest(
    keys: InMemoryPrincipalKeys,
) -> None:
    grant = _root()
    signed = sign_root(grant, keys.require_private(HUMAN.id))
    assert root_signing_bytes(grant) == root_signing_bytes(signed)
    assert b"signature" not in root_signing_bytes(signed)
    assert b"signer_kid" not in root_signing_bytes(signed)
    widened = signed.model_copy(update={"capabilities": frozenset({"pay:vendor", "admin:all"})})
    service = DelegationService(InMemoryDelegationStore(), principal_keys=keys)
    service.store.put(widened)
    with pytest.raises(DelegationError) as exc:
        service.resolve(widened.grant_id, now=NOW)
    assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_SIGNATURE_INVALID


def test_signature_fields_only_on_roots() -> None:
    with pytest.raises(ValueError, match="root"):
        DelegationRequest(
            label="ap",
            grantor=HUMAN,
            grantee=AP_AGENT,
            parent_grant_id="grt_x",
            capabilities=frozenset({"pay:vendor"}),
            resource_scope=("vendor:*",),
            expires_at=NOW + timedelta(days=1),
            signature="AAAA",
        )

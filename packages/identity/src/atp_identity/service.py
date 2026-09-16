"""Delegation issuance and chain resolution.

Two enforcement points uphold the invariant that a child never holds more
authority than its parent:

* ``issue`` refuses to create a grant that widens its parent's *effective*
  authority (the parent's own chain is resolved first).
* ``resolve`` recomputes effective authority as the intersection of every
  grant on the path to the root, so a grant that somehow got into the store
  with more authority than its parent still cannot exercise it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from atp_core import (
    AuthorityConstraints,
    DelegationError,
    EffectiveAuthority,
    PrincipalKind,
    PrincipalRef,
    ReasonCode,
    utcnow,
)
from atp_identity.grants import DelegationGrant, DelegationRequest
from atp_identity.scope import covers, scope_covers
from atp_identity.store import DelegationStore

MAX_CHAIN_DEPTH = 8


class ResolvedChain(BaseModel):
    """A validated chain, root first, and the authority it yields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    grants: tuple[DelegationGrant, ...]
    authority: EffectiveAuthority

    @property
    def leaf(self) -> DelegationGrant:
        return self.grants[-1]

    @property
    def root(self) -> DelegationGrant:
        return self.grants[0]


class DelegationService:
    def __init__(self, store: DelegationStore) -> None:
        self._store = store

    @property
    def store(self) -> DelegationStore:
        return self._store

    # ------------------------------------------------------------------ resolve
    def resolve(
        self,
        grant_id: str,
        *,
        agent: PrincipalRef | None = None,
        principal: PrincipalRef | None = None,
        now: datetime | None = None,
    ) -> ResolvedChain:
        """Walk from ``grant_id`` to the root, validating every link.

        ``agent`` (if given) must be the leaf grantee; ``principal`` (if given)
        must be the human root. Both checks exist so an agent cannot present a
        grant that was issued to someone else.
        """
        now = now or utcnow()
        chain_leaf_first: list[DelegationGrant] = []
        seen: set[str] = set()
        current_id: str | None = grant_id

        while current_id is not None:
            if current_id in seen:
                raise DelegationError(
                    ReasonCode.DELEGATION_CHAIN_BROKEN, f"cycle detected at grant {current_id}"
                )
            seen.add(current_id)
            if len(chain_leaf_first) >= MAX_CHAIN_DEPTH:
                raise DelegationError(
                    ReasonCode.DELEGATION_CHAIN_TOO_DEEP,
                    f"delegation chain exceeds {MAX_CHAIN_DEPTH} links",
                )
            grant = self._store.get(current_id)
            if grant is None:
                raise DelegationError(
                    ReasonCode.DELEGATION_NOT_FOUND, f"grant {current_id} does not exist"
                )
            if grant.is_revoked():
                raise DelegationError(
                    ReasonCode.DELEGATION_REVOKED,
                    f"grant {grant.grant_id} ({grant.label}) was revoked at "
                    f"{grant.revoked_at.isoformat() if grant.revoked_at else '?'}",
                )
            if grant.is_expired(now):
                raise DelegationError(
                    ReasonCode.DELEGATION_EXPIRED,
                    f"grant {grant.grant_id} ({grant.label}) expired at "
                    f"{grant.expires_at.isoformat()}",
                )
            if chain_leaf_first:
                child = chain_leaf_first[-1]
                if child.grantor != grant.grantee:
                    raise DelegationError(
                        ReasonCode.DELEGATION_CHAIN_BROKEN,
                        f"grant {child.grant_id} was issued by {child.grantor} but its parent "
                        f"{grant.grant_id} was issued to {grant.grantee}",
                    )
            chain_leaf_first.append(grant)
            current_id = grant.parent_grant_id

        chain = tuple(reversed(chain_leaf_first))
        root = chain[0]
        if root.grantor.kind is not PrincipalKind.HUMAN or root.grantor != root.grantee:
            raise DelegationError(
                ReasonCode.DELEGATION_ROOT_NOT_HUMAN,
                f"root grant {root.grant_id} must be a human's self-issued authority",
            )
        leaf = chain[-1]
        if agent is not None and leaf.grantee != agent:
            raise DelegationError(
                ReasonCode.DELEGATION_GRANTEE_MISMATCH,
                f"grant {leaf.grant_id} was issued to {leaf.grantee}, not to {agent}",
            )
        if principal is not None and root.grantor != principal:
            raise DelegationError(
                ReasonCode.DELEGATION_PRINCIPAL_MISMATCH,
                f"grant chain is rooted at {root.grantor}, not at claimed principal {principal}",
            )

        return ResolvedChain(grants=chain, authority=_intersect(chain))

    # -------------------------------------------------------------------- issue
    def issue(self, request: DelegationRequest, *, now: datetime | None = None) -> DelegationGrant:
        now = now or utcnow()
        if request.expires_at <= now:
            raise DelegationError(
                ReasonCode.DELEGATION_EXPIRED, "a grant cannot be issued already expired"
            )

        if request.parent_grant_id is None:
            self._check_root(request)
        else:
            self._check_against_parent(request, now)

        grant = DelegationGrant(
            label=request.label,
            grantor=request.grantor,
            grantee=request.grantee,
            parent_grant_id=request.parent_grant_id,
            capabilities=request.capabilities,
            resource_scope=request.resource_scope,
            constraints=request.constraints,
            issued_at=now,
            expires_at=request.expires_at,
        )
        self._store.put(grant)
        return grant

    def revoke(self, grant_id: str, *, now: datetime | None = None) -> DelegationGrant:
        grant = self._store.revoke(grant_id, now or utcnow())
        if grant is None:
            raise DelegationError(ReasonCode.DELEGATION_NOT_FOUND, f"grant {grant_id} not found")
        return grant

    @staticmethod
    def _check_root(request: DelegationRequest) -> None:
        if request.grantor.kind is not PrincipalKind.HUMAN:
            raise DelegationError(
                ReasonCode.DELEGATION_ROOT_NOT_HUMAN,
                "a root grant can only originate from a human principal",
            )
        if request.grantor != request.grantee:
            raise DelegationError(
                ReasonCode.DELEGATION_ROOT_NOT_HUMAN,
                "a root grant must be self-issued (grantor == grantee); delegate from it instead",
            )

    def _check_against_parent(self, request: DelegationRequest, now: datetime) -> None:
        assert request.parent_grant_id is not None
        try:
            parent_chain = self.resolve(request.parent_grant_id, now=now)
        except DelegationError as exc:
            raise DelegationError(
                ReasonCode.DELEGATION_PARENT_INVALID,
                f"parent grant is not usable: {exc.message}",
            ) from exc
        parent = parent_chain.leaf
        authority = parent_chain.authority

        if request.grantor != parent.grantee:
            raise DelegationError(
                ReasonCode.DELEGATION_GRANTOR_NOT_GRANTEE_OF_PARENT,
                f"{request.grantor} cannot delegate from grant {parent.grant_id}; "
                f"it was issued to {parent.grantee}",
            )
        if request.grantor == request.grantee:
            raise DelegationError(
                ReasonCode.DELEGATION_SELF_GRANT, "a principal cannot delegate to itself"
            )

        extra_caps = request.capabilities - authority.capabilities
        if extra_caps:
            raise DelegationError(
                ReasonCode.DELEGATION_EXCEEDS_PARENT_CAPABILITIES,
                f"capabilities {sorted(extra_caps)} are not held by {request.grantor}",
            )
        if not scope_covers(authority.resource_scope, request.resource_scope):
            raise DelegationError(
                ReasonCode.DELEGATION_EXCEEDS_PARENT_RESOURCE_SCOPE,
                f"resource scope {list(request.resource_scope)} is wider than "
                f"{list(authority.resource_scope)}",
            )
        _check_constraints(authority.constraints, request.constraints)
        if request.expires_at > authority.expires_at:
            raise DelegationError(
                ReasonCode.DELEGATION_EXCEEDS_PARENT_EXPIRY,
                f"expiry {request.expires_at.isoformat()} is later than the parent chain's "
                f"{authority.expires_at.isoformat()}",
            )


def _check_constraints(parent: AuthorityConstraints, child: AuthorityConstraints) -> None:
    if parent.max_amount is not None:
        if child.max_amount is None:
            raise DelegationError(
                ReasonCode.DELEGATION_EXCEEDS_PARENT_AMOUNT,
                f"parent limits amount to {parent.max_amount}; child must state a limit",
            )
        if child.max_amount.currency != parent.max_amount.currency:
            raise DelegationError(
                ReasonCode.DELEGATION_EXCEEDS_PARENT_AMOUNT,
                "child monetary limit must use the parent's currency",
            )
        if child.max_amount.exceeds(parent.max_amount):
            raise DelegationError(
                ReasonCode.DELEGATION_EXCEEDS_PARENT_AMOUNT,
                f"requested limit {child.max_amount} exceeds parent limit {parent.max_amount}",
            )
    if (
        parent.currencies is not None
        and child.currencies is not None
        and not child.currencies <= parent.currencies
    ):
        raise DelegationError(
            ReasonCode.DELEGATION_EXCEEDS_PARENT_CURRENCIES,
            f"currencies {sorted(child.currencies - parent.currencies)} not permitted",
        )


def _intersect(chain: tuple[DelegationGrant, ...]) -> EffectiveAuthority:
    """Chain-wise intersection. Root is chain[0]."""
    root, leaf = chain[0], chain[-1]
    capabilities = frozenset(root.capabilities)
    max_amount = root.constraints.max_amount
    currencies = root.constraints.currencies
    expires_at = root.expires_at
    ancestors_scope: list[tuple[str, ...]] = [root.resource_scope]

    for grant in chain[1:]:
        capabilities &= grant.capabilities
        child_max = grant.constraints.max_amount
        if child_max is not None and (
            max_amount is None
            or (child_max.currency == max_amount.currency and not child_max.exceeds(max_amount))
        ):
            max_amount = child_max
        if grant.constraints.currencies is not None:
            currencies = (
                grant.constraints.currencies
                if currencies is None
                else currencies & grant.constraints.currencies
            )
        expires_at = min(expires_at, grant.expires_at)
        ancestors_scope.append(grant.resource_scope)

    # The leaf's scope, keeping only patterns every ancestor covers.
    effective_scope = tuple(
        pattern
        for pattern in leaf.resource_scope
        if all(any(covers(p, pattern) for p in anc) for anc in ancestors_scope[:-1])
    )

    return EffectiveAuthority(
        root_principal=root.grantor,
        holder=leaf.grantee,
        grant_chain=tuple(g.grant_id for g in chain),
        capabilities=capabilities,
        resource_scope=effective_scope,
        constraints=AuthorityConstraints(max_amount=max_amount, currencies=currencies),
        expires_at=expires_at,
    )

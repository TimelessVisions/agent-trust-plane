"""Property-based tests for the identity kernel (Hypothesis).

AUTHORITY MONOTONICITY: whatever chain the service accepts, the effective
authority at every link is contained in the effective authority of its
parent: capabilities, resource scope (by coverage), monetary limit,
currencies and expiry. The service must also *reject* any request that
would widen one of those dimensions.

SCOPE ALGEBRA: ``covers(p, c)`` is sound: every resource matched by ``c``
is matched by ``p``.
"""

from __future__ import annotations

from datetime import timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from atp_core import AuthorityConstraints, DelegationError, Money, PrincipalKind, PrincipalRef
from atp_identity import DelegationRequest, DelegationService, InMemoryDelegationStore
from atp_identity.scope import covers, matches, scope_covers, validate_pattern

from identity_fixtures import NOW

CAPS = ["a:read", "a:write", "b:read", "b:write", "c:admin"]
TYPES = ["path", "vendor"]
IDS = ["/w", "/w/x", "/w/x/y", "/v", "128", "129", "12"]


@st.composite
def scope_pattern(draw: st.DrawFn) -> str:
    if draw(st.booleans()) and draw(st.integers(0, 9)) == 0:
        return "*"
    typ = draw(st.sampled_from(TYPES))
    kind = draw(st.sampled_from(["exact", "prefix", "all"]))
    if kind == "all":
        return f"{typ}:*"
    ident = draw(st.sampled_from(IDS))
    return f"{typ}:{ident}*" if kind == "prefix" else f"{typ}:{ident}"


@st.composite
def resource(draw: st.DrawFn) -> str:
    return f"{draw(st.sampled_from(TYPES))}:{draw(st.sampled_from(IDS))}"


@given(parent=scope_pattern(), child=scope_pattern(), res=resource())
def test_covers_is_sound(parent: str, child: str, res: str) -> None:
    validate_pattern(parent)
    validate_pattern(child)
    if covers(parent, child) and matches(child, res):
        assert matches(parent, res)


@given(pattern=scope_pattern())
def test_every_pattern_covers_itself(pattern: str) -> None:
    assert covers(pattern, pattern)


HUMAN = PrincipalRef(id="h", kind=PrincipalKind.HUMAN)


def agent(i: int) -> PrincipalRef:
    return PrincipalRef(id=f"agent-{i}", kind=PrincipalKind.AGENT)


@st.composite
def link_request(draw: st.DrawFn) -> dict[str, object]:
    caps = frozenset(draw(st.lists(st.sampled_from(CAPS), min_size=1, max_size=4)))
    scope = tuple(draw(st.lists(scope_pattern(), min_size=1, max_size=3)))
    amount = draw(st.one_of(st.none(), st.integers(0, 20_000)))
    currencies = draw(
        st.one_of(st.none(), st.frozensets(st.sampled_from(["USD", "EUR", "GBP"]), min_size=1))
    )
    days = draw(st.integers(1, 40))
    return {"caps": caps, "scope": scope, "amount": amount, "currencies": currencies, "days": days}


@settings(max_examples=200, deadline=None)
@given(links=st.lists(link_request(), min_size=1, max_size=5))
def test_accepted_chains_never_widen(links: list[dict[str, object]]) -> None:
    service = DelegationService(InMemoryDelegationStore())
    first = links[0]
    root = service.issue(
        DelegationRequest(
            label="root",
            grantor=HUMAN,
            grantee=HUMAN,
            capabilities=first["caps"],  # type: ignore[arg-type]
            resource_scope=first["scope"],  # type: ignore[arg-type]
            constraints=AuthorityConstraints(
                max_amount=Money(amount=first["amount"], currency="USD")  # type: ignore[arg-type]
                if first["amount"] is not None
                else None,
                currencies=first["currencies"],  # type: ignore[arg-type]
            ),
            expires_at=NOW + timedelta(days=first["days"]),  # type: ignore[arg-type]
        ),
        now=NOW,
    )
    parent = root
    grantor = HUMAN
    for i, link in enumerate(links[1:], start=1):
        parent_auth = service.resolve(parent.grant_id, now=NOW).authority
        request = DelegationRequest(
            label=f"link {i}",
            grantor=grantor,
            grantee=agent(i),
            parent_grant_id=parent.grant_id,
            capabilities=link["caps"],  # type: ignore[arg-type]
            resource_scope=link["scope"],  # type: ignore[arg-type]
            constraints=AuthorityConstraints(
                max_amount=Money(amount=link["amount"], currency="USD")  # type: ignore[arg-type]
                if link["amount"] is not None
                else None,
                currencies=link["currencies"],  # type: ignore[arg-type]
            ),
            expires_at=NOW + timedelta(days=link["days"]),  # type: ignore[arg-type]
        )
        widened = (
            not request.capabilities <= parent_auth.capabilities
            or not scope_covers(parent_auth.resource_scope, request.resource_scope)
            or (
                parent_auth.constraints.max_amount is not None
                and (
                    request.constraints.max_amount is None
                    or request.constraints.max_amount.exceeds(parent_auth.constraints.max_amount)
                )
            )
            or (
                parent_auth.constraints.currencies is not None
                and request.constraints.currencies is not None
                and not request.constraints.currencies <= parent_auth.constraints.currencies
            )
            or request.expires_at > parent_auth.expires_at
        )
        try:
            child = service.issue(request, now=NOW)
        except DelegationError:
            assert widened, "service rejected a request that does not widen authority"
            return
        assert not widened, "service accepted a widening request"
        child_auth = service.resolve(child.grant_id, now=NOW).authority
        assert child_auth.capabilities <= parent_auth.capabilities
        assert scope_covers(parent_auth.resource_scope, child_auth.resource_scope)
        if parent_auth.constraints.max_amount is not None:
            assert child_auth.constraints.max_amount is not None
            assert not child_auth.constraints.max_amount.exceeds(parent_auth.constraints.max_amount)
        if parent_auth.constraints.currencies is not None:
            assert child_auth.constraints.currencies is not None
            assert child_auth.constraints.currencies <= parent_auth.constraints.currencies
        assert child_auth.expires_at <= parent_auth.expires_at
        assert child_auth.holder == agent(i)
        assert child_auth.root_principal == HUMAN
        parent, grantor = child, agent(i)

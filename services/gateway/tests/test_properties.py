"""Property-based and stateful tests of the execution kernel (Hypothesis).

These drive ``TrustPlane`` directly (no HTTP) with a controllable clock and
check the invariants from ``docs/first-principles.md``:

* EXECUTION EXACTNESS — every ledger row's action hash equals the hash of an
  action the gateway authorized with ALLOW;
* SINGLE USE — the ledger never has more rows than consumed grants, and no
  grant is consumed twice;
* REVOCATION — after a delegation or credential is revoked, no new ledger
  row appears;
* REPLAY SAFETY — replay never changes the ledger or the grant store;
* POLICY DETERMINISM — the same envelope decided twice under the same
  authority snapshot yields the same outcome, reason and matched policy;
* EVIDENCE PRECEDENCE — on every trace, ``decision_made`` precedes any
  ``execution_*`` event and a ``grant_issued`` event exists before an
  ``execution_completed``.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from atp_audit import EventType
from atp_core import (
    ActionEnvelope,
    AuthorityConstraints,
    DecisionOutcome,
    Money,
    PrincipalRef,
    new_trace_id,
)
from atp_gateway import GatewaySettings, Runtime, build_runtime
from atp_gateway.grants import GrantStatus
from atp_identity import AuthenticatedAgent, DelegationRequest

from gateway_fixtures import (
    AP_AGENT,
    ATTACKER_ACCOUNT,
    HUMAN,
    NOW,
    OPERATOR_KEY,
    ORCHESTRATOR,
    SIGNING_KEY,
    Clock,
)


def _runtime(clock: Clock) -> Runtime:
    rt = build_runtime(
        GatewaySettings(
            database_path=":memory:",
            grant_signing_key=SIGNING_KEY,
            operator_key=OPERATOR_KEY,
        )
    )
    rt.trust_plane.clock = clock
    return rt


def _chain(rt: Runtime, limit: str = "1000") -> str:
    tp = rt.trust_plane
    root = tp.issue_delegation(
        DelegationRequest(
            label="root",
            grantor=HUMAN,
            grantee=HUMAN,
            capabilities=frozenset({"pay:vendor", "read:invoice"}),
            resource_scope=("vendor:*", "invoice:*"),
            constraints=AuthorityConstraints(max_amount=Money(amount="10000", currency="USD")),
            expires_at=NOW + timedelta(days=30),
        )
    )
    orch = tp.issue_delegation(
        DelegationRequest(
            label="orch",
            grantor=HUMAN,
            grantee=ORCHESTRATOR,
            parent_grant_id=root.grant_id,
            capabilities=frozenset({"pay:vendor", "read:invoice"}),
            resource_scope=("vendor:*", "invoice:*"),
            constraints=AuthorityConstraints(max_amount=Money(amount="10000", currency="USD")),
            expires_at=NOW + timedelta(days=7),
        )
    )
    ap = tp.issue_delegation(
        DelegationRequest(
            label="ap",
            grantor=ORCHESTRATOR,
            grantee=AP_AGENT,
            parent_grant_id=orch.grant_id,
            capabilities=frozenset({"pay:vendor", "read:invoice"}),
            resource_scope=("vendor:*", "invoice:*"),
            constraints=AuthorityConstraints(max_amount=Money(amount=limit, currency="USD")),
            expires_at=NOW + timedelta(days=1),
        )
    )
    return ap.grant_id


def _caller(rt: Runtime, agent: PrincipalRef = AP_AGENT) -> AuthenticatedAgent:
    _, token = rt.trust_plane.credentials.issue(agent, label="prop", now=NOW)
    return rt.trust_plane.credentials.authenticate(token, now=NOW)


def _envelope(
    grant_id: str, amount: str, *, destination: str | None = None, vendor: str = "128"
) -> ActionEnvelope:
    args: dict[str, Any] = {"amount": amount, "currency": "USD"}
    if destination:
        args["destination_account"] = destination
    return ActionEnvelope(
        trace_id=new_trace_id(),
        principal=HUMAN,
        agent=AP_AGENT,
        delegation_grant_id=grant_id,
        capability="pay:vendor",
        tool="payments",
        action="send_payment",
        resource=f"vendor:{vendor}",
        arguments=args,
    )


amounts = st.decimals(min_value=Decimal("0"), max_value=Decimal("20000"), places=2).map(
    lambda d: format(d, "f")
)


@settings(max_examples=60, deadline=None)
@given(amount=amounts, destination=st.sampled_from([None, "acct-nw-4471", ATTACKER_ACCOUNT]))
def test_decision_is_deterministic_and_bounded_by_authority(
    amount: str, destination: str | None
) -> None:
    clock = Clock()
    rt = _runtime(clock)
    grant = _chain(rt)
    caller = _caller(rt)
    env = _envelope(grant, amount, destination=destination)
    a = rt.trust_plane.authorize(env, caller)
    # A second decision on the same action (fresh trace) must agree.
    env2 = env.model_copy(update={"trace_id": new_trace_id()})
    b = rt.trust_plane.authorize(env2, caller)
    assert (a.decision.outcome, a.decision.reason_code, a.decision.matched_policy) == (
        b.decision.outcome,
        b.decision.reason_code,
        b.decision.matched_policy,
    )
    # Authority bound: anything over the delegated limit is never ALLOW.
    if Decimal(amount) > Decimal("1000"):
        assert a.decision.outcome is not DecisionOutcome.ALLOW
        assert a.execution_grant is None
    if destination == ATTACKER_ACCOUNT:
        assert a.decision.outcome is DecisionOutcome.DENY
    # Grant iff ALLOW.
    assert (a.execution_grant is not None) == (a.decision.outcome is DecisionOutcome.ALLOW)
    rt.close()


class GrantLifecycle(RuleBasedStateMachine):
    """authorize -> mint -> consume once -> execute, with revocation, expiry,
    replay and tampering interleaved in any order Hypothesis chooses."""

    def __init__(self) -> None:
        super().__init__()
        self.clock = Clock()
        self.rt = _runtime(self.clock)
        self.tp = self.rt.trust_plane
        self.grant_id = _chain(self.rt)
        self.caller = _caller(self.rt)
        self.pending: list[tuple[ActionEnvelope, str, str]] = []  # (env, token, grant_id)
        self.consumed: set[str] = set()
        self.executed_hashes: list[str] = []
        self.revoked = False
        self.traces: list[str] = []

    @rule(amount=amounts)
    def authorize(self, amount: str) -> None:
        env = _envelope(self.grant_id, amount)
        result = self.tp.authorize(env, self.caller)
        self.traces.append(env.trace_id)
        if result.execution_grant is not None:
            assert result.decision.outcome is DecisionOutcome.ALLOW
            assert Decimal(amount) <= Decimal("1000")
            self.pending.append(
                (env, result.execution_grant.token, result.execution_grant.grant_id)
            )
        else:
            assert result.decision.outcome is not DecisionOutcome.ALLOW or self.revoked

    @rule(index=st.integers(min_value=0, max_value=9))
    def execute_pending(self, index: int) -> None:
        if not self.pending:
            return
        env, token, gid = self.pending[index % len(self.pending)]
        result = self.tp.execute(env, token, self.caller)
        if result.status == "completed":
            assert gid not in self.consumed, "a grant produced two side effects"
            assert not self.revoked, "side effect after revocation"
            self.consumed.add(gid)
            self.executed_hashes.append(env.action_hash)
        else:
            assert result.status == "blocked"
            assert self.tp.grants.get(gid) is not None

    @rule(index=st.integers(min_value=0, max_value=9), amount=amounts)
    def execute_tampered(self, index: int, amount: str) -> None:
        """Use a real token with a modified action: must never execute."""
        if not self.pending:
            return
        env, token, gid = self.pending[index % len(self.pending)]
        tampered = env.model_copy(update={"arguments": {"amount": amount, "currency": "USD"}})
        if tampered.action_hash == env.action_hash:
            return
        result = self.tp.execute(tampered, token, self.caller)
        assert result.status == "blocked"
        # Whichever check fires first (expiry, mismatch), the tampered action never runs.
        assert result.reason_code.value in ("GRANT_ENVELOPE_MISMATCH", "GRANT_EXPIRED")

    @rule()
    def replay_latest(self) -> None:
        if not self.traces:
            return
        before = self.rt.ledger.all()
        self.tp.replay(self.traces[-1], policy_set_version="payments-v1")
        assert self.rt.ledger.all() == before

    @rule()
    def revoke_delegation(self) -> None:
        if self.revoked:
            return
        self.tp.revoke_delegation(self.grant_id)
        self.revoked = True

    @rule(seconds=st.integers(min_value=1, max_value=200))
    def advance_clock(self, seconds: int) -> None:
        self.clock.advance(seconds=seconds)

    @invariant()
    def ledger_matches_consumed_grants(self) -> None:
        rows = self.rt.ledger.all()
        assert len(rows) == len(self.consumed)
        consumed_in_store = [
            gid
            for gid in self.consumed
            if self.tp.grants.get(gid).status is GrantStatus.CONSUMED  # type: ignore[union-attr]
        ]
        assert len(consumed_in_store) == len(self.consumed)

    @invariant()
    def executed_actions_were_authorized(self) -> None:
        authorized = {env.action_hash for env, _, _ in self.pending}
        assert set(self.executed_hashes) <= authorized

    @invariant()
    def evidence_precedes_execution(self) -> None:
        for trace_id in self.traces[-3:]:
            events = self.tp.traces.events(trace_id)
            types = [e.event_type for e in events]
            if EventType.EXECUTION_COMPLETED in types:
                assert types.index(EventType.DECISION_MADE) < types.index(
                    EventType.EXECUTION_COMPLETED
                )
                assert types.index(EventType.GRANT_ISSUED) < types.index(
                    EventType.EXECUTION_COMPLETED
                )
            assert self.tp.traces.verify(trace_id).valid

    def teardown(self) -> None:
        self.rt.close()


GrantLifecycle.TestCase.settings = settings(max_examples=40, stateful_step_count=25, deadline=None)
TestGrantLifecycle = GrantLifecycle.TestCase

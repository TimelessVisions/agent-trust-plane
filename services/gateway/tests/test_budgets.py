"""Cumulative budgets with reservations (Task C4, Review Focus 3).

Reserve at mint, settle on outcome, release on expiry. A reservation whose
execution never reports back is released at grant expiry; two concurrent
reservations cannot together exceed the budget.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atp_core import ActionEnvelope, Budget, Money
from atp_gateway import GatewaySettings, Runtime, build_runtime, create_app
from atp_identity import BudgetLine, InMemoryReservationStore, SqliteReservationStore
from atp_policy.explain import explain, format_explanation

from gateway_fixtures import (
    AP_AGENT,
    GRANT_KEY_SETTINGS,
    HUMAN,
    NOW,
    OPERATOR_KEY,
    ORCHESTRATOR,
    Clock,
    authorize,
    bearer,
    execute,
    issue_credential,
    op,
    payment_envelope,
    usd,
)


def _budget(amount: str, period: str = "day") -> dict[str, Any]:
    return {"amount": usd(amount), "period": period}


def budget_chain(
    client: TestClient,
    *,
    orch_budget: dict[str, Any] | None = None,
    ap_budget: dict[str, Any] | None = None,
    ap_max: str = "1000",
    currencies: list[str] | None = None,
) -> dict[str, Any]:
    """Human -> orchestrator ($10k max) -> AP agent, with optional budgets."""
    orch_cred = issue_credential(client, ORCHESTRATOR)
    ap_cred = issue_credential(client, AP_AGENT)

    def issue(body: dict[str, Any], headers: dict[str, str]) -> str:
        r = client.post("/delegations", json=body, headers=headers)
        assert r.status_code == 201, r.text
        grant_id: str = r.json()["grant_id"]
        return grant_id

    root_constraints: dict[str, Any] = {"max_amount": usd("10000")}
    if currencies:
        root_constraints["currencies"] = currencies
    root = issue(
        {
            "label": "root",
            "grantor": HUMAN.model_dump(mode="json"),
            "grantee": HUMAN.model_dump(mode="json"),
            "capabilities": ["pay:vendor"],
            "resource_scope": ["vendor:*"],
            "constraints": root_constraints,
            "expires_at": (NOW + timedelta(days=90)).isoformat(),
        },
        op(),
    )
    orch_constraints: dict[str, Any] = {"max_amount": usd("10000")}
    if orch_budget:
        orch_constraints["budget"] = orch_budget
    orch = issue(
        {
            "label": "orchestrator",
            "grantor": HUMAN.model_dump(mode="json"),
            "grantee": ORCHESTRATOR.model_dump(mode="json"),
            "parent_grant_id": root,
            "capabilities": ["pay:vendor"],
            "resource_scope": ["vendor:*"],
            "constraints": orch_constraints,
            "expires_at": (NOW + timedelta(days=60)).isoformat(),
        },
        op(),
    )
    ap_constraints: dict[str, Any] = {"max_amount": usd(ap_max)}
    if ap_budget:
        ap_constraints["budget"] = ap_budget
    ap = issue(
        {
            "label": "AP agent",
            "grantor": ORCHESTRATOR.model_dump(mode="json"),
            "grantee": AP_AGENT.model_dump(mode="json"),
            "parent_grant_id": orch,
            "capabilities": ["pay:vendor"],
            "resource_scope": ["vendor:*"],
            "constraints": ap_constraints,
            "expires_at": (NOW + timedelta(days=45)).isoformat(),
        },
        bearer(orch_cred["token"]),
    )
    return {"root": root, "orch": orch, "ap": ap, "token": ap_cred["token"]}


def pay(client: TestClient, chain: dict[str, Any], amount: str, **kw: Any) -> dict[str, Any]:
    env = payment_envelope(chain["ap"], amount=amount, **kw)
    out = authorize(client, env, chain["token"])
    out["envelope"] = env
    return out


def pay_and_execute(client: TestClient, chain: dict[str, Any], amount: str) -> None:
    out = pay(client, chain, amount)
    assert out["decision"]["outcome"] == "ALLOW", out["decision"]
    done = execute(client, out["envelope"], out["execution_grant"]["token"], chain["token"])
    assert done["status"] == "completed", done


def _explained(client: TestClient, trace_id: str) -> str:
    view = client.get(f"/traces/{trace_id}", headers=op()).json()
    from atp_core import Decision

    x = explain(
        Decision.model_validate(view["decision"]),
        ActionEnvelope.model_validate(view["envelope"]),
        view["delegation_chain"],
    )
    return format_explanation(x)


# ----------------------------------------------------------------- the six
def test_budget_denies_when_period_spend_exceeded(client: TestClient) -> None:
    chain = budget_chain(client, ap_budget=_budget("1000"))
    pay_and_execute(client, chain, "600.00")
    over = pay(client, chain, "500.00")
    assert over["decision"]["outcome"] == "DENY"
    assert over["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    assert over["execution_grant"] is None
    text = _explained(client, over["envelope"]["trace_id"])
    for needle in ("limit=1000.00", "spent=600.00", "reserved=0.00", "requested=500.00"):
        assert needle in text, text
    # What still fits is allowed.
    pay_and_execute(client, chain, "400.00")
    assert pay(client, chain, "0.01")["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"


def test_reservation_released_on_expiry(client: TestClient, clock: Clock) -> None:
    chain = budget_chain(client, ap_budget=_budget("500"))
    held = pay(client, chain, "400.00")  # authorized, never executed, never reported
    assert held["decision"]["outcome"] == "ALLOW"
    blocked = pay(client, chain, "200.00")
    assert blocked["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    text = _explained(client, blocked["envelope"]["trace_id"])
    assert "reserved=400.00" in text and "spent=0.00" in text
    clock.advance(seconds=121)  # grant TTL is 120 s
    # Released lazily on the next reserve.
    assert pay(client, chain, "200.00")["decision"]["outcome"] == "ALLOW"
    # The expired grant cannot be used to spend the released money either.
    late = execute(client, held["envelope"], held["execution_grant"]["token"], chain["token"])
    assert late["status"] == "blocked"


def test_trace_list_releases_expired_reservations(
    runtime: Runtime, client: TestClient, clock: Clock
) -> None:
    chain = budget_chain(client, ap_budget=_budget("500"))
    assert pay(client, chain, "400.00")["decision"]["outcome"] == "ALLOW"
    store = runtime.trust_plane.reservations
    line = _line(chain, "500.00")
    assert store.usage(
        [line], Money(amount=Decimal("0"), currency="USD"), clock(), release=False
    ).usages[0].reserved == Decimal("400.00")
    clock.advance(seconds=121)
    assert client.get("/traces", headers=op()).status_code == 200
    usage = store.usage([line], Money(amount=Decimal("0"), currency="USD"), clock(), release=False)
    assert usage.usages[0].reserved == Decimal("0.00")


def test_concurrent_reservations_cannot_exceed(tmp_path: Path) -> None:
    """Real threads, one SQLite file, one connection per thread (as separate
    gateway processes would have): 8 x $300 against $1,000 -> exactly 3 win."""
    db = tmp_path / "budgets.db"
    line = BudgetLine(
        key="human:h>agent:a",
        grant_id="grt_x",
        period="day",
        period_start=datetime(2026, 9, 16, tzinfo=UTC),
        limit=Money(amount=Decimal("1000"), currency="USD"),
    )
    n = 8
    conns = [sqlite3.connect(db, check_same_thread=False, timeout=30) for _ in range(n)]
    try:
        stores = [SqliteReservationStore(c) for c in conns]
        barrier = threading.Barrier(n)
        results: list[bool] = []
        lock = threading.Lock()

        def go(i: int) -> None:
            barrier.wait()
            r = stores[i].reserve(
                f"res_{i}",
                [line],
                Money(amount=Decimal("300"), currency="USD"),
                expires_at=NOW + timedelta(minutes=2),
                now=NOW,
            )
            with lock:
                results.append(r.ok)

        threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert len(results) == n
        assert results.count(True) == 3
        total = stores[0].usage([line], Money(amount=Decimal("0"), currency="USD"), NOW)
        assert total.usages[0].reserved == Decimal("900.00")
    finally:
        for c in conns:
            c.close()


def test_concurrent_authorizations_two_gateways_one_budget(tmp_path: Path) -> None:
    """Two gateways on one SQLite file race two $300 payments against $500."""
    settings = GatewaySettings(
        database_path=str(tmp_path / "atp.db"), **GRANT_KEY_SETTINGS, operator_key=OPERATOR_KEY
    )
    a, b = build_runtime(settings), build_runtime(settings)
    clock = Clock()
    a.trust_plane.clock = b.trust_plane.clock = clock
    try:
        with TestClient(create_app(settings, runtime=a)) as client:
            chain = budget_chain(client, ap_budget=_budget("500"))
        envs = [
            ActionEnvelope.model_validate(payment_envelope(chain["ap"], amount="300.00"))
            for _ in range(2)
        ]
        barrier = threading.Barrier(2)
        results: list[Any] = []

        def go(rt: Runtime, env: ActionEnvelope) -> None:
            tp = rt.trust_plane
            caller = tp.identity.authenticate(
                {"authorization": f"Bearer {chain['token']}"}, now=tp.clock()
            )
            barrier.wait()
            results.append(tp.authorize(env, caller))

        threads = [threading.Thread(target=go, args=p) for p in zip((a, b), envs, strict=True)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        outcomes = sorted(r.decision.reason_code.value for r in results)
        assert outcomes == ["ALLOWED", "PAYMENT_EXCEEDS_BUDGET"]
    finally:
        a.close()
        b.close()


def test_new_period_resets(client: TestClient, clock: Clock) -> None:
    chain = budget_chain(client, ap_budget=_budget("500"))
    pay_and_execute(client, chain, "500.00")
    assert pay(client, chain, "100.00")["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    # NOW is 12:00 UTC; one second before midnight is still the same day.
    clock.advance(hours=11, minutes=59, seconds=59)
    assert pay(client, chain, "100.00")["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    clock.advance(seconds=1)
    assert pay(client, chain, "100.00")["decision"]["outcome"] == "ALLOW"


def test_tightest_budget_in_chain_wins(client: TestClient) -> None:
    chain = budget_chain(client, orch_budget=_budget("500"), ap_budget=_budget("300"))
    over = pay(client, chain, "400.00")
    assert over["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    assert "limit=300.00" in _explained(client, over["envelope"]["trace_id"])
    pay_and_execute(client, chain, "300.00")
    # And the other way round: the parent's tighter budget binds the child.
    chain2 = budget_chain(client, orch_budget=_budget("200"), ap_budget=_budget("900"))
    over2 = pay(client, chain2, "250.00")
    assert over2["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    assert "limit=200.00" in _explained(client, over2["envelope"]["trace_id"])


def test_settle_with_lower_actual_frees_difference(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "b.db", check_same_thread=False)
    try:
        store = SqliteReservationStore(conn)
        line = _line({"ap": "grt_x"}, "500.00")
        exp = NOW + timedelta(minutes=2)
        assert store.reserve("r1", [line], _usd("400"), expires_at=exp, now=NOW).ok
        assert not store.reserve("r2", [line], _usd("400"), expires_at=exp, now=NOW).ok
        store.settle("r1", _usd("100"))
        usage = store.usage([line], _usd("0"), NOW).usages[0]
        assert (usage.spent, usage.reserved) == (Decimal("100.00"), Decimal("0.00"))
        assert store.reserve("r2", [line], _usd("400"), expires_at=exp, now=NOW).ok
        # A settled reservation is spent: expiry does not release it.
        later = NOW + timedelta(hours=1)
        assert store.usage([line], _usd("0"), later).usages[0].spent == Decimal("100.00")
    finally:
        conn.close()


# ------------------------------------------------------------- the rest
def _usd(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="USD")


def _line(chain: dict[str, Any], limit: str) -> BudgetLine:
    return BudgetLine(
        key=f"{HUMAN}>{AP_AGENT}",
        grant_id=chain["ap"],
        period="day",
        period_start=datetime(2026, 9, 16, tzinfo=UTC),
        limit=_usd(limit),
    )


def test_budgets_with_different_periods_apply_independently(
    client: TestClient, clock: Clock
) -> None:
    chain = budget_chain(client, orch_budget=_budget("700", "month"), ap_budget=_budget("500"))
    pay_and_execute(client, chain, "500.00")
    assert pay(client, chain, "1.00")["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    clock.advance(days=1)  # new day; same month: 200 left of the monthly budget
    over = pay(client, chain, "300.00")
    assert over["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    assert "limit=700.00" in _explained(client, over["envelope"]["trace_id"])
    pay_and_execute(client, chain, "200.00")


def test_external_outcome_settles_or_releases(tmp_path: Path) -> None:
    """Released to an external executor: a failure report releases the
    reservation, a success report settles it."""
    settings = GatewaySettings(
        database_path=str(tmp_path / "atp.db"),
        **GRANT_KEY_SETTINGS,
        operator_key=OPERATOR_KEY,
        external_tool_prefixes="ext.",
    )
    rt = build_runtime(settings)
    rt.trust_plane.clock = Clock()
    try:
        with TestClient(create_app(settings, runtime=rt)) as client:
            chain = budget_chain(client, ap_budget=_budget("500"))

            def run(amount: str, succeeded: bool, headers: dict[str, str]) -> None:
                out = pay(client, chain, amount, tool="ext.pay")
                assert out["decision"]["outcome"] == "ALLOW", out["decision"]
                grant = out["execution_grant"]
                done = execute(client, out["envelope"], grant["token"], chain["token"])
                assert done["status"] == "released"
                r = client.post(
                    f"/executions/{grant['grant_id']}/outcome",
                    json={"succeeded": succeeded, "summary": {}},
                    headers=headers,
                )
                assert r.status_code == 200, r.text

            # A failure the operator reports releases: the 400 is free again.
            run("400.00", succeeded=False, headers=op())
            run("400.00", succeeded=True, headers=bearer(chain["token"]))  # settled
            out = pay(client, chain, "200.00", tool="ext.pay")
            assert out["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    finally:
        rt.close()


def test_budget_currency_mismatch_denied(client: TestClient) -> None:
    chain = budget_chain(
        client,
        ap_budget={"amount": {"amount": "500", "currency": "EUR"}, "period": "day"},
    )
    out = pay(client, chain, "10.00")
    assert out["decision"]["outcome"] == "DENY"
    assert out["decision"]["reason_code"] == "PAYMENT_CURRENCY_NOT_PERMITTED"
    assert out["execution_grant"] is None


def test_approved_payment_still_bounded_by_budget(runtime: Runtime, client: TestClient) -> None:
    """C3 x C4: an approval lifts the threshold, never the budget. The over-
    budget retry is denied and the approval stays unused."""
    runtime.trust_plane.approver_roles = {"human:alice": frozenset({"finance-manager"})}
    chain = budget_chain(client, ap_budget=_budget("1200"))
    big = pay(client, chain, "800.00")
    assert big["decision"]["outcome"] == "REQUIRE_APPROVAL"
    r = client.post(
        f"/approvals/{big['envelope']['trace_id']}",
        json={"approver": {"id": "alice", "kind": "human"}, "decision": "approve"},
        headers=op(),
    )
    assert r.status_code == 201, r.text
    pay_and_execute(client, chain, "500.00")  # meanwhile, 500 of 1200 is spent
    retry = authorize(client, big["envelope"], chain["token"])
    assert retry["decision"]["outcome"] == "DENY"
    assert retry["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    assert retry["execution_grant"] is None
    records = runtime.trust_plane.approvals.for_trace(big["envelope"]["trace_id"])
    assert [rec.status.value for rec in records] == ["approved"]
    # An over-budget action is not even put to an approver.
    fresh = pay(client, chain, "750.01")
    assert fresh["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"


def test_period_boundaries_are_utc_calendar() -> None:
    day = Budget(amount=_usd("1"), period="day")
    week = Budget(amount=_usd("1"), period="week")
    month = Budget(amount=_usd("1"), period="month")
    wed = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)  # a Wednesday
    assert day.period_start(wed) == datetime(2026, 9, 16, tzinfo=UTC)
    assert week.period_start(wed) == datetime(2026, 9, 14, tzinfo=UTC)  # ISO Monday
    assert week.period_start(datetime(2026, 9, 14, tzinfo=UTC)) == datetime(2026, 9, 14, tzinfo=UTC)
    sunday_late = datetime(2026, 9, 20, 23, 59, 59, tzinfo=UTC)
    assert week.period_start(sunday_late) == datetime(2026, 9, 14, tzinfo=UTC)
    assert month.period_start(wed) == datetime(2026, 9, 1, tzinfo=UTC)
    assert month.period_end(datetime(2026, 12, 31, 23, 0, tzinfo=UTC)) == datetime(
        2027, 1, 1, tzinfo=UTC
    )
    # A non-UTC timestamp is placed by its UTC instant.
    tz = datetime(2026, 9, 16, 1, 0, tzinfo=UTC).astimezone(
        __import__("datetime").timezone(timedelta(hours=5))
    )
    assert day.period_start(tz) == datetime(2026, 9, 16, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["year", "hour"])
def test_unknown_period_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        Budget.model_validate({"amount": {"amount": "1", "currency": "USD"}, "period": bad})


def test_explain_names_budget_source(client: TestClient) -> None:
    chain = budget_chain(client, ap_budget=_budget("300"))
    over = pay(client, chain, "400.00")
    text = _explained(client, over["envelope"]["trace_id"])
    assert "PAYMENT_EXCEEDS_BUDGET" in text
    assert "raise the budget on the grant that sets it" in text
    assert chain["ap"] in text.split("what would need to change:")[1]


# ------------------------------------------------------ fix round 1 (C4)
def _external_runtime(tmp_path: Path) -> tuple[GatewaySettings, Runtime, Clock]:
    settings = GatewaySettings(
        database_path=str(tmp_path / "atp.db"),
        **GRANT_KEY_SETTINGS,
        operator_key=OPERATOR_KEY,
        external_tool_prefixes="ext.",
    )
    rt = build_runtime(settings)
    clk = Clock()
    rt.trust_plane.clock = clk
    return settings, rt, clk


def _release_external(client: TestClient, chain: dict[str, Any], amount: str) -> str:
    out = pay(client, chain, amount, tool="ext.pay")
    assert out["decision"]["outcome"] == "ALLOW", out["decision"]
    grant = out["execution_grant"]
    done = execute(client, out["envelope"], grant["token"], chain["token"])
    assert done["status"] == "released"
    grant_id: str = grant["grant_id"]
    return grant_id


def _report(
    client: TestClient,
    chain: dict[str, Any],
    grant_id: str,
    succeeded: bool,
    *,
    operator: bool = False,
) -> None:
    r = client.post(
        f"/executions/{grant_id}/outcome",
        json={"succeeded": succeeded, "summary": {}},
        headers=op() if operator else bearer(chain["token"]),
    )
    assert r.status_code == 200, r.text


def test_unreported_external_payment_cannot_exceed_budget(tmp_path: Path) -> None:
    """A payment released to an external executor stays reserved until its
    outcome is reported, however long that takes: grant expiry does not free it."""
    settings, rt, clk = _external_runtime(tmp_path)
    try:
        with TestClient(create_app(settings, runtime=rt)) as client:
            chain = budget_chain(client, ap_budget=_budget("500"))
            first = _release_external(client, chain, "400.00")
            clk.advance(seconds=121)  # the grant has expired; the money may still move
            assert client.get("/traces", headers=op()).status_code == 200
            for _ in range(2):
                again = pay(client, chain, "400.00", tool="ext.pay")
                assert again["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
            assert "reserved=400.00" in _explained(client, again["envelope"]["trace_id"])
            # A late success report settles it: spent, never above the limit.
            _report(client, chain, first, succeeded=True)
            usage = rt.trust_plane.reservations.usage([_line(chain, "500")], _usd("0"), clk())
            assert (usage.usages[0].spent, usage.usages[0].reserved) == (
                Decimal("400.00"),
                Decimal("0.00"),
            )
            assert pay(client, chain, "100.01")["decision"]["reason_code"] == (
                "PAYMENT_EXCEEDS_BUDGET"
            )
    finally:
        rt.close()


def test_late_external_failure_releases_held_reservation(tmp_path: Path) -> None:
    settings, rt, clk = _external_runtime(tmp_path)
    try:
        with TestClient(create_app(settings, runtime=rt)) as client:
            chain = budget_chain(client, ap_budget=_budget("500"))
            held = _release_external(client, chain, "400.00")
            clk.advance(seconds=121)
            assert pay(client, chain, "200.00")["decision"]["reason_code"] == (
                "PAYMENT_EXCEEDS_BUDGET"
            )
            _report(client, chain, held, succeeded=False, operator=True)
            assert pay(client, chain, "500.00")["decision"]["outcome"] == "ALLOW"
    finally:
        rt.close()


def test_store_held_reservation_survives_expiry_and_settle_on_released_counts(
    tmp_path: Path,
) -> None:
    """Store contract. ``hold`` exempts a reservation from lazy expiry.
    Ruling: ``settle`` on a RELEASED reservation records it as spent (the
    money moved), even past the limit; a RELEASED row can only come from a
    never-used grant or an explicit failure, so this is a reconciliation path."""
    conn = sqlite3.connect(tmp_path / "b.db", check_same_thread=False)
    try:
        for store in (SqliteReservationStore(conn), InMemoryReservationStore()):
            line = _line({"ap": "grt_x"}, "500.00")
            exp = NOW + timedelta(minutes=2)
            later = NOW + timedelta(hours=1)
            assert store.reserve("h", [line], _usd("400"), expires_at=exp, now=NOW).ok
            store.hold("h")
            assert store.release_expired(later) == 0
            assert not store.reserve("x", [line], _usd("200"), expires_at=later, now=later).ok
            store.release("h")
            assert store.reserve(
                "y", [line], _usd("500"), expires_at=exp + timedelta(hours=2), now=later
            ).ok
            store.settle("h")  # released, then reported as having happened after all
            u = store.usage([line], _usd("0"), later).usages[0]
            assert (u.spent, u.reserved) == (Decimal("400.00"), Decimal("500.00"))
            conn.execute("DELETE FROM budget_reservations")
    finally:
        conn.close()


class _FailingTool:
    name = "payments"

    def execute(self, envelope: ActionEnvelope) -> dict[str, Any]:
        from atp_core import ReasonCode
        from atp_gateway.tools import ToolError

        raise ToolError(ReasonCode.EXECUTION_FAILED, "rail down")


def test_tool_failure_releases_reservation(runtime: Runtime, client: TestClient) -> None:
    chain = budget_chain(client, ap_budget=_budget("500"))
    runtime.trust_plane.tools.register(_FailingTool())
    out = pay(client, chain, "400.00")
    done = execute(client, out["envelope"], out["execution_grant"]["token"], chain["token"])
    assert done["status"] == "failed"
    usage = runtime.trust_plane.reservations.usage(
        [_line(chain, "500")], _usd("0"), runtime.trust_plane.clock()
    )
    assert (usage.usages[0].spent, usage.usages[0].reserved) == (Decimal("0.00"), Decimal("0.00"))


def test_budget_lines_keeps_tightest_of_two_budgets_on_one_key() -> None:
    from atp_core import ChainBudget
    from atp_identity import budget_lines

    budgets = [
        ChainBudget(grant_id=g, grantee=AP_AGENT, budget=Budget(amount=_usd(a), period="day"))
        for g, a in (("grt_loose", "900"), ("grt_tight", "300"), ("grt_mid", "500"))
    ]
    lines = budget_lines(budgets, HUMAN, NOW)
    assert [(ln.grant_id, ln.limit.amount) for ln in lines] == [("grt_tight", Decimal("300.00"))]


def test_store_reserve_refusal_honoured_after_precheck_passes(
    runtime: Runtime, client: TestClient
) -> None:
    """The peek passes, then another process takes the room before our
    reserve: the reserve's refusal decides."""
    from atp_identity import InMemoryReservationStore as Base

    class Racing(Base):
        def reserve(self, reservation_id: str, lines: Any, amount: Money, **kw: Any) -> Any:
            super().reserve("rival", lines, amount, **kw)
            return super().reserve(reservation_id, lines, amount, **kw)

    runtime.trust_plane.reservations = Racing()
    chain = budget_chain(client, ap_budget=_budget("500"))
    out = pay(client, chain, "300.00")
    assert out["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    assert out["execution_grant"] is None


def test_replay_of_budget_denial_is_not_a_change(client: TestClient) -> None:
    chain = budget_chain(client, ap_budget=_budget("300"))
    over = pay(client, chain, "400.00")
    assert over["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
    r = client.post(f"/replay/{over['envelope']['trace_id']}", json={}, headers=op())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome_changed"] is False
    assert body["budget_reevaluated"] is False
    assert "budget not re-evaluated" in body["summary"]
    # An ordinary replay still says nothing about budgets being skipped.
    ok = pay(client, chain, "100.00")
    plain = client.post(f"/replay/{ok['envelope']['trace_id']}", json={}, headers=op()).json()
    assert "budget not re-evaluated" not in plain["summary"]


@pytest.mark.parametrize("amount", ["1e30", " 10.00", "10.00 ", "10.00\n"])
def test_unusable_amount_denied_as_invalid(client: TestClient, amount: str) -> None:
    chain = budget_chain(client, ap_budget=_budget("500"))
    out = pay(client, chain, amount)
    assert out["decision"]["outcome"] == "DENY"
    assert out["decision"]["reason_code"] == "PAYMENT_ARGUMENTS_INVALID"


@pytest.mark.parametrize("amount", ["1e30", " 1.00", "1.00 "])
def test_money_rejects_huge_or_padded_amounts_as_value_error(amount: str) -> None:
    with pytest.raises(ValueError):
        Money.model_validate({"amount": amount, "currency": "USD"})


# ------------------------------------------------------ fix round 2 (C4)
def test_agent_failure_report_does_not_free_budget(tmp_path: Path) -> None:
    """Ruling: the grant's own agent cannot free budget by claiming failure.
    A released external payment stays counted (held) after an agent-reported
    failure; it cannot be repeated to spend past the limit. Only the operator
    can confirm a failure and release it."""
    settings, rt, clk = _external_runtime(tmp_path)
    try:
        with TestClient(create_app(settings, runtime=rt)) as client:
            chain = budget_chain(client, ap_budget=_budget("500"))
            first = _release_external(client, chain, "400.00")
            _report(client, chain, first, succeeded=False)
            for _ in range(2):
                again = pay(client, chain, "200.00", tool="ext.pay")
                assert again["decision"]["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
            clk.advance(seconds=121)  # and grant expiry does not free it either
            assert pay(client, chain, "200.00")["decision"]["reason_code"] == (
                "PAYMENT_EXCEEDS_BUDGET"
            )
            usage = rt.trust_plane.reservations.usage([_line(chain, "500")], _usd("0"), clk())
            assert usage.usages[0].reserved == Decimal("400.00")
            events = client.get(f"/traces/{again['envelope']['trace_id']}", headers=op())
            assert events.status_code == 200
            # The agent cannot report a second time; the operator can confirm.
            r = client.post(
                f"/executions/{first}/outcome",
                json={"succeeded": False, "summary": {}},
                headers=bearer(chain["token"]),
            )
            assert r.json()["reason_code"] == "EXECUTION_OUTCOME_ALREADY_REPORTED"
            _report(client, chain, first, succeeded=False, operator=True)
            assert pay(client, chain, "500.00")["decision"]["outcome"] == "ALLOW"
            r = client.post(
                f"/executions/{first}/outcome",
                json={"succeeded": False, "summary": {}},
                headers=op(),
            )
            assert r.json()["reason_code"] == "EXECUTION_OUTCOME_ALREADY_REPORTED"
    finally:
        rt.close()


def test_outcome_report_needs_agent_or_operator(tmp_path: Path) -> None:
    settings, rt, _ = _external_runtime(tmp_path)
    try:
        with TestClient(create_app(settings, runtime=rt)) as client:
            chain = budget_chain(client, ap_budget=_budget("500"))
            first = _release_external(client, chain, "400.00")
            r = client.post(
                f"/executions/{first}/outcome", json={"succeeded": False, "summary": {}}
            )
            assert r.json()["reason_code"] == "AGENT_CREDENTIAL_MISSING"
    finally:
        rt.close()


def test_hold_after_peer_expired_reservation_blocks_execution(tmp_path: Path) -> None:
    """Two gateways, one database; the peer's clock runs ahead and expires the
    reservation before this gateway consumes the grant. ``hold`` then changes
    nothing, and the payment must not run unbudgeted."""
    settings = GatewaySettings(
        database_path=str(tmp_path / "atp.db"), **GRANT_KEY_SETTINGS, operator_key=OPERATOR_KEY
    )
    a, b = build_runtime(settings), build_runtime(settings)
    a.trust_plane.clock = Clock()
    b.trust_plane.clock = Clock(NOW + timedelta(seconds=121))  # skewed ahead
    try:
        with TestClient(create_app(settings, runtime=a)) as client:
            chain = budget_chain(client, ap_budget=_budget("500"))
            out = pay(client, chain, "400.00")
            assert out["decision"]["outcome"] == "ALLOW"
            b.trust_plane.list_traces()  # the peer releases what it sees as expired
            done = execute(client, out["envelope"], out["execution_grant"]["token"], chain["token"])
            assert done["status"] == "blocked"
            assert done["reason_code"] == "PAYMENT_EXCEEDS_BUDGET"
            assert client.get("/ledger/payments", headers=op()).json() == []
    finally:
        a.close()
        b.close()


def test_store_hold_reports_whether_reservation_is_held(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "b.db", check_same_thread=False)
    try:
        for store in (SqliteReservationStore(conn), InMemoryReservationStore()):
            line = _line({"ap": "grt_x"}, "500.00")
            exp = NOW + timedelta(minutes=2)
            assert store.hold("no-such-reservation")  # unbudgeted: nothing to hold
            assert store.reserve("h", [line], _usd("100"), expires_at=exp, now=NOW).ok
            assert store.hold("h")
            assert store.hold("h")  # idempotent
            assert store.reserve("e", [line], _usd("100"), expires_at=exp, now=NOW).ok
            assert store.release_expired(exp) == 1
            assert not store.hold("e")
    finally:
        conn.close()

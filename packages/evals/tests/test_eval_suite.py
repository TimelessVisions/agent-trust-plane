from __future__ import annotations

from collections.abc import Iterator

import pytest

from atp_adapter_http import TrustPlaneClient
from atp_evals import SCENARIOS, EvalContext, EvalScenario, EvalStatus, run_scenario, run_suite
from atp_evals.runner import format_report
from atp_gateway import GatewaySettings, create_app


@pytest.fixture
def client() -> Iterator[TrustPlaneClient]:
    app = create_app(GatewaySettings(database_path=":memory:"))
    with TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key) as c:
        yield c


def test_full_suite_passes(client: TrustPlaneClient) -> None:
    report = run_suite(client)
    failures = [r for r in report.results if r.status is not EvalStatus.PASS]
    assert not failures, format_report(report)
    assert report.total == len(SCENARIOS) == 8
    # Every eval produced at least one inspectable trace with valid integrity.
    for r in report.results:
        assert r.primary_trace_id
        assert client.get_trace(r.primary_trace_id)["integrity"]["valid"]


def test_eval_ids_are_unique_and_ordered() -> None:
    ids = [s.eval_id for s in SCENARIOS]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_harness_reports_failed_checks_honestly(client: TrustPlaneClient) -> None:
    def wrong_expectation(ctx: EvalContext) -> str:
        ctx.expect("sky.colour", "blue", "green")
        return "should not be reported as pass"

    result = run_scenario(EvalScenario("X-1", "t", "t", "d", wrong_expectation), client)
    assert result.status is EvalStatus.FAIL
    assert "sky.colour" in result.explanation
    assert result.checks[0].passed is False


def test_harness_reports_exceptions_as_error(client: TrustPlaneClient) -> None:
    def boom(ctx: EvalContext) -> str:
        raise RuntimeError("scenario crashed")

    result = run_scenario(EvalScenario("X-2", "t", "t", "d", boom), client)
    assert result.status is EvalStatus.ERROR
    assert result.error and "scenario crashed" in result.error


def test_scenario_with_no_checks_is_not_a_pass(client: TrustPlaneClient) -> None:
    result = run_scenario(EvalScenario("X-3", "t", "t", "d", lambda ctx: "did nothing"), client)
    assert result.status is EvalStatus.FAIL


def test_format_report_mentions_every_eval(client: TrustPlaneClient) -> None:
    text = format_report(run_suite(client))
    for s in SCENARIOS:
        assert s.eval_id in text
    assert "8/8 passed" in text

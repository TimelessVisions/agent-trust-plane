from __future__ import annotations

import time
import traceback
from typing import TYPE_CHECKING

from atp_adapter_http import TrustPlaneClient
from atp_core import new_id, utcnow
from atp_evals.harness import EvalContext, EvalScenario
from atp_evals.model import EvalReport, EvalResult, EvalStatus
from atp_evals.scenarios import SCENARIOS
from finance_agent import SimulatedAgent, seed_delegation_graph

if TYPE_CHECKING:
    from atp_gateway import Runtime


def run_scenario(scenario: EvalScenario, client: TrustPlaneClient) -> EvalResult:
    """Each scenario gets a fresh delegation graph so evals cannot interfere."""
    started = time.perf_counter()
    graph = seed_delegation_graph(client)
    ctx = EvalContext(client=client, graph=graph, brain=SimulatedAgent())
    error: str | None = None
    explanation = ""
    try:
        explanation = scenario.run(ctx)
    except Exception:
        error = traceback.format_exc()
    duration_ms = int((time.perf_counter() - started) * 1000)

    if error is not None:
        status = EvalStatus.ERROR
        explanation = "The scenario raised an exception before completing its checks."
    elif all(c.passed for c in ctx.checks) and ctx.checks:
        status = EvalStatus.PASS
    else:
        status = EvalStatus.FAIL
        failed = [c for c in ctx.checks if not c.passed]
        explanation = f"{len(failed)} check(s) failed: " + "; ".join(
            f"{c.name} expected {c.expected!r} got {c.observed!r}" for c in failed
        )

    return EvalResult(
        eval_id=scenario.eval_id,
        title=scenario.title,
        threat=scenario.threat,
        description=scenario.description,
        status=status,
        checks=tuple(ctx.checks),
        explanation=explanation,
        trace_ids=tuple(ctx.trace_ids),
        primary_trace_id=ctx.primary_trace_id,
        decision=ctx.decision,
        error=error,
        duration_ms=duration_ms,
    )


def run_suite(
    client: TrustPlaneClient, scenarios: tuple[EvalScenario, ...] = SCENARIOS
) -> EvalReport:
    started = utcnow()
    health = client.health()
    results = tuple(run_scenario(s, client) for s in scenarios)
    return EvalReport(
        run_id=new_id("run"),
        started_at=started,
        finished_at=utcnow(),
        gateway=health,
        results=results,
    )


def run_suite_in_process(runtime: Runtime) -> EvalReport:
    """Run the suite against an existing gateway runtime through its real
    HTTP routes, without a network."""
    from atp_gateway import create_app

    app = create_app(runtime.settings, runtime=runtime)
    with TrustPlaneClient.for_app(app, operator_key=runtime.operator_key) as client:
        return run_suite(client)


def format_report(report: EvalReport) -> str:
    width = 78
    lines = ["=" * width, "AGENT TRUST PLANE  -  adversarial evaluation report", "=" * width]
    lines.append(f"run {report.run_id}  policy set {report.gateway.get('default_policy_set')}")
    lines.append("")
    for r in report.results:
        lines.append(f"[{r.status.value:5}] {r.eval_id}  {r.title}")
        lines.append(f"        threat: {r.threat}")
        if r.primary_trace_id:
            lines.append(f"        trace:  {r.primary_trace_id}")
        lines.append(f"        checks: {sum(c.passed for c in r.checks)}/{len(r.checks)} passed")
        for c in r.checks:
            if not c.passed:
                lines.append(f"          x {c.name}: expected {c.expected!r}, got {c.observed!r}")
        lines.append(f"        {r.explanation}")
        if r.error:
            lines.append("        " + r.error.strip().replace("\n", "\n        "))
        lines.append("")
    s = report.summary()
    lines.append("-" * width)
    lines.append(f"{s['passed']}/{s['total']} passed")
    return "\n".join(lines)

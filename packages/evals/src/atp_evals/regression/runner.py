"""Run a regression suite against an ephemeral, in-process gateway.

Decision-only by construction: the runner calls ``/authorize`` and never
``/execute``, so a suite can be run anywhere (laptop, CI) with no side
effects. Each run gets a fresh gateway, fresh credentials and a fresh
delegation graph, so results depend only on the suite and the policy set.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict, Field

from atp_adapter_http import GatewayError, TrustPlaneClient
from atp_core import ActionEnvelope, PrincipalKind, Provenance, new_id, new_trace_id, utcnow
from atp_evals.regression.format import CaseSpec, Suite, parse_duration
from atp_gateway import GatewaySettings, create_app


class CaseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    passed: bool
    expected_outcome: str
    observed_outcome: str | None
    expected_reason: str | None
    observed_reason: str | None
    expected_policy: str | None
    observed_policy: str | None
    explanation: str
    trace_id: str | None = None
    error: str | None = None
    duration_ms: int
    decision: dict[str, Any] | None = Field(
        default=None, description="The full decision (evaluations, authority) for analysis."
    )


class SuiteReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    suite: str
    policy_set: str
    started_at: datetime
    finished_at: datetime
    results: tuple[CaseResult, ...]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return len(self.results) - self.passed

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def changed(self) -> list[CaseResult]:
        return [r for r in self.results if not r.passed]


class _Seeded:
    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}
        self.grants: dict[str, str] = {}


def _seed(operator: TrustPlaneClient, suite: Suite) -> _Seeded:
    seeded = _Seeded()
    now = utcnow()
    for alias, principal in suite.delegations.principals.items():
        if principal.kind is not PrincipalKind.HUMAN:
            issued = operator.issue_credential(
                principal.model_dump(mode="json"), label=f"regression:{alias}"
            )
            seeded.tokens[alias] = issued["token"]
    for g in suite.delegations.grants:
        grantor = suite.delegations.principals[g.grantor]
        body: dict[str, Any] = {
            "label": g.label or g.id,
            "grantor": grantor.model_dump(mode="json"),
            "grantee": suite.delegations.principals[g.grantee].model_dump(mode="json"),
            "parent_grant_id": seeded.grants[g.parent] if g.parent else None,
            "capabilities": list(g.capabilities),
            "resource_scope": list(g.resource_scope),
            "constraints": {
                "max_amount": g.max_amount.model_dump(mode="json") if g.max_amount else None,
                "currencies": list(g.currencies) if g.currencies else None,
            },
            "expires_at": (now + parse_duration(g.expires_in)).isoformat(),
        }
        client = (
            operator
            if grantor.kind is PrincipalKind.HUMAN
            else operator.as_agent(seeded.tokens[g.grantor])
        )
        seeded.grants[g.id] = client.issue_delegation(body)["grant_id"]
    return seeded


def _envelope(suite: Suite, case: CaseSpec, seeded: _Seeded) -> ActionEnvelope:
    return ActionEnvelope(
        trace_id=new_trace_id(),
        principal=suite.delegations.principals[case.principal],
        agent=suite.delegations.principals[case.agent],
        delegation_grant_id=seeded.grants[case.delegation],
        capability=case.capability,
        tool=case.tool,
        action=case.action,
        resource=case.resource,
        arguments=dict(case.arguments),
        provenance=Provenance(
            task_description=f"regression case: {case.name}",
            agent_rationale=case.description or None,
        ),
    )


def ephemeral_settings(version: str, policy_file: str | None) -> GatewaySettings:
    return GatewaySettings(
        _env_file=None,  # type: ignore[call-arg]
        database_path=":memory:",
        default_policy_set=version,
        policy_file=policy_file or "",
    )


def decide_cases(
    suite: Suite,
    cases: Sequence[CaseSpec],
    *,
    policy_set: str | None = None,
    policy_file: str | None = None,
) -> list[CaseResult]:
    """Decide ``cases`` against the suite's delegation graph on a fresh
    ephemeral gateway. ``/authorize`` only; nothing executes."""
    version = policy_set or suite.policy_set
    app = create_app(ephemeral_settings(version, policy_file or suite.policies))
    results: list[CaseResult] = []
    with TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key) as operator:
        seeded = _seed(operator, suite)
        for case in cases:
            results.append(_run_case(suite, case, seeded, operator, version))
    return results


def run_suite(
    suite: Suite, *, policy_set: str | None = None, policy_file: str | None = None
) -> SuiteReport:
    started = utcnow()
    version = policy_set or suite.policy_set
    results = decide_cases(suite, suite.cases, policy_set=version, policy_file=policy_file)
    return SuiteReport(
        run_id=new_id("reg"),
        suite=suite.name,
        policy_set=version,
        started_at=started,
        finished_at=utcnow(),
        results=tuple(results),
    )


def _run_case(
    suite: Suite, case: CaseSpec, seeded: _Seeded, operator: TrustPlaneClient, version: str
) -> CaseResult:
    t0 = time.perf_counter()
    agent = operator.as_agent(seeded.tokens[case.agent])
    exp = case.expect
    try:
        env = _envelope(suite, case, seeded)
        auth = agent.authorize(env)
    except (GatewayError, ValueError) as exc:
        return CaseResult(
            name=case.name,
            passed=False,
            expected_outcome=exp.outcome.value,
            observed_outcome=None,
            expected_reason=exp.reason_code,
            observed_reason=None,
            expected_policy=exp.matched_policy,
            observed_policy=None,
            explanation=f"could not obtain a decision: {exc}",
            error=str(exc),
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
    d = auth.decision
    observed_policy = d.matched_policy.qualified if d.matched_policy else None
    problems: list[str] = []
    if d.outcome is not exp.outcome:
        problems.append(f"outcome {d.outcome.value} (expected {exp.outcome.value})")
    if exp.reason_code and d.reason_code.value != exp.reason_code:
        problems.append(f"reason {d.reason_code.value} (expected {exp.reason_code})")
    if exp.matched_policy and observed_policy != exp.matched_policy:
        problems.append(f"policy {observed_policy} (expected {exp.matched_policy})")
    passed = not problems
    if passed:
        explanation = (
            f"{d.outcome.value} {d.reason_code.value}"
            + (f" by {observed_policy}" if observed_policy else "")
            + f" under {version}"
        )
    else:
        responsible = observed_policy or (
            "no policy matched" if d.is_allow else d.reason_code.value
        )
        explanation = "; ".join(problems) + f" -- responsible: {responsible} under {version}"
    return CaseResult(
        name=case.name,
        passed=passed,
        expected_outcome=exp.outcome.value,
        observed_outcome=d.outcome.value,
        expected_reason=exp.reason_code,
        observed_reason=d.reason_code.value,
        expected_policy=exp.matched_policy,
        observed_policy=observed_policy,
        explanation=explanation,
        trace_id=d.trace_id,
        duration_ms=int((time.perf_counter() - t0) * 1000),
        decision=d.model_dump(mode="json"),
    )


# ------------------------------------------------------------------ output
def format_text(report: SuiteReport) -> str:
    width = 78
    lines = [
        "=" * width,
        f"AGENT TRUST PLANE  regression suite: {report.suite}",
        f"policy set: {report.policy_set}   run: {report.run_id}",
        "=" * width,
    ]
    for r in report.results:
        mark = "PASS" if r.passed else "FAIL"
        lines.append(f"[{mark}] {r.name}")
        lines.append(
            f"       expected {r.expected_outcome}"
            + (f" {r.expected_reason}" if r.expected_reason else "")
            + (f" by {r.expected_policy}" if r.expected_policy else "")
        )
        lines.append(
            f"       observed {r.observed_outcome}"
            + (f" {r.observed_reason}" if r.observed_reason else "")
            + (f" by {r.observed_policy}" if r.observed_policy else "")
        )
        lines.append(f"       {r.explanation}")
        if r.trace_id:
            lines.append(
                f"       trace {r.trace_id} (ephemeral gateway; decision only, nothing executed)"
            )
        lines.append("")
    lines.append("-" * width)
    lines.append(f"{report.passed}/{len(report.results)} passed under {report.policy_set}")
    if not report.ok:
        lines.append("changed decisions:")
        for r in report.changed():
            lines.append(f"  - {r.name}: {r.explanation}")
    return "\n".join(lines)


def to_json(report: SuiteReport) -> dict[str, Any]:
    body: dict[str, Any] = report.model_dump(mode="json")
    body["summary"] = {"passed": report.passed, "failed": report.failed, "ok": report.ok}
    return body


def to_junit(report: SuiteReport) -> str:
    """JUnit XML so CI systems can annotate failures without a plugin."""
    total = len(report.results)
    failures = report.failed
    duration = sum(r.duration_ms for r in report.results) / 1000
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name="{escape(report.suite)}" tests="{total}" failures="{failures}" '
        f'errors="0" time="{duration:.3f}" timestamp="{report.started_at.isoformat()}">',
        "  <properties>",
        f'    <property name="policy_set" value="{escape(report.policy_set)}"/>',
        "  </properties>",
    ]
    for r in report.results:
        out.append(
            f'  <testcase classname="{escape(report.suite)}" name="{escape(r.name)}" '
            f'time="{r.duration_ms / 1000:.3f}">'
        )
        if not r.passed:
            kind = "error" if r.error else "failure"
            out.append(
                f'    <{kind} message="{escape(r.explanation)}">{escape(r.explanation)}</{kind}>'
            )
        out.append("  </testcase>")
    out.append("</testsuite>")
    return "\n".join(out) + "\n"

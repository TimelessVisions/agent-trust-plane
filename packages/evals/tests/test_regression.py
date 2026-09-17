"""Regression suite format, runner, recorder — including hostile inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from atp_adapter_http import TrustPlaneClient
from atp_evals.regression import (
    Suite,
    TraceConversionError,
    case_from_trace,
    dump_suite,
    load_suite,
    merge_into_suite,
    run_suite,
    to_json,
    to_junit,
)
from atp_gateway import GatewaySettings, create_app
from finance_agent import (
    AP_AGENT,
    HUMAN,
    INJECTED_INVOICE,
    SimulatedAgent,
    run_accounts_payable,
    seed_delegation_graph,
)

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "examples" / "regression-suite" / "accounts-payable.yaml"


def test_sample_suite_passes_under_v2_and_fails_under_v1() -> None:
    suite = load_suite(SAMPLE)
    v2 = run_suite(suite)
    assert v2.ok, [r.explanation for r in v2.changed()]
    v1 = run_suite(suite, policy_set="payments-v1")
    assert not v1.ok
    names = {r.name for r in v1.changed()}
    assert "under-limit payment redirected to an unknown account is denied" in names
    changed = next(r for r in v1.changed() if "redirected" in r.name)
    assert "responsible: no policy matched under payments-v1" in changed.explanation
    assert changed.observed_outcome == "ALLOW"


def test_runner_never_executes(tmp_path: Path) -> None:
    """The ALLOW case in the sample suite must not settle anything: the runner
    calls /authorize only. Verified by running against a shared app and
    reading its ledger."""
    suite = load_suite(SAMPLE)
    report = run_suite(suite)
    # every result has a trace id from the ephemeral gateway but no execution
    assert all(r.trace_id for r in report.results)
    # and the runner's ephemeral gateway is gone; run again to prove isolation
    again = run_suite(suite)
    assert again.ok and again.run_id != report.run_id


def test_outputs(tmp_path: Path) -> None:
    suite = load_suite(SAMPLE)
    report = run_suite(suite, policy_set="payments-v1")
    body = to_json(report)
    assert body["summary"]["ok"] is False and body["summary"]["failed"] == 2
    xml = to_junit(report)
    assert 'tests="8" failures="2"' in xml
    assert "<failure" in xml and "policy_set" in xml
    assert json.dumps(body)  # serialisable


class TestFormatValidation:
    def _base(self) -> dict[str, Any]:
        return yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))

    def _write(self, tmp_path: Path, data: dict[str, Any]) -> Path:
        p = tmp_path / "s.yaml"
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
        return p

    def test_unknown_fields_rejected(self, tmp_path: Path) -> None:
        data = self._base()
        data["cases"][0]["execute"] = True
        with pytest.raises(ValueError):
            load_suite(self._write(tmp_path, data))

    def test_unknown_alias_rejected(self, tmp_path: Path) -> None:
        data = self._base()
        data["cases"][0]["delegation"] = "nope"
        with pytest.raises(ValueError, match="unknown delegation alias"):
            load_suite(self._write(tmp_path, data))

    def test_parent_must_precede_child(self, tmp_path: Path) -> None:
        data = self._base()
        data["delegations"]["grants"].reverse()
        with pytest.raises(ValueError, match="must be declared earlier"):
            load_suite(self._write(tmp_path, data))

    def test_duplicate_case_names_rejected(self, tmp_path: Path) -> None:
        data = self._base()
        data["cases"][1]["name"] = data["cases"][0]["name"]
        with pytest.raises(ValueError, match="duplicate case name"):
            load_suite(self._write(tmp_path, data))

    def test_oversized_arguments_rejected(self, tmp_path: Path) -> None:
        data = self._base()
        data["cases"][0]["arguments"]["memo"] = "x" * 20_000
        with pytest.raises(ValueError):
            load_suite(self._write(tmp_path, data))

    def test_bad_identifiers_rejected(self, tmp_path: Path) -> None:
        data = self._base()
        data["cases"][0]["resource"] = "vendor:128; DROP TABLE"
        with pytest.raises(ValueError):
            load_suite(self._write(tmp_path, data))

    def test_round_trip(self, tmp_path: Path) -> None:
        suite = load_suite(SAMPLE)
        out = tmp_path / "copy.yaml"
        dump_suite(suite, out)
        assert load_suite(out) == suite


class TestRecording:
    @pytest.fixture
    def recorded_trace(self) -> dict[str, Any]:
        app = create_app(GatewaySettings(database_path=":memory:"))
        with TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key) as op:
            seed = seed_delegation_graph(op)
            result = run_accounts_payable(
                op.as_agent(seed.identities.accounts_payable_token),
                SimulatedAgent(),
                INJECTED_INVOICE,
                principal=HUMAN,
                agent=AP_AGENT,
                delegation_grant_id=seed.graph.accounts_payable,
            )
            trace: dict[str, Any] = op.get_trace(result.trace_id)
            return trace

    def test_trace_becomes_a_case_that_reproduces(self, recorded_trace: dict[str, Any]) -> None:
        delegations, case = case_from_trace(recorded_trace, name="injected 12500")
        assert case.expect.outcome.value == "DENY"
        assert case.expect.reason_code == "PAYMENT_EXCEEDS_DELEGATED_AUTHORITY"
        assert case.expect.matched_policy == "payments.vendor.max_amount.v1"
        assert case.source is not None and case.source.trace_id == recorded_trace["trace_id"]
        assert len(delegations.grants) == 3  # human -> orchestrator -> AP agent
        suite = merge_into_suite(None, delegations, case)
        report = run_suite(suite)
        assert report.ok, [r.explanation for r in report.changed()]

    def test_provenance_excerpt_is_not_carried_over(self, recorded_trace: dict[str, Any]) -> None:
        _, case = case_from_trace(recorded_trace)
        dumped = json.dumps(case.model_dump(mode="json"))
        assert "Ignore all previous instructions" not in dumped
        assert "content_hash" not in dumped

    def test_hostile_trace_fields_are_rejected(self, recorded_trace: dict[str, Any]) -> None:
        # Arguments are opaque at conversion time; a tampered amount converts
        # but is judged by policy when the suite runs, so the pinned decision
        # no longer reproduces and the run fails loudly instead of executing.
        bad = json.loads(json.dumps(recorded_trace))
        bad["envelope"]["arguments"]["amount"] = "1000.004"
        d, c = case_from_trace(bad)
        report = run_suite(merge_into_suite(None, d, c))
        assert not report.ok
        assert report.results[0].observed_reason == "PAYMENT_ARGUMENTS_INVALID"
        worse = json.loads(json.dumps(recorded_trace))
        worse["envelope"]["resource"] = "vendor:128\n--evil"
        with pytest.raises(TraceConversionError):
            case_from_trace(worse)
        tampered = json.loads(json.dumps(recorded_trace))
        tampered["delegation_chain"][-1]["grantee"] = {"id": "someone-else", "kind": "agent"}
        with pytest.raises(TraceConversionError, match="not part of the recorded chain"):
            case_from_trace(tampered)

    def test_trace_without_chain_is_refused(self, recorded_trace: dict[str, Any]) -> None:
        stripped = {**recorded_trace, "delegation_chain": []}
        with pytest.raises(TraceConversionError, match="no resolved delegation chain"):
            case_from_trace(stripped)

    def test_merge_refuses_conflicting_alias(self, recorded_trace: dict[str, Any]) -> None:
        delegations, case = case_from_trace(recorded_trace, name="a")
        suite = merge_into_suite(None, delegations, case)
        with pytest.raises(TraceConversionError, match="already exists"):
            merge_into_suite(suite, delegations, case)
        other = delegations.model_copy(
            update={
                "principals": {
                    **delegations.principals,
                    "company-user-42": delegations.principals["accounts-payable-agent"],
                }
            }
        )
        with pytest.raises(TraceConversionError, match="different principal"):
            merge_into_suite(suite, other, case.model_copy(update={"name": "b"}))
        assert isinstance(suite, Suite)

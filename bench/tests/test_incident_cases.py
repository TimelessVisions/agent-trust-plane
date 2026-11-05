"""E2 MCPoison-class incident: a real local MCP server changes tools/list."""

from __future__ import annotations

from pathlib import Path

from atp_bench.incidents import load_incident_case, run_incident
from atp_bench.layers.atp_layer import AtpLayer
from atp_bench.layers.name_only_layer import NameOnlyLayer

CASE_ROOT = Path(__file__).resolve().parents[1] / "incidents" / "mcpoison"


def test_mcpoison_incident_real_server_and_atp_proxy() -> None:
    case = load_incident_case(CASE_ROOT / "case.yaml")
    name_only = run_incident(case, NameOnlyLayer())
    assert name_only.status == "PASS", name_only
    assert name_only.outcomes == ("ALLOWED", "ALLOWED"), name_only

    atp = run_incident(case, AtpLayer())
    assert atp.status == "PASS", atp
    assert atp.outcomes == ("ALLOWED", "DENIED"), atp


def test_mcpoison_companion_atp_regression_is_not_a_schema_pin() -> None:
    """atp test validates ordinary delegation, while proxy enforces the definition."""
    from atp_cli.main import main

    try:
        outcome = main(["test", str(CASE_ROOT / "atp-regression.yaml")])
    except SystemExit as exc:
        outcome = exc.code
    assert outcome in (None, 0), outcome


def test_tool_description_poisoning_scope_with_real_proxy() -> None:
    case = load_incident_case(CASE_ROOT.parent / "tool-description-poisoning" / "case.yaml")
    reference = run_incident(case, NameOnlyLayer())
    assert reference.status == "PASS", reference
    assert reference.outcomes == ("ALLOWED", "ALLOWED"), reference

    protected = run_incident(case, AtpLayer())
    assert protected.status == "PASS", protected
    assert protected.outcomes == ("ALLOWED", "DENIED"), protected


def test_tool_description_companion_scope_regression() -> None:
    from atp_cli.main import main

    suite = CASE_ROOT.parent / "tool-description-poisoning" / "atp-regression.yaml"
    try:
        exit_code = main(["test", str(suite)])
    except SystemExit as exc:
        exit_code = exc.code
    assert exit_code in (None, 0), exit_code


def test_pr_title_hijack_scope_with_real_proxy() -> None:
    case = load_incident_case(CASE_ROOT.parent / "pr-title-hijack" / "case.yaml")
    reference = run_incident(case, NameOnlyLayer())
    assert reference.status == "PASS", reference
    assert reference.outcomes == ("ALLOWED", "ALLOWED", "ALLOWED"), reference

    protected = run_incident(case, AtpLayer())
    assert protected.status == "PASS", protected
    assert protected.outcomes == ("ALLOWED", "ALLOWED", "DENIED"), protected


def test_pr_title_hijack_companion_regression() -> None:
    from atp_cli.main import main

    suite = CASE_ROOT.parent / "pr-title-hijack" / "atp-regression.yaml"
    try:
        exit_code = main(["test", str(suite)])
    except SystemExit as exc:
        exit_code = exc.code
    assert exit_code in (None, 0), exit_code

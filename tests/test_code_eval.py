"""Code-evaluation checks. These run real subprocesses (a few seconds in total)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from annoqa.cli import main
from annoqa.codeeval import build_code_report, check, ground_truth, load_code_items, load_code_labels, run_hidden_tests
from annoqa.sandbox import outputs_differ, run_cases

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "data" / "code" / "items.jsonl"
REFERENCE = ROOT / "data" / "code" / "labels" / "reference.jsonl"
SYNTHETIC = ROOT / "examples" / "synthetic" / "code-annotator-b.jsonl"

BUGGY_BY_TESTS = {"code-001", "code-002", "code-003", "code-005", "code-006", "code-007", "code-010"}


@pytest.fixture(scope="module")
def items():  # type: ignore[no-untyped-def]
    return load_code_items(ITEMS)


@pytest.fixture(scope="module")
def runs(items):  # type: ignore[no-untyped-def]
    return run_hidden_tests(items)


def test_every_reference_solution_passes_its_tests(items) -> None:  # type: ignore[no-untyped-def]
    for item in items.values():
        result = run_cases(item.reference, item.function, item.tests)
        assert result.ok, (item.id, result.error, result.failed)


def test_candidates_fail_exactly_where_planted(runs) -> None:  # type: ignore[no-untyped-def]
    assert {i for i, r in runs.items() if not r.ok} == BUGGY_BY_TESTS


def test_test_gap_is_real(items) -> None:  # type: ignore[no-untyped-def]
    chunk = items["code-008"]
    assert run_cases(chunk.candidate, chunk.function, chunk.tests).ok
    differ, how = outputs_differ(chunk.candidate, chunk.reference, chunk.function, [[1, 2], -1])
    assert differ and "raises ValueError" in how


def test_sandbox_reports_timeouts_crashes_and_load_errors() -> None:
    assert "timed out" in (
        run_cases("def f():\n    while True: pass\n", "f", [{"args": [], "expected": 1}], timeout=1).error or ""
    )
    assert "could not load" in (run_cases("def g(): pass\n", "f", [{"args": [], "expected": 1}]).error or "")
    assert run_cases("import os\ndef f():\n    os._exit(3)\n", "f", [{"args": [], "expected": 1}]).error


def test_reference_labels_are_fully_verified(items, runs) -> None:  # type: ignore[no-untyped-def]
    findings = check(load_code_labels(REFERENCE), items, runs)
    assert {f.code for f in findings} == {"V304"}  # every failing input confirmed, nothing else
    assert len(findings) == 8


def test_synthetic_mistakes_are_caught(items, runs) -> None:  # type: ignore[no-untyped-def]
    labels = load_code_labels(REFERENCE) + load_code_labels(SYNTHETIC)
    found = {(f.code, f.item_id) for f in check(labels, items, runs) if f.annotator == "synthetic-b"}
    assert ("V301", "code-005") in found  # missed bug the tests catch
    assert ("V306", "code-008") in found  # missed bug only an annotator's input exposes
    assert ("V303", "code-003") in found  # failing input that does not fail


def test_ground_truth_counts_confirmed_test_gaps(items, runs) -> None:  # type: ignore[no-untyped-def]
    findings = check(load_code_labels(REFERENCE), items, runs)
    truth = ground_truth(items, runs, findings)
    assert {i for i, v in truth.items() if v == "incorrect"} == BUGGY_BY_TESTS | {"code-008"}


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"verdict": "maybe"}, "E204"),
        ({"scores": {"correctness": 5}}, "E203"),
        ({"issues": [{"category": "vibes", "severity": "major", "description": "x"}]}, "E205"),
        ({"rationale": "Looks fine to me."}, "E206"),
        ({"failing_input": "[5, 5, 3]"}, "E207"),
        ({"verdict": "incorrect", "failing_input": None}, "V305"),
    ],
)
def test_schema_and_evidence_rules(change, code, items, runs, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    row = json.loads(REFERENCE.read_text(encoding="utf-8").splitlines()[3])  # code-004, a clean "correct" label
    row.update(change)
    path = tmp_path / "l.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert code in {f.code for f in check(load_code_labels(path), items, runs)}


def test_report_and_cli(tmp_path: Path, items) -> None:  # type: ignore[no-untyped-def]
    labels = load_code_labels(REFERENCE) + load_code_labels(SYNTHETIC)
    report = build_code_report(labels, items, gold="ref")
    assert "| synthetic-b | 10 | 80% | 2 | 0 | 5/6 |" in report
    assert "confirmed by an annotator's failing input" in report
    out = tmp_path / "r.md"
    assert main(["code-check", "--items", str(ITEMS), str(REFERENCE), "--out", str(out)]) == 0
    assert main(["code-check", "--items", str(ITEMS), str(tmp_path / "missing.jsonl")]) == 2

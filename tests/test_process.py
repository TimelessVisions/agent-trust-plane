from __future__ import annotations

import copy
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from annoqa.cli import main
from annoqa.process import (
    CalcError,
    build_step_report,
    check,
    evaluate,
    load_solutions,
    load_step_hidden,
    load_step_labels,
)

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / "data" / "process"
ITEMS, HIDDEN, REFERENCE = P / "items.jsonl", P / "hidden.jsonl", P / "labels" / "reference.jsonl"
SYNTHETIC = ROOT / "examples" / "synthetic" / "process-annotator-b.jsonl"


@pytest.fixture(scope="module")
def sols():  # type: ignore[no-untyped-def]
    return load_solutions(ITEMS)


def test_exact_arithmetic() -> None:
    assert evaluate("3*1.75") == Fraction(21, 4)
    assert evaluate("0.1+0.2") == Fraction(3, 10)  # no floating-point error
    assert evaluate("-(2-5)/3") == 1
    for bad in ("__import__('os')", "2**10", "1/0", "x+1", "1+"):
        with pytest.raises(CalcError):
            evaluate(bad)


def test_ground_truth_is_as_designed(sols) -> None:  # type: ignore[no-untyped-def]
    hidden = load_step_hidden(HIDDEN)
    assert {s for s, sol in sols.items() if sol.final_correct} == {"ps-01", "ps-03", "ps-04", "ps-07", "ps-08", "ps-10"}
    assert {s: sol.first_arithmetic_error for s, sol in sols.items() if sol.first_arithmetic_error} == {
        "ps-02": 2,
        "ps-03": 1,
    }
    # The arithmetic-detectable first errors agree with the hidden ground truth.
    for sid, sol in sols.items():
        if sol.first_arithmetic_error:
            assert hidden[sid]["first_error_step"] == sol.first_arithmetic_error
    # Exactly one "lucky" solution: right answer, wrong process.
    lucky = [s for s, sol in sols.items() if sol.final_correct and hidden[s]["first_error_step"] is not None]
    assert lucky == ["ps-03"]


def test_reference_labels_are_clean(sols) -> None:  # type: ignore[no-untyped-def]
    assert check(load_step_labels(REFERENCE), sols, load_step_hidden(HIDDEN)) == []


def test_synthetic_mistakes_are_caught(sols) -> None:  # type: ignore[no-untyped-def]
    found = {(f.code, f.solution_id) for f in check(load_step_labels(SYNTHETIC), sols, load_step_hidden(HIDDEN))}
    assert found == {("V611", "ps-03"), ("V614", "ps-03"), ("V614", "ps-05"), ("V615", "ps-09")}


def _row(sid: str) -> dict[str, Any]:
    for line in REFERENCE.read_text(encoding="utf-8").splitlines():
        if json.loads(line)["solution_id"] == sid:
            return copy.deepcopy(json.loads(line))
    raise KeyError(sid)


@pytest.mark.parametrize(
    ("sid", "change", "code"),
    [
        ("ps-02", {"step_labels": ["good", "wrong"]}, "E603"),
        ("ps-02", {"first_error_step": 3}, "E604"),
        ("ps-02", {"error_type": None}, "E605"),
        ("ps-01", {"error_type": "logic"}, "E605"),
        ("ps-02", {"rationale": "step two is wrong"}, "E606"),
        ("ps-02", {"final_answer_correct": "no"}, "E607"),
        ("ps-02", {"step_labels": ["good", "bad", "good"]}, "W621"),
        ("ps-01", {"step_labels": ["good", "good"]}, "W622"),
        ("ps-02", {"step_labels": ["good", "good", "bad"], "first_error_step": 3}, "V611"),
        ("ps-05", {"error_type": "arithmetic"}, "V612"),
        ("ps-03", {"final_answer_correct": False}, "V613"),
        ("ps-06", {"step_labels": ["good", "good", "neutral"], "first_error_step": None, "error_type": None}, "V616"),
    ],
)
def test_each_rule_fires(sid: str, change: dict[str, Any], code: str, sols, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    row = _row(sid)
    row.update(change)
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert code in {f.code for f in check(load_step_labels(p), sols, load_step_hidden(HIDDEN))}


def test_report_and_cli(sols, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    labels = load_step_labels(REFERENCE) + load_step_labels(SYNTHETIC)
    report = build_step_report(labels, sols, load_step_hidden(HIDDEN))
    assert "**lucky: right answer, wrong process**" in report
    assert "| synthetic-b | 11 | 9/11 | 3/4 | 11/11 | 2 |" in report
    out = tmp_path / "packet.md"
    assert main(["step-show", "--items", str(ITEMS), "--out", str(out)]) == 0
    assert "`3*1.75 = 5.75`" in out.read_text(encoding="utf-8")
    assert main(["step-check", "--items", str(ITEMS), "--hidden", str(HIDDEN), str(REFERENCE)]) == 0
    assert main(["step-check", "--items", str(tmp_path / "none.jsonl"), str(REFERENCE)]) == 2

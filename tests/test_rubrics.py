from __future__ import annotations

import math
from pathlib import Path

import pytest

from annoqa.cli import main
from annoqa.rubrics import (
    Criterion,
    Rubric,
    auto_check,
    build_rubric_report,
    evaluate,
    grader_index,
    kendall_tau,
    lint,
    load_grades,
    load_rubric_tasks,
    load_rubrics,
)

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "data" / "rubrics" / "tasks.jsonl"
RUBRICS = ROOT / "data" / "rubrics" / "rubrics.jsonl"
REF = ROOT / "data" / "rubrics" / "grades" / "reference.jsonl"
SYN = ROOT / "examples" / "synthetic" / "rubric-grader-b.jsonl"


@pytest.fixture(scope="module")
def data():  # type: ignore[no-untyped-def]
    return load_rubric_tasks(TASKS), load_rubrics(RUBRICS), grader_index(load_grades(REF))


def test_kendall_tau() -> None:
    assert kendall_tau([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert kendall_tau([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert math.isnan(kendall_tau([1, 1, 1], [1, 2, 3]))


def test_every_v1_rubric_is_hackable_and_every_v2_is_not(data) -> None:  # type: ignore[no-untyped-def]
    tasks, rubrics, idx = data
    for rb in rubrics:
        res = evaluate(rb, tasks[rb.task_id], idx[("ref", rb.task_id, rb.version)])
        if rb.version == "v1":
            assert res.hack_gap <= 0, rb.task_id
            assert res.tau < 0.5, rb.task_id
        else:
            assert res.hack_gap > 1.0, rb.task_id
            assert res.tau == pytest.approx(1.0), rb.task_id


def test_v2_rubrics_lint_clean_and_v1_do_not(data) -> None:  # type: ignore[no-untyped-def]
    _tasks, rubrics, _idx = data
    for rb in rubrics:
        codes = {f.code for f in lint(rb)}
        if rb.version == "v2":
            assert codes == set(), (rb.task_id, codes)
        else:
            assert {"L501", "L502", "L503", "L504"} <= codes, (rb.task_id, codes)


def _rb(*crits: Criterion) -> Rubric:
    return Rubric("t", "x", crits)


@pytest.mark.parametrize(
    ("crit", "code"),
    [
        (Criterion("a", "Explains it well.", 2, "judgment", None), "L501"),
        (Criterion("a", "Names the cause and the fix.", 2, "judgment", None), "L502"),
        (Criterion("a", "Keeps the reply short.", 2, "judgment", None), "L505"),
        (Criterion("a", "At most 50 words.", 2, "verifiable", {"max_words": "50"}), "L506"),
        (Criterion("a", "Invents a policy.", -2, "judgment", None), "L509"),
        (Criterion("a", "Bad.", 0, "judgment", None), "L500"),
    ],
)
def test_lint_rules(crit: Criterion, code: str) -> None:
    filler = [Criterion(f"f{i}", f"States fact number {i} from the source.", i + 1, "judgment", None) for i in range(3)]
    assert code in {f.code for f in lint(_rb(crit, *filler))}


def test_lint_overlap_and_parentheses() -> None:
    a = Criterion("a", "Asks the customer for a photo of the damage.", 3, "judgment", None)
    b = Criterion("b", "Asks the customer for a photo showing the damage.", 1, "judgment", None)
    assert "L507" in {f.code for f in lint(_rb(a, b))}
    # "and" inside parentheses is an example list, not a compound criterion
    c = Criterion("c", "Names a limitation (hashing and ordering).", 1, "judgment", None)
    assert "L502" not in {f.code for f in lint(_rb(c))}


def test_auto_checks() -> None:
    assert auto_check({"includes_any": ["Photo"]}, "send a photo please")
    assert not auto_check({"max_words": 3}, "one two three four")
    assert auto_check({"regex": r"#\d{4}"}, "order #4471")


def test_report_and_cli(data, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    tasks, rubrics, _ = data
    report = build_rubric_report(tasks, rubrics, load_grades(REF) + load_grades(SYN))
    assert "| rb-refund | v1 |" in report and "**yes**" in report
    out = tmp_path / "r.md"
    assert main(["rubric-eval", "--tasks", str(TASKS), "--rubrics", str(RUBRICS), str(REF), "--out", str(out)]) == 0
    assert main(["rubric-eval", "--tasks", str(tmp_path / "nope.jsonl"), "--rubrics", str(RUBRICS)]) == 2

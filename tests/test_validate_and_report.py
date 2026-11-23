from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from annoqa.cli import main
from annoqa.report import build_report, find_disagreements, index
from annoqa.schema import Label, load_items, load_labels
from annoqa.validate import validate

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "data" / "items.jsonl"
REFERENCE = ROOT / "data" / "labels" / "reference.jsonl"
SYNTHETIC = ROOT / "examples" / "synthetic" / "annotator-b.jsonl"

GOOD: dict[str, Any] = {
    "item_id": "it-005",
    "annotator": "tester",
    "preference": "A",
    "scores": {
        "A": {"instruction_following": 5, "helpfulness": 5, "honesty": 5, "harmlessness": 5},
        "B": {"instruction_following": 4, "helpfulness": 1, "honesty": 1, "harmlessness": 5},
    },
    "flags": {"A": [], "B": ["factual_error"]},
    "rationale": (
        "A is correct: 40 x 0.75 = 30 then 30 x 1.10 = 33. B nets the percentages and gets $34, which is wrong."
    ),
}


def _codes(row: dict[str, Any], tmp_path: Path, extra: list[dict[str, Any]] | None = None) -> set[str]:
    path = tmp_path / "labels.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in [row, *(extra or [])]), encoding="utf-8")
    return {f.code for f in validate(load_labels(path), load_items(ITEMS))}


def _with(**changes: Any) -> dict[str, Any]:
    row = copy.deepcopy(GOOD)
    for dotted, value in changes.items():
        target = row
        *parents, last = dotted.split("__")
        for p in parents:
            target = target[p]
        target[last] = value
    return row


def test_reference_labels_are_clean() -> None:
    assert validate(load_labels(REFERENCE), load_items(ITEMS)) == []


def test_good_label_is_clean(tmp_path: Path) -> None:
    assert _codes(GOOD, tmp_path) == set()


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"item_id": "it-999"}, "E001"),
        ({"scores__A__honesty": 6}, "E003"),
        ({"scores__B__helpfulness": "3"}, "E003"),
        ({"scores__A__harmlessness": True}, "E003"),
        ({"preference": "a"}, "E004"),
        ({"flags__B": ["made_up_flag"]}, "E005"),
        ({"rationale": "A is right."}, "E006"),
        ({"annotator": " "}, "E007"),
        ({"preference": "B"}, "W101"),
        ({"flags__B": ["factual_error"], "scores__B__honesty": 5}, "W103"),
        ({"flags__B": ["privacy_risk"]}, "W104"),
        ({"flags__A": ["over_refusal"]}, "W105"),
    ],
)
def test_each_rule_fires(changes: dict[str, Any], code: str, tmp_path: Path) -> None:
    assert code in _codes(_with(**changes), tmp_path)


def test_duplicate_label_is_rejected(tmp_path: Path) -> None:
    assert "E002" in _codes(GOOD, tmp_path, extra=[GOOD])


def test_tie_with_far_apart_totals_warns(tmp_path: Path) -> None:
    assert "W102" in _codes(_with(preference="tie", rationale="Tie: " + GOOD["rationale"]), tmp_path)


def test_rationale_must_name_preferred_side(tmp_path: Path) -> None:
    text = "the first one is correct because it applies the discount and then the tax, giving thirty three dollars"
    assert "W106" in _codes(_with(rationale=text), tmp_path)
    # The article "a" must not count as naming response A.
    assert "W106" in _codes(_with(rationale="it is " + text + " which is a good answer"), tmp_path)


def test_synthetic_annotator_is_flagged_where_planted() -> None:
    findings = validate(load_labels(SYNTHETIC), load_items(ITEMS))
    assert {(f.code, f.item_id) for f in findings} == {("E006", "it-006"), ("W101", "it-012")}


def test_disagreements_rank_opposite_preferences_first() -> None:
    labels: list[Label] = load_labels(REFERENCE) + load_labels(SYNTHETIC)
    found = find_disagreements(index(labels))
    assert found[0].item_id == "it-012"
    assert "opposite preferences (A vs B)" in found[0].reasons
    assert {d.item_id for d in found} >= {"it-008", "it-011", "it-012"}


def test_report_excludes_invalid_labels_and_scores_gold() -> None:
    labels = load_labels(REFERENCE) + load_labels(SYNTHETIC)
    report = build_report(labels, load_items(ITEMS), gold="ref")
    assert "usable: 23" in report
    assert "## Accuracy against gold (`ref`)" in report
    assert "| synthetic-b | 11 | 82% |" in report
    assert "### it-012 (severity 3)" in report


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "--items", str(ITEMS), str(REFERENCE)]) == 0
    assert main(["validate", "--items", str(ITEMS), str(SYNTHETIC)]) == 1
    assert main(["validate", "--items", str(ITEMS), str(tmp_path / "missing.jsonl")]) == 2
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    assert main(["validate", "--items", str(ITEMS), str(bad)]) == 2
    out = tmp_path / "r.md"
    assert main(["report", "--items", str(ITEMS), str(REFERENCE), str(SYNTHETIC), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Annotation agreement report")
    capsys.readouterr()

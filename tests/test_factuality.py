from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from annoqa.cli import main
from annoqa.factuality import (
    align,
    build_fact_report,
    check,
    coverage,
    load_fact_items,
    load_fact_labels,
    normalize,
    numbers,
    span_of,
)

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "data" / "facts" / "items.jsonl"
REFERENCE = ROOT / "data" / "facts" / "labels" / "reference.jsonl"
SYNTHETIC = ROOT / "examples" / "synthetic" / "fact-annotator-b.jsonl"


@pytest.fixture(scope="module")
def items():  # type: ignore[no-untyped-def]
    return load_fact_items(ITEMS)


def _ref_row(item_id: str) -> dict[str, Any]:
    for line in REFERENCE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["item_id"] == item_id:
            return row
    raise KeyError(item_id)


def _codes(row: dict[str, Any], items, tmp_path: Path) -> set[str]:  # type: ignore[no-untyped-def]
    path = tmp_path / "l.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return {f.code for f in check(load_fact_labels(path), items)}


def test_reference_labels_are_clean(items) -> None:  # type: ignore[no-untyped-def]
    assert check(load_fact_labels(REFERENCE), items) == []


def test_every_reference_quote_is_verbatim_in_its_source(items) -> None:  # type: ignore[no-untyped-def]
    for lb in load_fact_labels(REFERENCE):
        for c in lb.claims:
            assert span_of(c["text"], items[lb.item_id].response), c["text"]
            for ev in c["evidence"]:
                assert normalize(ev["quote"]) in normalize(items[lb.item_id].sources[ev["source"]])


def test_planted_errors_are_all_contradicted_in_reference() -> None:
    contradicted = {
        (lb.item_id, c["text"])
        for lb in load_fact_labels(REFERENCE)
        for c in lb.claims
        if c["verdict"] == "contradicted"
    }
    assert len(contradicted) == 7
    assert ("fact-006", "beating its 50% target") in contradicted


def _mutate(item_id: str, claim: int, **fields: Any) -> dict[str, Any]:
    row = copy.deepcopy(_ref_row(item_id))
    row["claims"][claim].update(fields)
    return row


@pytest.mark.parametrize(
    ("row", "code"),
    [
        (_mutate("fact-001", 0, text="voted 6-3 to delay the bike lane"), "E303"),
        (_mutate("fact-001", 0, verdict="true"), "E304"),
        (_mutate("fact-001", 1, evidence=[]), "E305"),
        (_mutate("fact-001", 0, evidence=[{"source": "S9", "quote": "voted 5-4"}]), "E306"),
        (_mutate("fact-001", 0, evidence=[{"source": "S1", "quote": "the council agreed to wait a year"}]), "E307"),
        (_mutate("fact-001", 1, correction=""), "E308"),
        (_mutate("fact-001", 0, evidence=[{"source": "S1", "quote": "Main Street bike lane"}]), "W312"),
        (_mutate("fact-002", 3, evidence=[{"source": "S1", "quote": "Parking is limited to three hours."}]), "W314"),
    ],
)
def test_each_rule_fires(row: dict[str, Any], code: str, items, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert code in _codes(row, items, tmp_path)


def test_skipped_sentences_and_duplicates_warn(items, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    row = copy.deepcopy(_ref_row("fact-003"))
    row["claims"] = row["claims"][:2]
    assert "W311" in _codes(row, items, tmp_path)
    row = copy.deepcopy(_ref_row("fact-004"))
    row["claims"].append(copy.deepcopy(row["claims"][0]))
    assert "W313" in _codes(row, items, tmp_path)


def test_quote_normalization_and_numbers() -> None:
    assert normalize("it’s  the\n“new”–page") == 'it\'s the "new"-page'
    assert numbers("from 500 to 1,000 rows, 3.11") == {"500", "1000", "3.11"}


def test_coverage_counts_sentences() -> None:
    text = "One fact. Two fact. Three fact."
    cov, missed = coverage([(0, 9)], text)
    assert cov == pytest.approx(1 / 3)
    assert missed == ["Two fact.", "Three fact."]


def test_synthetic_annotator_mistakes_surface(items) -> None:  # type: ignore[no-untyped-def]
    labels = load_fact_labels(REFERENCE) + load_fact_labels(SYNTHETIC)
    errors = {(f.code, f.item_id) for f in check(labels, items) if f.annotator == "synthetic-b"}
    assert errors == {("E307", "fact-004")}  # the paraphrased quote
    aligned = {(c.item_id, c.text): c.verdicts for c in align(labels, items)}
    assert aligned[("fact-002", "It has 25 free parking spaces.")]["synthetic-b"] == "supported"
    assert aligned[("fact-006", "beating its 50% target")]["synthetic-b"] == "(not extracted)"


def test_report_and_cli(items, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    labels = load_fact_labels(REFERENCE) + load_fact_labels(SYNTHETIC)
    report = build_fact_report(labels, items, gold="ref")
    assert "| synthetic-b | 21/22 | 90% | 4/6 |" in report
    assert "| fact-006 | beating its 50% target | contradicted | (not extracted) |" in report
    out = tmp_path / "r.md"
    assert main(["fact-check", "--items", str(ITEMS), str(REFERENCE), "--out", str(out)]) == 0
    assert main(["fact-check", "--items", str(ITEMS), str(SYNTHETIC)]) == 1
    assert main(["fact-check", "--items", str(ITEMS), str(tmp_path / "nope.jsonl")]) == 2

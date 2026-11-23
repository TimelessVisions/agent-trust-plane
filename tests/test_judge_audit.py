from __future__ import annotations

import sys
from pathlib import Path

import pytest

from annoqa.cli import main
from annoqa.judgeaudit import (
    AUTHORITY,
    FILLER,
    audit,
    build_judge_report,
    command_judge,
    gold_from_labels,
    load_run,
    make_probes,
    parse_verdict,
    reference_judges,
    run_judge,
    save_run,
    to_ab,
)
from annoqa.schema import load_items, load_labels

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "data" / "items.jsonl"
GOLD = ROOT / "data" / "labels" / "reference.jsonl"


@pytest.fixture(scope="module")
def setup():  # type: ignore[no-untyped-def]
    items = load_items(ITEMS)
    gold = gold_from_labels(load_labels(GOLD), "ref")
    return items, gold, make_probes(items, gold)


def test_probes_are_built_for_every_item(setup) -> None:  # type: ignore[no-untyped-def]
    items, gold, probes = setup
    decisive = sum(g in ("A", "B") for g in gold.values())
    assert len(probes) == 2 * len(gold) + 2 * decisive
    for p in probes:
        if p.kind == "padded":
            worse = p.r2 if gold[p.item_id] == "A" else p.r1
            assert worse.endswith(FILLER)
        if p.kind == "assertive":
            worse = p.r2 if gold[p.item_id] == "A" else p.r1
            assert worse.startswith(AUTHORITY)


def test_verdict_parsing_and_mapping(setup) -> None:  # type: ignore[no-untyped-def]
    assert parse_verdict("Reason. [[2]]") == "2"
    assert parse_verdict("first [[1]] then final [[TIE]]") == "tie"
    assert parse_verdict("no verdict") is None
    _items, _gold, probes = setup
    swapped = next(p for p in probes if p.kind == "swapped")
    assert to_ab(swapped, "1") == "B" and to_ab(swapped, "2") == "A"


def _audit(name: str, setup):  # type: ignore[no-untyped-def]
    _items, gold, probes = setup
    return audit(name, run_judge(reference_judges(gold)[name], probes), gold)


def test_oracle_passes_everything(setup) -> None:  # type: ignore[no-untyped-def]
    r = _audit("oracle", setup)
    assert all(r.passes().values())
    assert r.accuracy == 1.0 and r.position_consistency == 1.0 and r.verbosity_flip == 0 and r.authority_flip == 0


def test_first_position_bias_is_detected(setup) -> None:  # type: ignore[no-untyped-def]
    r = _audit("first-position", setup)
    assert r.position_consistency == 0.0 and r.first_slot_rate == 1.0
    assert not r.passes()["position_consistency"]


def test_verbosity_bias_is_detected(setup) -> None:  # type: ignore[no-untyped-def]
    r = _audit("longer", setup)
    assert r.verbosity_flip == 1.0
    assert not r.passes()["verbosity_flip"]


def test_authority_bias_is_detected_and_isolated(setup) -> None:  # type: ignore[no-untyped-def]
    r = _audit("authority-swayed", setup)
    assert r.authority_flip == 1.0
    assert r.passes() == {
        "accuracy": True,
        "position_consistency": True,
        "verbosity_flip": True,
        "authority_flip": False,
    }


def test_command_judge_runs_a_real_process(setup, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    script = tmp_path / "judge.py"
    script.write_text("import sys\nsys.stdin.read()\nprint('Response 2 is better. [[2]]')\n", encoding="utf-8")
    _items, gold, probes = setup
    raw = run_judge(command_judge(f"{sys.executable} {script}"), probes)
    r = audit("always-2", raw, gold)
    assert r.first_slot_rate == 0.0 and r.position_consistency == 0.0
    # record and re-score without re-running
    path = tmp_path / "run.jsonl"
    save_run(path, "always-2", raw)
    name, again = load_run(path)
    assert name == "always-2" and again == raw


def test_command_judge_without_verdict_fails_loudly(setup, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    script = tmp_path / "mute.py"
    script.write_text("print('I cannot decide')\n", encoding="utf-8")
    _items, _gold, probes = setup
    with pytest.raises(RuntimeError, match="no verdict"):
        run_judge(command_judge(f"{sys.executable} {script}"), probes[:1])


def test_report_and_cli(setup, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    items, gold, _ = setup
    report = build_judge_report([_audit("oracle", setup), _audit("first-position", setup)], items, gold)
    assert "| oracle | 100% |" in report and "FAIL: accuracy, position_consistency" in report
    out = tmp_path / "r.md"
    rec = tmp_path / "runs"
    args = [
        "judge-audit",
        "--items",
        str(ITEMS),
        "--gold",
        str(GOLD),
        "--judge",
        "longer",
        "--record",
        str(rec),
        "--out",
        str(out),
    ]
    assert main(args) == 0
    assert (rec / "longer.jsonl").exists()
    assert main(["judge-audit", "--items", str(ITEMS), "--gold", str(GOLD), "--run", str(rec / "longer.jsonl")]) == 0
    assert main(["judge-audit", "--items", str(ITEMS), "--gold", str(GOLD), "--judge", "nope"]) == 2
    assert main(["judge-audit", "--items", str(ITEMS), "--gold", str(GOLD), "--gold-annotator", "nobody"]) == 2

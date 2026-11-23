"""Code-evaluation annotation: schema, checks verified by execution, and report.

An annotator grades one AI-written solution per item (see
``guidelines/code-evaluation-v1.md``). Their verdict is then checked against
hidden tests, and any failing input they supply is run against a trusted
reference implementation to confirm it really exposes a bug.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Literal, TypeGuard

from annoqa.agreement import cohen_kappa, interpret_alpha, interpret_kappa, krippendorff_alpha, percent_agreement
from annoqa.sandbox import RunResult, outputs_differ, run_cases
from annoqa.schema import LoadError, read_jsonl

CODE_DIMENSIONS: tuple[str, ...] = (
    "correctness",
    "edge_cases",
    "efficiency",
    "security",
    "readability",
    "explanation_accuracy",
)
VERDICTS: tuple[str, ...] = ("correct", "incorrect")
ISSUE_CATEGORIES: tuple[str, ...] = (
    "logic_bug",
    "edge_case",
    "spec_mismatch",
    "security",
    "performance",
    "error_handling",
    "explanation_mismatch",
    "style",
)
SEVERITIES: tuple[str, ...] = ("blocker", "major", "minor")
MIN_RATIONALE_WORDS = 15

Kind = Literal["error", "mismatch", "warning", "confirmed"]

RULES: dict[str, tuple[Kind, str]] = {
    "E201": ("error", "item_id does not match any code item"),
    "E202": ("error", "same annotator labelled the same item twice"),
    "E203": ("error", "a dimension score is missing or not an integer 1-5"),
    "E204": ("error", "verdict must be 'correct' or 'incorrect'"),
    "E205": ("error", "an issue has an unknown category or severity, or no description"),
    "E206": ("error", f"rationale is shorter than {MIN_RATIONALE_WORDS} words"),
    "E207": ("error", "failing_input must be a list of call arguments"),
    "E208": ("error", "annotator id is empty"),
    "V301": ("mismatch", "verdict 'correct', but hidden tests fail"),
    "V302": ("mismatch", "verdict 'incorrect', but hidden tests pass and no failing input confirms a bug"),
    "V303": ("mismatch", "the failing input does not expose a bug: candidate and reference agree"),
    "V304": ("confirmed", "failing input confirmed: candidate and reference disagree"),
    "V306": ("mismatch", "verdict 'correct', but another annotator's confirmed failing input exposes a bug"),
    "V305": ("warning", "verdict 'incorrect' without a failing_input (the guidelines require one)"),
    "W401": ("warning", "verdict 'incorrect', yet correctness is 4-5"),
    "W402": ("warning", "verdict 'correct', yet correctness is 1-2"),
    "W403": ("warning", "a security issue is listed, yet security is 4-5"),
    "W404": ("warning", "a blocker issue is listed, yet the verdict is 'correct'"),
}


@dataclass(frozen=True)
class CodeItem:
    id: str
    function: str
    task: str
    candidate: str
    reference: str
    tests: list[dict[str, Any]]
    explanation: str = ""


@dataclass
class CodeLabel:
    item_id: str
    annotator: str
    verdict: Any
    scores: dict[str, Any] = field(default_factory=dict)
    issues: list[Any] = field(default_factory=list)
    failing_input: Any = None
    rationale: str = ""
    line: int = 0
    source: str = ""


@dataclass(frozen=True)
class CodeFinding:
    code: str
    item_id: str
    annotator: str
    message: str
    where: str

    @property
    def kind(self) -> Kind:
        return RULES[self.code][0]


def load_code_items(path: Path) -> dict[str, CodeItem]:
    items: dict[str, CodeItem] = {}
    for n, obj in read_jsonl(path):
        try:
            item = CodeItem(
                id=str(obj["id"]),
                function=str(obj["function"]),
                task=str(obj["task"]),
                candidate=str(obj["candidate"]),
                reference=str(obj["reference"]),
                tests=list(obj["tests"]),
                explanation=str(obj.get("explanation", "")),
            )
        except KeyError as exc:
            raise LoadError(f"{path}:{n}: code item is missing {exc.args[0]!r}") from exc
        if item.id in items:
            raise LoadError(f"{path}:{n}: duplicate item id {item.id!r}")
        items[item.id] = item
    return items


def load_code_labels(path: Path) -> list[CodeLabel]:
    out: list[CodeLabel] = []
    for n, obj in read_jsonl(path):
        scores, issues = obj.get("scores"), obj.get("issues")
        out.append(
            CodeLabel(
                item_id=str(obj.get("item_id", "")),
                annotator=str(obj.get("annotator", "")),
                verdict=obj.get("verdict"),
                scores=scores if isinstance(scores, dict) else {},
                issues=issues if isinstance(issues, list) else [],
                failing_input=obj.get("failing_input"),
                rationale=str(obj.get("rationale", "")),
                line=n,
                source=str(path),
            )
        )
    return out


def run_hidden_tests(items: dict[str, CodeItem]) -> dict[str, RunResult]:
    return {item.id: run_cases(item.candidate, item.function, item.tests) for item in items.values()}


def check(
    labels: list[CodeLabel],
    items: dict[str, CodeItem],
    test_runs: dict[str, RunResult] | None = None,
) -> list[CodeFinding]:
    runs = test_runs if test_runs is not None else run_hidden_tests(items)
    findings: list[CodeFinding] = []
    seen: set[tuple[str, str]] = set()
    for lb in labels:

        def add(code: str, detail: str = "", lb: CodeLabel = lb) -> None:
            msg = RULES[code][1] + (f": {detail}" if detail else "")
            where = f"{lb.source}:{lb.line}" if lb.source else f"line {lb.line}"
            findings.append(CodeFinding(code, lb.item_id, lb.annotator, msg, where))

        if not lb.annotator.strip():
            add("E208")
        item = items.get(lb.item_id)
        if item is None:
            add("E201", repr(lb.item_id))
        if (lb.item_id, lb.annotator) in seen:
            add("E202")
        seen.add((lb.item_id, lb.annotator))
        bad = [d for d in CODE_DIMENSIONS if not _score(lb.scores.get(d))]
        if bad:
            add("E203", ", ".join(bad))
        if lb.verdict not in VERDICTS:
            add("E204", repr(lb.verdict))
        for i, issue in enumerate(lb.issues):
            if (
                not isinstance(issue, dict)
                or issue.get("category") not in ISSUE_CATEGORIES
                or issue.get("severity") not in SEVERITIES
                or not str(issue.get("description", "")).strip()
            ):
                add("E205", f"issue #{i + 1}")
        if len(lb.rationale.split()) < MIN_RATIONALE_WORDS:
            add("E206", f"{len(lb.rationale.split())} word(s)")
        if lb.failing_input is not None and not isinstance(lb.failing_input, list):
            add("E207")

        issue_dicts = [i for i in lb.issues if isinstance(i, dict)]
        correctness = lb.scores.get("correctness")
        if lb.verdict == "incorrect" and _score(correctness) and correctness >= 4:
            add("W401")
        if lb.verdict == "correct" and _score(correctness) and correctness <= 2:
            add("W402")
        security = lb.scores.get("security")
        if any(i.get("category") == "security" for i in issue_dicts) and _score(security) and security >= 4:
            add("W403")
        if lb.verdict == "correct" and any(i.get("severity") == "blocker" for i in issue_dicts):
            add("W404")

        if item is None or lb.verdict not in VERDICTS:
            continue
        run = runs[item.id]
        confirmed = False
        if isinstance(lb.failing_input, list):
            differ, how = outputs_differ(item.candidate, item.reference, item.function, lb.failing_input)
            args = json.dumps(lb.failing_input)
            if differ:
                confirmed = True
                add("V304", f"{args}: {how}")
            else:
                add("V303", f"{args}: {how}")
        if lb.verdict == "correct" and not run.ok:
            add("V301", _first_failure(run))
        if lb.verdict == "incorrect":
            if lb.failing_input is None:
                add("V305")
            if run.ok and not confirmed:
                add("V302")
    # Second pass: a confirmed failing input from anyone makes "correct" on that item a missed bug.
    confirmed_by: dict[str, CodeFinding] = {}
    for f in findings:
        if f.code == "V304":
            confirmed_by.setdefault(f.item_id, f)
    for lb in labels:
        item = items.get(lb.item_id)
        if item is None or lb.verdict != "correct" or lb.item_id not in confirmed_by:
            continue
        if not runs[item.id].ok:
            continue  # already reported as V301
        src = confirmed_by[lb.item_id]
        where = f"{lb.source}:{lb.line}" if lb.source else f"line {lb.line}"
        msg = RULES["V306"][1] + f": from {src.annotator}, {src.message.split(': ', 1)[1]}"
        findings.append(CodeFinding("V306", lb.item_id, lb.annotator, msg, where))
    return findings


def _score(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 5


def _first_failure(run: RunResult) -> str:
    if run.error:
        return run.error
    f = run.failed[0]
    return f"{json.dumps(f.args)} -> {f.detail}"


def ground_truth(items: dict[str, CodeItem], runs: dict[str, RunResult], findings: list[CodeFinding]) -> dict[str, str]:
    """An item is 'incorrect' if hidden tests fail or any annotator's failing input is confirmed."""
    confirmed = {f.item_id for f in findings if f.code == "V304"}
    return {i: ("incorrect" if (not runs[i].ok or i in confirmed) else "correct") for i in items}


def build_code_report(labels: list[CodeLabel], items: dict[str, CodeItem], *, gold: str | None = None) -> str:
    runs = run_hidden_tests(items)
    findings = check(labels, items, runs)
    errors = {(f.item_id, f.annotator) for f in findings if f.kind == "error"}
    good = [lb for lb in labels if (lb.item_id, lb.annotator) not in errors]
    truth = ground_truth(items, runs, findings)
    annotators = sorted({lb.annotator for lb in good})
    by_item: dict[str, dict[str, CodeLabel]] = {}
    for lb in good:
        by_item.setdefault(lb.item_id, {})[lb.annotator] = lb

    lines = ["# Code-evaluation report", ""]
    lines += [
        f"- Code items: {len(items)}; labels read: {len(labels)}; usable: {len(good)}",
        f"- Annotators: {', '.join(annotators) or 'none'}",
        "",
        "## Hidden test results (ground truth)",
        "",
        "| Item | Function | Tests passed | Verdict from tests | First failure |",
        "|---|---|---|---|---|",
    ]
    for item_id, item in items.items():
        run = runs[item_id]
        passed = "error" if run.error else f"{sum(c.passed for c in run.cases)}/{len(run.cases)}"
        first = "-" if run.ok else _cell(_first_failure(run))
        note = truth[item_id] + (
            " (confirmed by an annotator's failing input)" if run.ok and truth[item_id] == "incorrect" else ""
        )
        lines.append(f"| {item_id} | `{item.function}` | {passed} | {note} | {first} |")
    lines.append("")

    lines += [
        "## Annotator accuracy",
        "",
        "| Annotator | n | Verdict accuracy | Missed bugs | False alarms | Failing inputs confirmed |",
        "|---|---|---|---|---|---|",
    ]
    for ann in annotators:
        mine = [lb for lb in good if lb.annotator == ann]
        right = sum(lb.verdict == truth[lb.item_id] for lb in mine)
        missed = sum(lb.verdict == "correct" and truth[lb.item_id] == "incorrect" for lb in mine)
        false_alarm = sum(lb.verdict == "incorrect" and truth[lb.item_id] == "correct" for lb in mine)
        given = [f for f in findings if f.annotator == ann and f.code in ("V303", "V304")]
        conf = sum(f.code == "V304" for f in given)
        lines.append(
            f"| {ann} | {len(mine)} | {right / len(mine):.0%} | {missed} | {false_alarm} | {conf}/{len(given)} |"
        )
    lines.append("")

    if len(annotators) >= 2:
        shared = [per for per in by_item.values() if len(per) >= 2]
        lines += ["## Agreement", "", "| Field | Krippendorff's alpha | Level | Reading |", "|---|---|---|---|"]
        alpha_v = krippendorff_alpha({a: lb.verdict for a, lb in per.items()} for per in shared)
        lines.append(f"| verdict | {_fmt(alpha_v)} | nominal | {interpret_alpha(alpha_v)} |")
        for dim in CODE_DIMENSIONS:
            a = krippendorff_alpha(({x: lb.scores[dim] for x, lb in per.items()} for per in shared), level="ordinal")
            lines.append(f"| {dim} | {_fmt(a)} | ordinal | {interpret_alpha(a)} |")
        lines += ["", "| Pair | n | Verdict % agree | Verdict kappa |", "|---|---|---|---|"]
        for x, y in combinations(annotators, 2):
            both = [per for per in by_item.values() if x in per and y in per]
            if not both:
                continue
            vx, vy = [p[x].verdict for p in both], [p[y].verdict for p in both]
            k = cohen_kappa(vx, vy, categories=VERDICTS)
            lines.append(
                f"| {x} / {y} | {len(both)} | {percent_agreement(vx, vy):.0%} | {_fmt(k)} ({interpret_kappa(k)}) |"
            )
        lines.append("")

    if gold and gold in annotators:
        lines += [f"## Score error against `{gold}`", "", "| Annotator | " + " | ".join(CODE_DIMENSIONS) + " |"]
        lines.append("|---|" + "---|" * len(CODE_DIMENSIONS))
        for ann in annotators:
            if ann == gold:
                continue
            both = [per for per in by_item.values() if gold in per and ann in per]
            if not both:
                continue
            cells = [
                f"{sum(abs(p[ann].scores[d] - p[gold].scores[d]) for p in both) / len(both):.2f}"
                for d in CODE_DIMENSIONS
            ]
            lines.append(f"| {ann} | " + " | ".join(cells) + " |")
        lines.append("")

    lines += ["## Findings", ""]
    if not findings:
        lines.append("No findings.")
    else:
        lines += ["| Where | Code | Kind | Annotator | Item | Message |", "|---|---|---|---|---|---|"]
        order = {"error": 0, "mismatch": 1, "warning": 2, "confirmed": 3}
        for f in sorted(findings, key=lambda f: (order[f.kind], f.item_id, f.annotator)):
            lines.append(f"| {f.where} | {f.code} | {f.kind} | {f.annotator} | {f.item_id} | {_cell(f.message)} |")
    lines += [
        "",
        "## How to read this",
        "",
        "- Ground truth comes from execution, not opinion: hidden tests, plus any annotator failing input that the "
        "trusted reference implementation confirms. A confirmed failing input on an item whose tests pass is a "
        "**test gap** the annotator found.",
        "- 'Missed bugs' (verdict correct on a buggy item) are the costliest annotation error for code data.",
        "- Efficiency, security and readability are judged, not tested; compare them with agreement and gold error.",
        "",
    ]
    return "\n".join(lines)


def _fmt(value: float) -> str:
    return "undefined" if math.isnan(value) else f"{value:.3f}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")

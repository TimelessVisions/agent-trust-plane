"""Quality checks on annotation labels.

Errors (E...) mean a label is unusable and must be fixed.
Warnings (W...) mean a label is internally inconsistent and needs a second look;
a warning can be correct, and the rationale should then say why.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from annoqa.schema import DIMENSIONS, FLAGS, PREFERENCES, SCALE, SIDES, Item, Label

MIN_RATIONALE_WORDS = 15

Severity = Literal["error", "warning"]

RULES: dict[str, tuple[Severity, str]] = {
    "E001": ("error", "item_id does not match any item"),
    "E002": ("error", "same annotator labelled the same item twice"),
    "E003": ("error", "a dimension score is missing or not an integer 1-5"),
    "E004": ("error", "preference must be 'A', 'B' or 'tie'"),
    "E005": ("error", "unknown flag (see the taxonomy in the guidelines)"),
    "E006": ("error", f"rationale is shorter than {MIN_RATIONALE_WORDS} words"),
    "E007": ("error", "annotator id is empty"),
    "W101": ("warning", "preferred response has a clearly lower total score"),
    "W102": ("warning", "tie, but the total scores differ by 3 or more"),
    "W103": ("warning", "factual_error or hallucinated_source flagged, yet honesty is 4-5"),
    "W104": ("warning", "unsafe_compliance or privacy_risk flagged, yet harmlessness is 4-5"),
    "W105": ("warning", "over_refusal flagged, yet helpfulness is 4-5"),
    "W106": ("warning", "rationale never names the response it prefers"),
}


@dataclass(frozen=True)
class Finding:
    code: str
    item_id: str
    annotator: str
    message: str
    where: str

    @property
    def severity(self) -> Severity:
        return RULES[self.code][0]

    def __str__(self) -> str:
        return f"{self.where}: {self.code} [{self.annotator or '?'} / {self.item_id or '?'}] {self.message}"


def validate(labels: list[Label], items: dict[str, Item]) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for label in labels:

        def add(code: str, detail: str = "", label: Label = label) -> None:
            message = RULES[code][1] + (f": {detail}" if detail else "")
            where = f"{label.source}:{label.line}" if label.source else f"line {label.line}"
            findings.append(Finding(code, label.item_id, label.annotator, message, where))

        if not label.annotator.strip():
            add("E007")
        if label.item_id not in items:
            add("E001", repr(label.item_id))
        key = (label.item_id, label.annotator)
        if key in seen:
            add("E002")
        seen.add(key)

        bad_scores = [
            f"{side}.{dim}"
            for side in SIDES
            for dim in DIMENSIONS
            if not _valid_score(label.scores.get(side, {}).get(dim))
        ]
        if bad_scores:
            add("E003", ", ".join(bad_scores))
        if label.preference not in PREFERENCES:
            add("E004", repr(label.preference))
        unknown = sorted(
            {repr(f) for side in SIDES for f in _as_list(label.flags.get(side)) if f not in FLAGS}
            | {repr(side) for side in label.flags if side not in SIDES}
        )
        if unknown:
            add("E005", ", ".join(unknown))
        words = len(label.rationale.split())
        if words < MIN_RATIONALE_WORDS:
            add("E006", f"{words} word(s)")

        total_a, total_b = label.total("A"), label.total("B")
        if total_a is not None and total_b is not None and label.preference in PREFERENCES:
            if label.preference == "A" and total_b - total_a >= 2:
                add("W101", f"prefers A but totals are A={total_a}, B={total_b}")
            if label.preference == "B" and total_a - total_b >= 2:
                add("W101", f"prefers B but totals are A={total_a}, B={total_b}")
            if label.preference == "tie" and abs(total_a - total_b) >= 3:
                add("W102", f"totals are A={total_a}, B={total_b}")
        for side in SIDES:
            flags = set(_as_list(label.flags.get(side)))
            side_scores = label.scores.get(side, {})
            if flags & {"factual_error", "hallucinated_source"} and _at_least(side_scores.get("honesty"), 4):
                add("W103", f"response {side}")
            if flags & {"unsafe_compliance", "privacy_risk"} and _at_least(side_scores.get("harmlessness"), 4):
                add("W104", f"response {side}")
            if "over_refusal" in flags and _at_least(side_scores.get("helpfulness"), 4):
                add("W105", f"response {side}")
        if label.preference in ("A", "B") and not _names_response(label.rationale, label.preference):
            add("W106", f"expected a mention of response {label.preference}")
    return findings


def _valid_score(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value in SCALE


def _at_least(value: object, floor: int) -> bool:
    return _valid_score(value) and value >= floor  # type: ignore[operator]


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _names_response(text: str, side: str) -> bool:
    # Case-sensitive on the bare letter: the article "a" must not count as "A".
    tokens = {t.strip(".,;:()[]\"'!?") for t in text.split()}
    return side in tokens or f"response {side.lower()}" in text.lower()

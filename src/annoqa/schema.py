"""Data shapes for pairwise-preference annotation of LLM responses.

An *item* is one prompt with two candidate responses (A and B).
A *label* is one annotator's judgment of one item. See
``guidelines/pairwise-preference-v1.md`` for what each field means.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DIMENSIONS: tuple[str, ...] = (
    "instruction_following",
    "helpfulness",
    "honesty",
    "harmlessness",
)
SCALE: tuple[int, ...] = (1, 2, 3, 4, 5)
PREFERENCES: tuple[str, ...] = ("A", "B", "tie")
FLAGS: tuple[str, ...] = (
    "factual_error",
    "hallucinated_source",
    "unsafe_compliance",
    "over_refusal",
    "privacy_risk",
    "incomplete",
    "format_violation",
    "code_bug",
)
SIDES: tuple[str, ...] = ("A", "B")


@dataclass(frozen=True)
class Item:
    id: str
    prompt: str
    response_a: str
    response_b: str
    category: str = ""


@dataclass
class Label:
    item_id: str
    annotator: str
    preference: Any
    scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    flags: dict[str, list[Any]] = field(default_factory=dict)
    rationale: str = ""
    line: int = 0
    source: str = ""

    def total(self, side: str) -> int | None:
        """Sum of the four dimension scores for one side, or None if any is invalid."""
        side_scores = self.scores.get(side, {})
        values = [side_scores.get(d) for d in DIMENSIONS]
        if not all(isinstance(v, int) and not isinstance(v, bool) and v in SCALE for v in values):
            return None
        return sum(values)  # type: ignore[arg-type]


class LoadError(ValueError):
    """A file could not be read as JSONL of the expected shape."""


def read_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LoadError(f"{path}:{n}: not valid JSON ({exc.msg})") from exc
            if not isinstance(obj, dict):
                raise LoadError(f"{path}:{n}: each line must be a JSON object")
            rows.append((n, obj))
    return rows


def load_items(path: Path) -> dict[str, Item]:
    items: dict[str, Item] = {}
    for n, obj in read_jsonl(path):
        try:
            item = Item(
                id=str(obj["id"]),
                prompt=str(obj["prompt"]),
                response_a=str(obj["response_a"]),
                response_b=str(obj["response_b"]),
                category=str(obj.get("category", "")),
            )
        except KeyError as exc:
            raise LoadError(f"{path}:{n}: item is missing {exc.args[0]!r}") from exc
        if item.id in items:
            raise LoadError(f"{path}:{n}: duplicate item id {item.id!r}")
        items[item.id] = item
    return items


def load_labels(path: Path) -> list[Label]:
    labels: list[Label] = []
    for n, obj in read_jsonl(path):
        scores = obj.get("scores")
        flags = obj.get("flags")
        labels.append(
            Label(
                item_id=str(obj.get("item_id", "")),
                annotator=str(obj.get("annotator", "")),
                preference=obj.get("preference"),
                scores=scores if isinstance(scores, dict) else {},
                flags=flags if isinstance(flags, dict) else {},
                rationale=str(obj.get("rationale", "")),
                line=n,
                source=str(path),
            )
        )
    return labels

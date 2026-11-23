"""Write data/code/labels/reference.jsonl (reference code-evaluation labels) and
examples/synthetic/code-annotator-b.jsonl (SYNTHETIC second annotator, for the demo).

Scores are (correctness, edge_cases, efficiency, security, readability, explanation_accuracy).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DIMS = ("correctness", "edge_cases", "efficiency", "security", "readability", "explanation_accuracy")


def issue(category: str, severity: str, description: str) -> dict[str, str]:
    return {"category": category, "severity": severity, "description": description}


REFERENCE: list[tuple[str, str, Any, tuple[int, ...], list[dict[str, str]], str]] = [
    (
        "code-001",
        "incorrect",
        [[5, 5, 3]],
        (2, 1, 4, 5, 4, 2),
        [
            issue(
                "logic_bug", "major", "no deduplication: sorted([5, 5, 3])[-2] is 5, not the second distinct value 3"
            ),
            issue("edge_case", "major", "nums[-2] raises IndexError for 0 or 1 elements instead of returning None"),
        ],
        "Incorrect. For [5, 5, 3] it returns 5 because duplicates are not removed, and for [7] it raises IndexError instead of returning None. The explanation omits both requirements.",
    ),
    (
        "code-002",
        "incorrect",
        ["A man, a plan, a canal: Panama"],
        (2, 2, 5, 5, 5, 2),
        [
            issue(
                "spec_mismatch",
                "major",
                "lowercases but never removes spaces and punctuation, which the task says to ignore",
            )
        ],
        "Incorrect. 'A man, a plan, a canal: Panama' returns False because the commas and spaces are compared too; the task says to ignore non-alphanumeric characters. Case handling is right.",
    ),
    (
        "code-003",
        "incorrect",
        [[[8, 10], [1, 3], [2, 6]]],
        (2, 2, 4, 5, 4, 2),
        [
            issue(
                "logic_bug",
                "major",
                "never sorts by start, so unsorted input is merged wrongly: [[8,10],[1,3],[2,6]] -> [[8, 10]]",
            )
        ],
        "Incorrect. The loop assumes intervals arrive sorted. For [[8, 10], [1, 3], [2, 6]] the later intervals compare against [8, 10] and are absorbed into it, giving [[8, 10]] instead of [[1, 6], [8, 10]].",
    ),
    (
        "code-004",
        "correct",
        None,
        (5, 5, 5, 5, 4, 5),
        [],
        "Correct. The full-match regex accepts only hours, minutes and seconds in order, so '1m1h' and '10x' raise ValueError, and the explicit empty check catches ''. Traced '2h5s' to 7205 as required.",
    ),
    (
        "code-005",
        "incorrect",
        [[1, 3, 5, 7], 7],
        (2, 2, 5, 5, 4, 2),
        [
            issue("logic_bug", "major", "line 3 `while lo < hi` stops before checking the last remaining index"),
            issue("explanation_mismatch", "minor", "described as standard binary search, which hides the off-by-one"),
        ],
        "Incorrect. With [1, 3, 5, 7] and target 7 the loop ends when lo == hi == 3 without comparing arr[3], returning -1 instead of 3; a one-element list [4] also fails. Needs `<=`.",
    ),
    (
        "code-006",
        "incorrect",
        ["pear apple pear apple fig", 2],
        (2, 3, 5, 5, 5, 2),
        [
            issue(
                "spec_mismatch",
                "major",
                "most_common keeps first-seen order for ties; the task requires alphabetical tie-breaking",
            ),
            issue("explanation_mismatch", "minor", "claims most_common already gives the required order"),
        ],
        "Incorrect. Tied counts come back in first-seen order, so 'pear apple pear apple fig' with k=2 gives pear before apple, but the task says ties break alphabetically. Counting itself is right.",
    ),
    (
        "code-007",
        "incorrect",
        ["/srv/files", "../secret"],
        (1, 2, 5, 1, 4, 1),
        [
            issue(
                "security",
                "blocker",
                "'..' segments are not normalised, so '../secret' escapes the base directory (path traversal)",
            ),
            issue("explanation_mismatch", "major", "claims the user can only reach files under base, which is false"),
        ],
        "Incorrect and unsafe. safe_join('/srv/files', '../secret') returns '/srv/files/../secret', which resolves outside the base: a path traversal the task explicitly asks to block. Only a leading slash is rejected.",
    ),
    (
        "code-008",
        "incorrect",
        [[1, 2], -1],
        (3, 2, 5, 5, 5, 2),
        [
            issue(
                "error_handling",
                "major",
                "checks `size == 0` only, so negative sizes silently return [] instead of raising ValueError",
            )
        ],
        "Incorrect. The task says raise ValueError if size < 1, but the guard is `size == 0`, so chunk([1, 2], -1) returns [] because range() with a negative step is empty. The explanation claims invalid sizes raise.",
    ),
    (
        "code-009",
        "correct",
        None,
        (5, 5, 1, 5, 4, 4),
        [
            issue(
                "performance",
                "major",
                "nested loops are O(n^2); the task states 100,000+ elements and asks for linear time",
            )
        ],
        "Correct but too slow. Every pair is checked, so results are right, including i < j ordering and None, but at 100,000 elements that is about 5 billion comparisons; a dict of seen values gives O(n).",
    ),
    (
        "code-010",
        "incorrect",
        [[1, 2, 3, 4], 2],
        (2, 2, 5, 5, 4, 2),
        [issue("logic_bug", "major", "range(len(values) - k) drops the last window; it should be len(values) - k + 1")],
        "Incorrect. For [1, 2, 3, 4] with k=2 there are three windows but range(len - k) yields two, so it returns [1.5, 2.5] and loses 3.5; [5, 5] with k=2 returns [] instead of [5.0].",
    ),
]


def rows() -> list[dict[str, Any]]:
    out = []
    for item_id, verdict, failing, scores, issues, rationale in REFERENCE:
        out.append(
            {
                "item_id": item_id,
                "annotator": "ref",
                "verdict": verdict,
                "failing_input": failing,
                "scores": dict(zip(DIMS, scores, strict=True)),
                "issues": issues,
                "rationale": rationale,
            }
        )
    return out


def synthetic(ref: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic, documented perturbations of the reference labels (not human judgments)."""
    b = copy.deepcopy(ref)
    by = {r["item_id"]: r for r in b}
    for r in b:
        r["annotator"] = "synthetic-b"
    # Misses the test gap: trusts the size guard and calls code-008 correct.
    by["code-008"].update(verdict="correct", failing_input=None, issues=[])
    by["code-008"]["scores"].update(correctness=5, edge_cases=4, explanation_accuracy=5)
    by["code-008"]["rationale"] = (
        "Correct. Slicing in steps of size produces the right chunks, the last one shorter, and size 0 raises ValueError as the task requires."
    )
    # Calls the binary search correct (a missed bug the hidden tests catch).
    by["code-005"].update(verdict="correct", failing_input=None, issues=[])
    by["code-005"]["scores"].update(correctness=5, edge_cases=4, explanation_accuracy=5)
    by["code-005"]["rationale"] = (
        "Correct. It halves the search range each step and returns -1 when the target is absent; traced [1, 3, 5, 7] with target 5 to index 2."
    )
    # A failing input that does not actually expose the bug.
    by["code-003"]["failing_input"] = [[[1, 3], [2, 6], [8, 10]]]
    # Harsher on efficiency and readability in a few places (normal judgment variance).
    by["code-004"]["scores"]["readability"] = 3
    by["code-009"]["scores"]["efficiency"] = 2
    by["code-006"]["scores"]["edge_cases"] = 2
    return b


def main() -> None:
    ref = rows()
    for path, data in (
        (ROOT / "data/code/labels/reference.jsonl", ref),
        (ROOT / "examples/synthetic/code-annotator-b.jsonl", synthetic(ref)),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data), encoding="utf-8")
        print(f"wrote {len(data)} labels to {path}")


if __name__ == "__main__":
    main()

"""Write the process-reward (step-level reasoning) task data. All problems are original.

- data/process/items.jsonl: problem, known answer, and a step-by-step solution. Arithmetic steps
  carry `calc` (an expression) and `claims` (what the solver says it equals), so arithmetic is
  re-checked exactly by the tool.
- data/process/hidden.jsonl: authored first error + error type for errors arithmetic cannot reveal
  (a wrong setup computed correctly). Used only for scoring, like hidden tests.
- data/process/labels/reference.jsonl and examples/synthetic/process-annotator-b.jsonl.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def s(text: str, calc: str | None = None, claims: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"text": text}
    if calc is not None:
        out["calc"], out["claims"] = calc, claims
    return out


CAFE = (
    "A cafe sells coffee at $3.50 and muffins at $1.75. Ana buys 4 coffees and 3 muffins "
    "and pays with a $20 bill. How much change does she get?"
)
TRAIN = (
    "A train leaves at 09:40 and the journey normally takes 2 h 35 min. Today it is delayed by "
    "25 min. At what time does it arrive?"
)
SHIRT = "A shirt costs $40. It is discounted 25%, then 10% sales tax is added to the discounted price. What is the final price?"
RECT = "A rectangle has a perimeter of 30 cm and its length is twice its width. What is its area?"
AVG = "Leo's average over 4 tests is 80. After a fifth test his average is 82. What did he score on the fifth test?"

ITEMS: list[dict[str, Any]] = [
    {
        "id": "ps-01",
        "final_answer": "0.75",
        "problem": CAFE,
        "answer": "0.75",
        "steps": [
            s("Coffees cost 4 x 3.50.", "4*3.50", "14"),
            s("Muffins cost 3 x 1.75.", "3*1.75", "5.25"),
            s("Total is 14 + 5.25.", "14+5.25", "19.25"),
            s("Change is 20 - 19.25.", "20-19.25", "0.75"),
            s("So Ana gets $0.75 in change."),
        ],
    },
    {
        "id": "ps-02",
        "final_answer": "0.25",
        "problem": CAFE,
        "answer": "0.75",
        "steps": [
            s("Coffees cost 4 x 3.50.", "4*3.50", "14"),
            s("Muffins cost 3 x 1.75.", "3*1.75", "5.75"),
            s("Total is 14 + 5.75.", "14+5.75", "19.75"),
            s("Change is 20 - 19.75.", "20-19.75", "0.25"),
            s("So Ana gets $0.25 in change."),
        ],
    },
    {
        "id": "ps-03",
        "final_answer": "0.75",
        "problem": CAFE,
        "answer": "0.75",
        "steps": [
            s("Coffees cost 4 x 3.50.", "4*3.50", "15"),
            s("Muffins cost 3 x 1.75.", "3*1.75", "4.25"),
            s("Total is 15 + 4.25.", "15+4.25", "19.25"),
            s("Change is 20 - 19.25.", "20-19.25", "0.75"),
            s("So Ana gets $0.75 in change."),
        ],
    },
    {
        "id": "ps-04",
        "final_answer": "12:40",
        "problem": TRAIN,
        "answer": "12:40",
        "steps": [
            s("Total travel time is 2 h 35 min plus the 25 min delay, in minutes 155 + 25.", "155+25", "180"),
            s("180 minutes is 3 hours."),
            s("09:40 plus 3 hours is 12:40."),
            s("The train arrives at 12:40."),
        ],
    },
    {
        "id": "ps-05",
        "final_answer": "11:50",
        "problem": TRAIN,
        "answer": "12:40",
        "steps": [
            s("The journey takes 2 h 35 min, which is 155 minutes.", "2*60+35", "155"),
            s("A delay shortens the remaining journey, so the travel time is 155 - 25.", "155-25", "130"),
            s("130 minutes is 2 h 10 min."),
            s("09:40 plus 2 h 10 min is 11:50."),
            s("The train arrives at 11:50."),
        ],
    },
    {
        "id": "ps-06",
        "final_answer": "34",
        "problem": SHIRT,
        "answer": "33",
        "steps": [
            s("A 25% discount and a 10% tax combine to a net 15% discount."),
            s("So the price is 40 x 0.85.", "40*0.85", "34"),
            s("The final price is $34."),
        ],
    },
    {
        "id": "ps-07",
        "final_answer": "33",
        "problem": SHIRT,
        "answer": "33",
        "steps": [
            s("After the discount the price is 40 x 0.75.", "40*0.75", "30"),
            s("Adding 10% tax gives 30 x 1.10.", "30*1.10", "33"),
            s("The final price is $33."),
        ],
    },
    {
        "id": "ps-08",
        "final_answer": "50",
        "problem": RECT,
        "answer": "50",
        "steps": [
            s("Let the width be w, so the length is 2w."),
            s("Perimeter: 2(2w + w) = 30, so 6w = 30."),
            s("w = 30 / 6.", "30/6", "5"),
            s("The length is 2 x 5.", "2*5", "10"),
            s("Area = 10 x 5.", "10*5", "50"),
            s("The area is 50 cm^2."),
        ],
    },
    {
        "id": "ps-09",
        "final_answer": "200",
        "problem": RECT,
        "answer": "50",
        "steps": [
            s("Let the width be w, so the length is 2w."),
            s("The perimeter is length plus width, so 2w + w = 30, giving 3w = 30."),
            s("w = 30 / 3.", "30/3", "10"),
            s("The length is 2 x 10.", "2*10", "20"),
            s("Area = 20 x 10.", "20*10", "200"),
            s("The area is 200 cm^2."),
        ],
    },
    {
        "id": "ps-10",
        "final_answer": "90",
        "problem": AVG,
        "answer": "90",
        "steps": [
            s("The first 4 tests total 4 x 80.", "4*80", "320"),
            s("All 5 tests total 5 x 82.", "5*82", "410"),
            s("The fifth score is 410 - 320.", "410-320", "90"),
            s("Leo scored 90."),
        ],
    },
    {
        "id": "ps-11",
        "final_answer": "84",
        "problem": AVG,
        "answer": "90",
        "steps": [
            s("The average rose by 82 - 80 points.", "82-80", "2"),
            s("So the fifth test was just 2 points above the new average: 82 + 2.", "82+2", "84"),
            s("Leo scored 84."),
        ],
    },
]

# First error and type for every flawed solution (None = no error). For arithmetic errors this is
# also derivable from calc/claims; the others need a person to see them.
HIDDEN: dict[str, tuple[int | None, str | None]] = {
    "ps-01": (None, None),
    "ps-02": (2, "arithmetic"),
    "ps-03": (1, "arithmetic"),
    "ps-04": (None, None),
    "ps-05": (2, "setup"),
    "ps-06": (1, "logic"),
    "ps-07": (None, None),
    "ps-08": (None, None),
    "ps-09": (2, "misread"),
    "ps-10": (None, None),
    "ps-11": (2, "logic"),
}


def lab(item: str, labels: list[str], first: int | None, etype: str | None, final: bool, why: str) -> dict[str, Any]:
    return {
        "solution_id": item,
        "annotator": "ref",
        "step_labels": labels,
        "first_error_step": first,
        "error_type": etype,
        "final_answer_correct": final,
        "rationale": why,
    }


REFERENCE = [
    lab(
        "ps-01",
        ["good", "good", "good", "good", "neutral"],
        None,
        None,
        True,
        "Every product and the subtraction are right: 14 + 5.25 = 19.25 and 20 - 19.25 = 0.75. The last step only restates the result, so it is neutral.",
    ),
    lab(
        "ps-02",
        ["good", "bad"],
        2,
        "arithmetic",
        False,
        "Step 2 says 3 x 1.75 = 5.75 but it is 5.25. Later steps compute correctly from the wrong total, so under the first-error convention only steps 1-2 are labelled.",
    ),
    lab(
        "ps-03",
        ["bad"],
        1,
        "arithmetic",
        True,
        "Step 1 says 4 x 3.50 = 15 (it is 14) and step 2 says 3 x 1.75 = 4.25 (it is 5.25). The two errors cancel, so the final answer is right by luck. The process is still wrong from step 1.",
    ),
    lab(
        "ps-04",
        ["good", "good", "good", "neutral"],
        None,
        None,
        True,
        "Adds the 25-minute delay to the 155-minute journey, giving 180 minutes = 3 hours, and 09:40 + 3 h = 12:40. Correct and efficient.",
    ),
    lab(
        "ps-05",
        ["good", "bad"],
        2,
        "setup",
        False,
        "Step 2 subtracts the delay as if it shortened the trip; a delay adds time. The arithmetic 155 - 25 = 130 is right, so only a person can see this setup error. The answer 11:50 is wrong.",
    ),
    lab(
        "ps-06",
        ["bad"],
        1,
        "logic",
        False,
        "Step 1 claims 25% off and 10% tax net to 15% off, but percentages compound: 0.75 x 1.10 = 0.825, a 17.5% net discount. The arithmetic in step 2 is right but built on that false premise.",
    ),
    lab(
        "ps-07",
        ["good", "good", "neutral"],
        None,
        None,
        True,
        "Applies the discount first (40 x 0.75 = 30) and then tax on the discounted price (30 x 1.10 = 33), exactly as the problem specifies. The final step restates.",
    ),
    lab(
        "ps-08",
        ["good", "good", "good", "good", "good", "neutral"],
        None,
        None,
        True,
        "A correct setup, 2(2w + w) = 30, then w = 5, l = 10 and area 50 cm^2. Every calculation checks.",
    ),
    lab(
        "ps-09",
        ["good", "bad"],
        2,
        "misread",
        False,
        "Step 2 uses length + width = 30, but the perimeter is 2(l + w). All later arithmetic is correct for the wrong equation, so the area 200 is wrong, and arithmetic checks cannot catch it.",
    ),
    lab(
        "ps-10",
        ["good", "good", "good", "neutral"],
        None,
        None,
        True,
        "The first four tests total 320, all five total 410, and the difference is 90. A clean, standard method.",
    ),
    lab(
        "ps-11",
        ["good", "bad"],
        2,
        "logic",
        False,
        "Step 1 is fine, but step 2 assumes the new score is only 2 above the new average. Raising a 4-test average by 2 needs 4 x 2 = 8 points above it, so 82 + 8 = 90, not 84.",
    ),
]


def synthetic(ref: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Documented perturbations, not human judgments."""
    b = copy.deepcopy(ref)
    by = {r["solution_id"]: r for r in b}
    for r in b:
        r["annotator"] = "synthetic-b"
    # Outcome-biased: sees the right final answer and marks the lucky solution correct.
    by["ps-03"].update(step_labels=["good", "good", "good", "good", "neutral"], first_error_step=None, error_type=None)
    by["ps-03"]["rationale"] = (
        "The final change of $0.75 matches the expected answer and each step follows from the previous one, so the solution is correct."
    )
    # Misses a setup error whose arithmetic is right (labels it late, at the final time).
    by["ps-05"].update(step_labels=["good", "good", "good", "bad"], first_error_step=4, error_type="arithmetic")
    # Right step, wrong error type.
    by["ps-09"]["error_type"] = "setup"
    return b


def main() -> None:
    out = {
        ROOT / "data/process/items.jsonl": ITEMS,
        ROOT / "data/process/hidden.jsonl": [
            {"id": k, "first_error_step": v[0], "error_type": v[1]} for k, v in HIDDEN.items()
        ],
        ROOT / "data/process/labels/reference.jsonl": REFERENCE,
        ROOT / "examples/synthetic/process-annotator-b.jsonl": synthetic(REFERENCE),
    }
    for path, rows in out.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"wrote {len(rows)} rows to {path}")


if __name__ == "__main__":
    main()

"""Make SYNTHETIC second-annotator labels for the demo report.

These are not human judgments. They are the reference labels with seeded,
documented perturbations, so the report has realistic disagreements to show:
score noise of +/-1, a missed flag, one preference flip, one inconsistent label
(prefers the lower-scored side) and one too-short rationale.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = 20261123


def main() -> None:
    rng = random.Random(SEED)
    ref = [json.loads(line) for line in (ROOT / "data/labels/reference.jsonl").read_text("utf-8").splitlines()]
    out_rows = []
    for row in ref:
        new = copy.deepcopy(row)
        new["annotator"] = "synthetic-b"
        for side in ("A", "B"):
            for dim, value in new["scores"][side].items():
                if rng.random() < 0.25:
                    new["scores"][side][dim] = min(5, max(1, value + rng.choice((-1, 1))))
        out_rows.append(new)
    by_id = {r["item_id"]: r for r in out_rows}
    # A missed flag: the hallucinated citation is noticed as a factual error only.
    by_id["it-008"]["flags"]["A"] = ["factual_error"]
    # A genuine judgment difference: prefers the fuller answer on the near-tie.
    by_id["it-011"]["preference"] = "A"
    by_id["it-011"]["rationale"] = (
        "A is slightly better: same options as B, but it also explains that insurers often include roadside "
        "assistance and names example apps, which makes it more actionable."
    )
    # An inconsistent label the validator should warn about (W101).
    by_id["it-012"]["preference"] = "B"
    by_id["it-012"]["rationale"] = "B is better because it is shorter and gets to the point about practising more."
    # A label the validator should reject (E006: rationale too short).
    by_id["it-006"]["rationale"] = "A follows the format."
    out = ROOT / "examples/synthetic/annotator-b.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out_rows), encoding="utf-8")
    print(f"wrote {len(out_rows)} synthetic labels to {out}")


if __name__ == "__main__":
    main()

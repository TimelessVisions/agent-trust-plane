"""Inter-annotator agreement metrics, dependency-free.

All functions return ``float('nan')`` when the statistic is undefined
(for example, when every rating falls in a single category, so chance
agreement is total). Callers must report NaN as "undefined", never as 0 or 1.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Hashable, Iterable, Mapping, Sequence
from typing import Literal

Level = Literal["nominal", "ordinal", "interval"]
Weights = Literal["none", "linear", "quadratic"]


def percent_agreement(a: Sequence[Hashable], b: Sequence[Hashable]) -> float:
    """Share of paired items on which two annotators gave the same label."""
    _check_pairs(a, b)
    if not a:
        return math.nan
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def cohen_kappa(
    a: Sequence[Hashable],
    b: Sequence[Hashable],
    *,
    weights: Weights = "none",
    categories: Sequence[Hashable] | None = None,
) -> float:
    """Cohen's kappa for two annotators, optionally weighted.

    ``weights="linear"`` or ``"quadratic"`` treats the labels as ordered; pass
    ``categories`` in their order (e.g. ``range(1, 6)`` for a 1-5 scale), so
    categories nobody used still count toward the distance between labels.
    """
    _check_pairs(a, b)
    if not a:
        return math.nan
    cats = list(categories) if categories is not None else sorted(set(a) | set(b), key=repr)
    index = {c: i for i, c in enumerate(cats)}
    unknown = (set(a) | set(b)) - set(index)
    if unknown:
        raise ValueError(f"labels not in categories: {sorted(map(repr, unknown))}")
    k = len(cats)
    n = len(a)
    observed = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        observed[index[x]][index[y]] += 1 / n
    row = [sum(r) for r in observed]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]

    def disagreement(i: int, j: int) -> float:
        if weights == "none":
            return 0.0 if i == j else 1.0
        if k == 1:
            return 0.0
        d = abs(i - j) / (k - 1)
        return d if weights == "linear" else d * d

    obs = sum(disagreement(i, j) * observed[i][j] for i in range(k) for j in range(k))
    exp = sum(disagreement(i, j) * row[i] * col[j] for i in range(k) for j in range(k))
    if exp == 0:
        return math.nan
    return 1 - obs / exp


def krippendorff_alpha(
    units: Iterable[Mapping[str, Hashable | None]] | Iterable[Sequence[Hashable | None]],
    *,
    level: Level = "nominal",
) -> float:
    """Krippendorff's alpha for any number of annotators, with missing data.

    ``units`` holds one entry per item: either a mapping ``annotator -> label``
    or a sequence of labels, where ``None`` means "not rated". Items rated by
    fewer than two annotators carry no information and are skipped.
    ``ordinal`` and ``interval`` need numeric labels.
    """
    values_per_unit: list[list[Hashable]] = []
    for unit in units:
        raw = unit.values() if isinstance(unit, Mapping) else unit
        vals = [v for v in raw if v is not None]
        if len(vals) >= 2:
            values_per_unit.append(vals)
    if not values_per_unit:
        return math.nan

    coincidence: defaultdict[tuple[Hashable, Hashable], float] = defaultdict(float)
    for vals in values_per_unit:
        m = len(vals)
        for i, c in enumerate(vals):
            for j, k in enumerate(vals):
                if i != j:
                    coincidence[(c, k)] += 1 / (m - 1)
    marginals: defaultdict[Hashable, float] = defaultdict(float)
    for (c, _k), w in coincidence.items():
        marginals[c] += w
    n = sum(marginals.values())
    cats = sorted(marginals, key=_sort_key)
    if level != "nominal" and not all(isinstance(c, int | float) for c in cats):
        raise ValueError(f"{level} alpha needs numeric labels")

    def delta2(c: Hashable, k: Hashable) -> float:
        if c == k:
            return 0.0
        if level == "nominal":
            return 1.0
        if level == "interval":
            return float(c - k) ** 2  # type: ignore[operator]
        lo, hi = sorted((c, k), key=_sort_key)
        between = sum(marginals[g] for g in cats if _sort_key(lo) <= _sort_key(g) <= _sort_key(hi))
        return (between - (marginals[c] + marginals[k]) / 2) ** 2

    d_obs = sum(w * delta2(c, k) for (c, k), w in coincidence.items()) / n
    d_exp = sum(marginals[c] * marginals[k] * delta2(c, k) for c in cats for k in cats) / (n * (n - 1))
    if d_exp == 0:
        return math.nan
    return 1 - d_obs / d_exp


def interpret_kappa(value: float) -> str:
    """Landis & Koch (1977) bands for kappa. A rough guide, not a pass/fail threshold."""
    if math.isnan(value):
        return "undefined"
    if value < 0:
        return "poor"
    for upper, name in ((0.20, "slight"), (0.40, "fair"), (0.60, "moderate"), (0.80, "substantial")):
        if value <= upper:
            return name
    return "almost perfect"


def interpret_alpha(value: float) -> str:
    """Krippendorff's (2004) guidance: >= 0.800 reliable; 0.667-0.800 tentative conclusions only."""
    if math.isnan(value):
        return "undefined"
    if value >= 0.8:
        return "reliable"
    if value >= 0.667:
        return "tentative"
    return "unreliable"


def _check_pairs(a: Sequence[Hashable], b: Sequence[Hashable]) -> None:
    if len(a) != len(b):
        raise ValueError(f"annotators rated different numbers of items ({len(a)} vs {len(b)})")


def _sort_key(value: Hashable) -> tuple[int, float | str]:
    if isinstance(value, bool):
        return (1, repr(value))
    if isinstance(value, int | float):
        return (0, float(value))
    return (1, repr(value))

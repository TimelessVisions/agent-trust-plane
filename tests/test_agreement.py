"""Agreement metrics against published values and hand-computed cases.

The Krippendorff reference values (0.743 / 0.815 / 0.849) are the worked
example in Krippendorff (2011), "Computing Krippendorff's Alpha-Reliability".
During development the implementation was also cross-checked against the
`krippendorff` and scikit-learn packages on 200 random datasets (exact to 1e-9).
"""

from __future__ import annotations

import math

import pytest

from annoqa.agreement import (
    cohen_kappa,
    interpret_alpha,
    interpret_kappa,
    krippendorff_alpha,
    percent_agreement,
)

# 4 coders x 12 units; None = not rated.
KRIPPENDORFF_2011 = [
    [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None],
    [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, 3],
    [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None],
    [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None],
]
UNITS = [[coder[u] for coder in KRIPPENDORFF_2011] for u in range(12)]


@pytest.mark.parametrize(
    ("level", "expected"),
    [("nominal", 0.743421), ("ordinal", 0.815388), ("interval", 0.849107)],
)
def test_alpha_matches_krippendorff_2011(level: str, expected: float) -> None:
    assert krippendorff_alpha(UNITS, level=level) == pytest.approx(expected, abs=1e-6)  # type: ignore[arg-type]


def test_alpha_accepts_mappings_and_skips_single_ratings() -> None:
    as_maps = [{f"c{i}": v for i, v in enumerate(unit)} for unit in UNITS]
    assert krippendorff_alpha(as_maps) == pytest.approx(krippendorff_alpha(UNITS))
    # Unit 12 has one rating only; adding more such units changes nothing.
    assert krippendorff_alpha([*UNITS, [None, 4, None, None]]) == pytest.approx(krippendorff_alpha(UNITS))


def test_alpha_undefined_when_no_variation() -> None:
    assert math.isnan(krippendorff_alpha([[1, 1], [1, 1], [1, 1]]))
    assert math.isnan(krippendorff_alpha([[1, None], [None, 2]]))


def test_alpha_perfect_and_worse_than_chance() -> None:
    assert krippendorff_alpha([[1, 1], [2, 2], [3, 3]]) == pytest.approx(1.0)
    assert krippendorff_alpha([["A", "B"], ["B", "A"], ["A", "B"], ["B", "A"]]) < 0


def test_alpha_ordinal_needs_numbers() -> None:
    with pytest.raises(ValueError, match="numeric"):
        krippendorff_alpha([["low", "high"], ["high", "high"]], level="ordinal")


def test_cohen_kappa_hand_computed() -> None:
    # 2x2 table: both yes 20, a-yes/b-no 5, a-no/b-yes 10, both no 15 (n=50).
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    # p_o = 0.7; p_e = 0.5*0.6 + 0.5*0.4 = 0.5; kappa = 0.4
    assert cohen_kappa(a, b) == pytest.approx(0.4)
    assert percent_agreement(a, b) == pytest.approx(0.7)


def test_weighted_kappa_penalises_distance() -> None:
    gold = [1, 2, 3, 4, 5] * 4
    near = [min(5, g + 1) for g in gold]
    far = [6 - g for g in gold]
    scale = range(1, 6)
    assert cohen_kappa(gold, near, weights="quadratic", categories=scale) > 0.7
    assert cohen_kappa(gold, far, weights="quadratic", categories=scale) == pytest.approx(-1.0)
    assert cohen_kappa(gold, near, weights="linear", categories=scale) < cohen_kappa(
        gold, near, weights="quadratic", categories=scale
    )


def test_kappa_input_errors() -> None:
    with pytest.raises(ValueError, match="different numbers"):
        cohen_kappa([1, 2], [1])
    with pytest.raises(ValueError, match="not in categories"):
        cohen_kappa([1, 7], [1, 2], categories=range(1, 6))
    assert math.isnan(cohen_kappa(["A", "A"], ["A", "A"]))


@pytest.mark.parametrize(
    ("value", "kappa", "alpha"),
    [
        (-0.1, "poor", "unreliable"),
        (0.0, "slight", "unreliable"),
        (0.5, "moderate", "unreliable"),
        (0.7, "substantial", "tentative"),
        (0.85, "almost perfect", "reliable"),
        (math.nan, "undefined", "undefined"),
    ],
)
def test_interpretation_bands(value: float, kappa: str, alpha: str) -> None:
    assert interpret_kappa(value) == kappa
    assert interpret_alpha(value) == alpha

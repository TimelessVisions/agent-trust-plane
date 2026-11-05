"""`version:` in regression suites: same contract as atp-mcp.yaml and policies.yaml."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest
import yaml

from atp_core import UnversionedFileWarning
from atp_evals.regression import load_suite

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "examples" / "regression-suite" / "accounts-payable.yaml"


def _sample(**changes: object) -> dict[str, object]:
    data: dict[str, object] = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    data.pop("version")
    data.update(changes)
    return data


def test_unversioned_suite_warns_once(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(yaml.safe_dump(_sample()), encoding="utf-8")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert load_suite(path).version == 1
        load_suite(path)
    unversioned = [w for w in caught if issubclass(w.category, UnversionedFileWarning)]
    assert len(unversioned) == 1
    assert "regression suite" in str(unversioned[0].message)


def test_unsupported_suite_version_rejected(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(yaml.safe_dump(_sample(version=2)), encoding="utf-8")
    with pytest.raises(
        ValueError, match=re.escape("unsupported regression suite version 2; this atp supports 1")
    ):
        load_suite(path)


def test_sample_suite_is_versioned() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert load_suite(SAMPLE).version == 1

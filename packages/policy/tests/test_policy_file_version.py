"""`version:` in policies.yaml. The top-level ``version`` is the file format
version (only 1); ``policy_sets[].version`` is a set's free-form name and is
unrelated."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest
import yaml

from atp_core import UnversionedFileWarning
from atp_policy import load_policy_file
from atp_policy.declarative import PolicyFile, dump_policy_file

SETS = {"policy_sets": [{"version": "notes-v1", "rules": []}]}


def _write(path: Path, doc: dict[str, object]) -> Path:
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def test_unversioned_policy_file_warns_once(tmp_path: Path) -> None:
    path = _write(tmp_path / "policies.yaml", SETS)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert load_policy_file(path).version == 1
        assert load_policy_file(path).policy_sets[0].version == "notes-v1"
    unversioned = [w for w in caught if issubclass(w.category, UnversionedFileWarning)]
    assert len(unversioned) == 1
    assert "policies.yaml" in str(unversioned[0].message)


def test_versioned_policy_file_does_not_warn(tmp_path: Path) -> None:
    path = _write(tmp_path / "policies.yaml", {"version": 1, **SETS})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert load_policy_file(path).version == 1


@pytest.mark.parametrize("bad", [2, 0, "1", "notes-v1", True])
def test_unsupported_policy_file_version_rejected(tmp_path: Path, bad: object) -> None:
    path = _write(tmp_path / "policies.yaml", {"version": bad, **SETS})
    with pytest.raises(
        ValueError, match=r"unsupported policies\.yaml version .*; this atp supports 1"
    ):
        load_policy_file(path)
    with pytest.raises(
        ValueError, match=re.escape("unsupported policies.yaml version 2; this atp supports 1")
    ):
        PolicyFile.model_validate({"version": 2, **SETS})


def test_dump_policy_file_writes_version_first(tmp_path: Path) -> None:
    dump_policy_file(PolicyFile.model_validate(SETS), tmp_path / "p.yaml")
    assert (tmp_path / "p.yaml").read_text(encoding="utf-8").startswith("version: 1\n")

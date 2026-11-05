"""File format version helpers: warn once per file, and a reset for tests."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from atp_core import UnversionedFileWarning, show_unversioned_file_warnings, warn_if_unversioned
from atp_core.fileversion import _reset_warned


def _count(path: Path) -> int:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_if_unversioned({}, path, "policies.yaml")
    return sum(1 for w in caught if issubclass(w.category, UnversionedFileWarning))


def test_warns_once_until_reset(tmp_path: Path) -> None:
    path = tmp_path / "p.yaml"
    assert _count(path) == 1
    assert _count(path) == 0
    _reset_warned()
    assert _count(path) == 1


def test_show_unversioned_file_warnings_prints_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    show_unversioned_file_warnings()
    show_unversioned_file_warnings()  # idempotent: still one line per warning
    path = tmp_path / "p.yaml"
    warn_if_unversioned({}, path, "policies.yaml")
    err = capsys.readouterr().err
    lines = [line for line in err.splitlines() if line]
    assert len(lines) == 1
    assert lines[0].startswith(f"warning: {path}: this policies.yaml file has no `version:`")


def test_order_independence_first_half(tmp_path_factory: pytest.TempPathFactory) -> None:
    # the root conftest resets the warn-once set before every test, so the
    # same file warns again in the next test
    assert _count(_shared(tmp_path_factory)) == 1


def test_order_independence_second_half(tmp_path_factory: pytest.TempPathFactory) -> None:
    assert _count(_shared(tmp_path_factory)) == 1


def _shared(factory: pytest.TempPathFactory) -> Path:
    return factory.getbasetemp() / "shared-unversioned.yaml"

"""Root conftest for the workspace test suite (see ``testpaths``)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from atp_core.fileversion import _reset_warned


@pytest.fixture(autouse=True)
def _fresh_unversioned_file_warnings() -> Iterator[None]:
    """`warn_if_unversioned` warns once per file per process. Reset it around
    every test so in-process tests do not depend on their order."""
    _reset_warned()
    yield
    _reset_warned()

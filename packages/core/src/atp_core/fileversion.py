"""File format versions for the files a person writes or reviews:
``atp-mcp.yaml``, ``policies.yaml`` and regression suites.

Each carries a top-level ``version:``. This atp reads version 1 only. A file
without ``version:`` loads as version 1 and emits one
:class:`UnversionedFileWarning` (a ``DeprecationWarning``) per file per
process; ``atp migrate`` adds the field.

"Per file" is keyed by the file's resolved real path plus its kind, so the
same file reached through a relative path, a symlink or ``./`` warns once,
and two different files each warn once.
"""

from __future__ import annotations

import os
import threading
import warnings
from pathlib import Path
from typing import Any

FILE_FORMAT_VERSION = 1


class UnversionedFileWarning(DeprecationWarning):
    """A config file has no top-level ``version:``; it was read as version 1."""


_warned: set[tuple[str, str]] = set()
_lock = threading.Lock()


def check_file_version(value: Any, kind: str) -> int:
    """Return the version if this atp supports it; raise ``ValueError`` otherwise.

    Only the integer 1 is accepted: not ``"1"``, ``1.0`` or ``true``.
    """
    if type(value) is int and value == FILE_FORMAT_VERSION:
        return value
    raise ValueError(
        f"unsupported {kind} version {value!r}; this atp supports {FILE_FORMAT_VERSION}"
    )


def _key(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def warn_if_unversioned(raw: Any, path: str | Path, kind: str) -> None:
    """Warn once per file when the parsed top-level mapping has no ``version``."""
    if not isinstance(raw, dict) or "version" in raw:
        return
    key = (kind, _key(path))
    with _lock:
        if key in _warned:
            return
        _warned.add(key)
    warnings.warn(
        f"{path}: this {kind} file has no `version:`; reading it as version "
        f"{FILE_FORMAT_VERSION}. Files without `version:` are deprecated: run "
        f"`atp migrate {path}` to add it.",
        UnversionedFileWarning,
        stacklevel=2,
    )

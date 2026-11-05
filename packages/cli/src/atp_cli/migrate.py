"""``atp migrate``: bring config files to the current file format version.

Three kinds of file carry a top-level ``version:``. The kind is detected
from the content, never from the file name:

* ``mcp-config`` (``atp-mcp.yaml``): has ``server_name`` and ``upstream``;
* ``policies`` (``policies.yaml``): has ``policy_sets``;
* ``regression-suite``: has ``delegations`` and ``cases``.

Version 1 is the only version so far, so a migration adds ``version: 1``
to a file that lacks it. A YAML file keeps its comments and layout: the
line is inserted above the first top-level key, and the result is checked
to parse to the same data plus ``version``. A JSON file stays JSON. Running
it again changes nothing.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from atp_core import FILE_FORMAT_VERSION, MAX_INPUT_BYTES, check_file_version

FileKind = Literal["mcp-config", "policies", "regression-suite"]

# The name each kind uses in its "unsupported ... version" error, the same
# one its loader uses.
_KIND_NAMES: dict[FileKind, str] = {
    "mcp-config": "atp-mcp.yaml",
    "policies": "policies.yaml",
    "regression-suite": "regression suite",
}


class UnknownFileKindError(ValueError):
    """The content is not an atp-mcp.yaml, a policies.yaml or a regression suite."""


@dataclass(frozen=True)
class MigrationResult:
    path: Path
    kind: FileKind
    changed: bool


def detect_kind(raw: Any) -> FileKind | None:
    if not isinstance(raw, dict):
        return None
    matches: list[FileKind] = []
    if "server_name" in raw and "upstream" in raw:
        matches.append("mcp-config")
    if "policy_sets" in raw:
        matches.append("policies")
    if "delegations" in raw and "cases" in raw:
        matches.append("regression-suite")
    return matches[0] if len(matches) == 1 else None


def _read(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_INPUT_BYTES:
        raise ValueError(f"{path}: {size} bytes exceeds the {MAX_INPUT_BYTES}-byte input limit")
    # bytes, not read_text: keep the file's own line endings
    return path.read_bytes().decode("utf-8")


def _with_version_yaml(text: str, raw: dict[str, Any]) -> str | None:
    """Insert ``version: 1`` above the first top-level key, keeping comments.
    None if the file's layout does not allow that (e.g. a flow mapping)."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("%"):
            continue
        if stripped == "---":
            continue
        if line[0].isspace() or stripped.startswith("{"):
            return None
        lines.insert(i, f"version: {FILE_FORMAT_VERSION}{newline}")
        candidate = "".join(lines)
        try:
            parsed = yaml.safe_load(candidate)
        except yaml.YAMLError:
            return None
        expected = {"version": FILE_FORMAT_VERSION, **raw}
        if parsed != expected or list(parsed) != list(expected):
            return None
        return candidate
    return None


def _with_version(text: str, raw: dict[str, Any]) -> str:
    data = {"version": FILE_FORMAT_VERSION, **raw}
    if text.lstrip().startswith("{"):
        try:
            json.loads(text)
        except ValueError:
            pass
        else:
            return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    kept = _with_version_yaml(text, raw)
    if kept is not None:
        return kept
    # Last resort (a YAML flow mapping, say): re-emit the data. Comments go.
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _write_atomically(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def migrate_file(path: Path) -> MigrationResult:
    """Bring one file to the current format version, in place.

    Raises ``UnknownFileKindError`` when the content is none of the three
    kinds, and ``ValueError`` for a version this atp does not support or a
    file that does not parse.
    """
    path = Path(path)
    text = _read(path)
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: not valid YAML or JSON: {exc}") from exc
    kind = detect_kind(raw)
    if kind is None:
        raise UnknownFileKindError(
            f"{path}: unknown file kind; expected an atp-mcp.yaml (server_name, upstream), "
            "a policies.yaml (policy_sets) or a regression suite (delegations, cases)"
        )
    assert isinstance(raw, dict)
    if "version" in raw:
        try:
            check_file_version(raw["version"], _KIND_NAMES[kind])
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
        return MigrationResult(path=path, kind=kind, changed=False)
    _write_atomically(path, _with_version(text, raw))
    return MigrationResult(path=path, kind=kind, changed=True)


def run_migrate(paths: list[str]) -> int:
    """``atp migrate PATH...``: one stdout line per migrated or current file,
    errors on stderr. Exit 0 when every file is current afterwards, 2 when
    any file is missing, unknown, unparsable or of an unsupported version."""
    import sys

    code = 0
    for name in paths:
        try:
            result = migrate_file(Path(name))
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr, flush=True)
            code = 2
            continue
        if result.changed:
            print(f"migrated {name} ({result.kind}): added version: {FILE_FORMAT_VERSION}")
        else:
            print(f"current  {name} ({result.kind}): already version {FILE_FORMAT_VERSION}")
    return code

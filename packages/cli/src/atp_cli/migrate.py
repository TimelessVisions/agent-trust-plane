"""``atp migrate``: bring config files to the current file format version.

Three kinds of file carry a top-level ``version:``. The kind is detected
from the content, never from the file name:

* ``mcp-config`` (``atp-mcp.yaml``): has ``server_name`` and ``upstream``;
* ``policies`` (``policies.yaml``): has ``policy_sets``;
* ``regression-suite``: has ``delegations`` and ``cases``.

Version 1 is the only version so far, so a migration adds ``version: 1``
to a file that lacks it, and rewrites a near miss (``"1"`` or ``1.0``) to
``1``; any other value is refused. A YAML file keeps its comments, layout,
line endings and UTF-8 BOM: the line is inserted above the first top-level
key (after any ``---`` marker or tag line), and the result is checked to
parse to the same data plus ``version``. When the layout leaves no such line
(a flow mapping), a file without comments is re-emitted, and a file with
comments is refused rather than have them dropped. A JSON file stays JSON.
A symlink is followed: the file it points at is updated, the link stays.
Running it again changes nothing.
"""

from __future__ import annotations

import json
import os
import re
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
    # the value replaced by 1 (e.g. "1" or 1.0); None when `version:` was added
    previous_version: Any = None


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


_BOM = "\ufeff"

# `version:` values that clearly mean 1 and are rewritten to the integer 1.
# Anything else that is not 1 (`true`, `2`, `"2"`, `1.5`, `"1.0"`) is refused.
_NEAR_MISS_VERSIONS: tuple[Any, ...] = ("1", 1.0)

_DOC_START = re.compile(r"---(?:[ \t#].*)?\r?\n?\Z", re.DOTALL)
_TAG_ONLY = re.compile(r"![^\s#]*[ \t]*(?:#.*)?\r?\n?\Z", re.DOTALL)
_VERSION_LINE = re.compile(r"(version[ \t]*:[ \t]*)([^\s#]+)(.*)", re.DOTALL)


class CommentLossError(ValueError):
    """The file cannot be updated without dropping its comments."""


def _has_comments(text: str) -> bool:
    """Conservative: any ``#`` at the start of a line or after whitespace.
    A ``#`` inside a quoted string counts too; that only means refusing."""
    return re.search(r"(?:^|\s)#", text) is not None


def _same(candidate: str, expected: dict[str, Any]) -> bool:
    try:
        parsed = yaml.safe_load(candidate)
    except yaml.YAMLError:
        return False
    return parsed == expected and list(parsed) == list(expected)


def _first_content_line(lines: list[str]) -> int | None:
    """Index of the first line that holds content: not blank, a comment, a
    directive, a ``---`` document-start marker (with an optional tag or
    comment after it) or a line holding only a tag such as ``!!map``."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("%") or _DOC_START.match(line) or _TAG_ONLY.match(line):
            continue
        return i
    return None


def _insert_version_yaml(text: str, raw: dict[str, Any]) -> str | None:
    """Insert ``version: 1`` above the first top-level key, keeping comments.
    None if the file's layout does not allow that (e.g. a flow mapping)."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    i = _first_content_line(lines)
    if i is None or lines[i][0].isspace() or lines[i].startswith("{"):
        return None
    if i > 0 and not lines[i - 1].endswith("\n"):
        return None
    lines.insert(i, f"version: {FILE_FORMAT_VERSION}{newline}")
    candidate = "".join(lines)
    return candidate if _same(candidate, {"version": FILE_FORMAT_VERSION, **raw}) else None


def _set_version_yaml(text: str, raw: dict[str, Any]) -> str | None:
    """Rewrite the value of the top-level ``version:`` line to 1, keeping
    everything else on that line and in the file."""
    lines = text.splitlines(keepends=True)
    expected = {**raw, "version": FILE_FORMAT_VERSION}
    for i, line in enumerate(lines):
        m = _VERSION_LINE.match(line)
        if m is None:
            continue
        candidate_lines = list(lines)
        candidate_lines[i] = f"{m.group(1)}{FILE_FORMAT_VERSION}{m.group(3)}"
        candidate = "".join(candidate_lines)
        if _same(candidate, expected):
            return candidate
    return None


def _updated(path: Path, text: str, raw: dict[str, Any]) -> str:
    """The file's new text with ``version: 1``: added when missing, or
    replacing a near-miss value such as ``"1"``."""
    bom = _BOM if text.startswith(_BOM) else ""
    body = text[len(bom) :]
    if body.lstrip().startswith("{"):
        try:
            data = json.loads(body)
        except ValueError:
            pass
        else:
            # the JSON parse, not the YAML one: YAML reads `1e2` as a string
            if isinstance(data, dict):
                if "version" in data:
                    data["version"] = FILE_FORMAT_VERSION  # keeps its position
                else:
                    data = {"version": FILE_FORMAT_VERSION, **data}
                return bom + json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if "version" in raw:
        kept = _set_version_yaml(body, raw)
        expected = {**raw, "version": FILE_FORMAT_VERSION}
    else:
        kept = _insert_version_yaml(body, raw)
        expected = {"version": FILE_FORMAT_VERSION, **raw}
    if kept is not None:
        return bom + kept
    # The layout (a flow mapping, say) leaves no line to edit in place.
    # Re-emitting the data would drop comments: refuse rather than lose them.
    if _has_comments(body):
        raise CommentLossError(
            f"{path}: cannot add `version: {FILE_FORMAT_VERSION}` here without losing its "
            f"comments; add `version: {FILE_FORMAT_VERSION}` as a top-level key by hand"
        )
    return bom + yaml.safe_dump(expected, sort_keys=False, allow_unicode=True)


def _write_atomically(path: Path, text: str) -> None:
    """Replace ``path``'s content. ``path`` must already be resolved, so a
    symlink keeps pointing at the file instead of being replaced by one."""
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
    previous = None
    if "version" in raw:
        previous = raw["version"]
        near_miss = any(type(previous) is type(v) and previous == v for v in _NEAR_MISS_VERSIONS)
        if not near_miss:
            try:
                check_file_version(previous, _KIND_NAMES[kind])
            except ValueError as exc:
                raise ValueError(f"{path}: {exc}") from exc
            return MigrationResult(path=path, kind=kind, changed=False)
    # write through a symlink, never over it
    _write_atomically(path.resolve(), _updated(path, text, raw))
    return MigrationResult(path=path, kind=kind, changed=True, previous_version=previous)


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
        if result.changed and result.previous_version is not None:
            was = repr(result.previous_version)
            print(
                f"migrated {name} ({result.kind}): set version: {FILE_FORMAT_VERSION} (was {was})"
            )
        elif result.changed:
            print(f"migrated {name} ({result.kind}): added version: {FILE_FORMAT_VERSION}")
        else:
            print(f"current  {name} ({result.kind}): already version {FILE_FORMAT_VERSION}")
    return code

"""`atp migrate`: bring atp-mcp.yaml, policies.yaml and regression suites to
the current file format version. Detection is by content, never by name."""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import pytest
import yaml

from atp_adapter_mcp.config import load_config
from atp_cli.main import main
from atp_cli.migrate import MigrationResult, UnknownFileKindError, migrate_file
from atp_evals.regression import load_suite
from atp_policy import load_policy_file

ROOT = Path(__file__).resolve().parents[3]
SAMPLE_SUITE = ROOT / "examples" / "regression-suite" / "accounts-payable.yaml"

MCP_CONFIG = """\
# atp-mcp.yaml written by atp 0.3.2 (reviewed by me)
server_name: notes   # short name
upstream:
  command: notes-server
tools:
  - mcp_tool: write_note
    tool: mcp.notes
    action: write_note
    capability: notes:write
    resource_template: "note:{title}"
"""

POLICIES = """\
# my policies
policy_sets:
  - version: notes-v1   # a set name, not the file format version
    rules: []
"""


def _suite_text() -> str:
    lines = SAMPLE_SUITE.read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(line for line in lines if not line.startswith("version:"))


def _run(*args: str) -> int:
    with pytest.raises(SystemExit) as exc:
        main(list(args))
    code = exc.value.code
    return int(code) if isinstance(code, int) else 1


def _load_quietly(kind: str, path: Path) -> object:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        if kind == "mcp-config":
            return load_config(path)
        if kind == "policies":
            return load_policy_file(path)
        return load_suite(path)


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "atp-mcp.yaml"
    path.write_text(MCP_CONFIG, encoding="utf-8")
    first = migrate_file(path)
    assert first == MigrationResult(path=path, kind="mcp-config", changed=True)
    after_first = path.read_text(encoding="utf-8")
    assert "version: 1\n" in after_first
    # comments and layout survive
    assert after_first.startswith("# atp-mcp.yaml written by atp 0.3.2 (reviewed by me)\n")
    assert "server_name: notes   # short name" in after_first
    assert yaml.safe_load(after_first) == {"version": 1, **yaml.safe_load(MCP_CONFIG)}
    _load_quietly("mcp-config", path)

    second = migrate_file(path)
    assert second == MigrationResult(path=path, kind="mcp-config", changed=False)
    assert path.read_text(encoding="utf-8") == after_first

    # and through the CLI: exit 0, one line per file, still nothing to do
    assert _run("migrate", str(path)) == 0
    assert path.read_text(encoding="utf-8") == after_first


@pytest.mark.parametrize(
    ("filename", "text", "kind"),
    [
        # names chosen to mislead: detection must use the content
        ("policies.yaml", MCP_CONFIG, "mcp-config"),
        ("atp-mcp.yaml", POLICIES, "policies"),
        ("config.yml", None, "regression-suite"),
    ],
)
def test_migrate_detects_kind(tmp_path: Path, filename: str, text: str | None, kind: str) -> None:
    path = tmp_path / filename
    path.write_text(text if text is not None else _suite_text(), encoding="utf-8")
    result = migrate_file(path)
    assert result.kind == kind and result.changed
    _load_quietly(kind, path)


def test_migrate_json_suite_stays_json(tmp_path: Path) -> None:
    data = yaml.safe_load(_suite_text())
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    assert migrate_file(path) == MigrationResult(path=path, kind="regression-suite", changed=True)
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated == {"version": 1, **data}
    assert next(iter(migrated)) == "version"
    _load_quietly("regression-suite", path)


def test_migrate_unknown_kind(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    unknown = tmp_path / "atp-mcp.yaml"
    unknown.write_text("name: something else\nitems: [1, 2]\n", encoding="utf-8")
    with pytest.raises(UnknownFileKindError):
        migrate_file(unknown)
    good = tmp_path / "good.yaml"
    good.write_text(POLICIES, encoding="utf-8")
    capsys.readouterr()
    assert _run("migrate", str(unknown), str(good)) == 2
    captured = capsys.readouterr()
    assert "unknown" in captured.err and str(unknown) in captured.err
    # the recognised file is still migrated, and reported on its own line
    assert [line for line in captured.out.splitlines() if line] == [
        f"migrated {good} (policies): added version: 1"
    ]
    assert unknown.read_text(encoding="utf-8") == "name: something else\nitems: [1, 2]\n"


def test_migrate_refuses_unsupported_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "atp-mcp.yaml"
    path.write_text("version: 2\n" + MCP_CONFIG, encoding="utf-8")
    with pytest.raises(
        ValueError, match=re.escape("unsupported atp-mcp.yaml version 2; this atp supports 1")
    ):
        migrate_file(path)
    assert _run("migrate", str(path)) == 2
    assert "unsupported atp-mcp.yaml version 2" in capsys.readouterr().err


def test_migrate_cli_prints_one_line_per_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mcp, pol = tmp_path / "a.yaml", tmp_path / "b.yaml"
    mcp.write_text(MCP_CONFIG, encoding="utf-8")
    pol.write_text("version: 1\n" + POLICIES, encoding="utf-8")
    capsys.readouterr()
    assert _run("migrate", str(mcp), str(pol)) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"migrated {mcp} (mcp-config): added version: 1",
        f"current  {pol} (policies): already version 1",
    ]


def test_regression_migrate_alias(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    via_alias, via_migrate = tmp_path / "alias" / "s.yaml", tmp_path / "direct" / "s.yaml"
    for p in (via_alias, via_migrate):
        p.parent.mkdir()
        p.write_text(_suite_text(), encoding="utf-8")
    capsys.readouterr()
    assert _run("regression", "migrate", str(via_alias)) == 0
    alias_out = capsys.readouterr().out
    assert _run("migrate", str(via_migrate)) == 0
    direct_out = capsys.readouterr().out
    assert alias_out == direct_out.replace("direct", "alias")
    assert alias_out.startswith(f"migrated {via_alias} (regression-suite)")
    assert via_alias.read_text(encoding="utf-8") == via_migrate.read_text(encoding="utf-8")
    _load_quietly("regression-suite", via_alias)


BOM = "﻿"


def _expected(text: str) -> dict[str, object]:
    return {"version": 1, **yaml.safe_load(text)}


def test_migrate_keeps_bom_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "atp-mcp.yaml"
    path.write_bytes((BOM + "# c\n" + MCP_CONFIG).encode("utf-8"))
    assert migrate_file(path).changed
    after = path.read_bytes().decode("utf-8")
    assert after.startswith(BOM + "# c\n# atp-mcp.yaml written by atp 0.3.2")
    assert after.count(BOM) == 1
    assert "server_name: notes   # short name" in after
    assert yaml.safe_load(after) == _expected(MCP_CONFIG)
    _load_quietly("mcp-config", path)
    # idempotent with the BOM too
    assert not migrate_file(path).changed
    assert path.read_bytes().decode("utf-8") == after


@pytest.mark.parametrize(
    "marker", ["---\n", "--- # header\n", "---   \n", "--- !!map\n", "--- !!map # tagged\n"]
)
def test_migrate_inserts_after_document_start_marker(tmp_path: Path, marker: str) -> None:
    path = tmp_path / "atp-mcp.yaml"
    path.write_text(marker + MCP_CONFIG, encoding="utf-8")
    assert migrate_file(path).changed
    after = path.read_text(encoding="utf-8")
    assert after.startswith(marker)
    assert "# atp-mcp.yaml written by atp 0.3.2 (reviewed by me)\n" in after
    assert "server_name: notes   # short name" in after
    assert yaml.safe_load(after) == _expected(MCP_CONFIG)
    _load_quietly("mcp-config", path)


def test_migrate_keeps_comments_after_tag_line(tmp_path: Path) -> None:
    path = tmp_path / "atp-mcp.yaml"
    path.write_text("# head\n!!map\n" + MCP_CONFIG, encoding="utf-8")
    assert migrate_file(path).changed
    after = path.read_text(encoding="utf-8")
    assert after.startswith("# head\n!!map\n")
    assert "server_name: notes   # short name" in after
    assert yaml.safe_load(after) == _expected(MCP_CONFIG)


FLOW_WITH_COMMENT = "{server_name: notes, upstream: {command: notes-server}}  # mine\n"


def test_migrate_refuses_rather_than_drop_comments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "atp-mcp.yaml"
    path.write_text(FLOW_WITH_COMMENT, encoding="utf-8")
    with pytest.raises(ValueError, match="comments"):
        migrate_file(path)
    assert path.read_text(encoding="utf-8") == FLOW_WITH_COMMENT
    capsys.readouterr()
    assert _run("migrate", str(path)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(path) in captured.err and "add `version: 1`" in captured.err
    assert path.read_text(encoding="utf-8") == FLOW_WITH_COMMENT


def test_migrate_rewrites_flow_mapping_without_comments(tmp_path: Path) -> None:
    text = "{server_name: notes, upstream: {command: notes-server}}\n"
    path = tmp_path / "atp-mcp.yaml"
    path.write_text(text, encoding="utf-8")
    assert migrate_file(path).changed
    after = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert after == _expected(text) and next(iter(after)) == "version"


def test_migrate_through_symlink_keeps_the_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "real" / "atp-mcp.yaml"
    target.parent.mkdir()
    target.write_text(MCP_CONFIG, encoding="utf-8")
    link = tmp_path / "link.yaml"
    try:
        link.symlink_to(target)
    except OSError:  # pragma: no cover - only on systems without symlinks
        pytest.skip("this OS cannot create symlinks")
    result = migrate_file(link)
    assert result == MigrationResult(path=link, kind="mcp-config", changed=True)
    assert link.is_symlink() and link.resolve() == target.resolve()
    assert yaml.safe_load(target.read_text(encoding="utf-8")) == _expected(MCP_CONFIG)
    assert sorted(p.name for p in target.parent.iterdir()) == ["atp-mcp.yaml"]
    # the CLI reports the path it was given
    link2 = tmp_path / "link2.yaml"
    target2 = tmp_path / "real" / "policies.yaml"
    target2.write_text(POLICIES, encoding="utf-8")
    link2.symlink_to(target2)
    capsys.readouterr()
    assert _run("migrate", str(link2)) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"migrated {link2} (policies): added version: 1"
    ]
    assert link2.is_symlink()


def test_migrate_json_keeps_json_numbers(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    path.write_text('{"delegations": [], "cases": [{"amount": 1e2, "n": 7}]}', encoding="utf-8")
    assert migrate_file(path).changed
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated == {"version": 1, "delegations": [], "cases": [{"amount": 100.0, "n": 7}]}
    assert isinstance(migrated["cases"][0]["amount"], float)


def test_migrate_json_with_bom(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    path.write_bytes((BOM + '{"delegations": [], "cases": []}').encode("utf-8"))
    assert migrate_file(path).changed
    after = path.read_bytes().decode("utf-8")
    assert after.startswith(BOM)
    assert json.loads(after[1:]) == {"version": 1, "delegations": [], "cases": []}


@pytest.mark.parametrize("value", ['"1"', "'1'", "1.0"])
def test_migrate_normalises_near_miss_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    path = tmp_path / "atp-mcp.yaml"
    path.write_text(MCP_CONFIG.replace("server_name:", f"version: {value}   # old\nserver_name:"))
    capsys.readouterr()
    assert _run("migrate", str(path)) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"migrated {path} (mcp-config): set version: 1 (was {yaml.safe_load(value)!r})"
    ]
    after = path.read_text(encoding="utf-8")
    assert "version: 1   # old\n" in after
    assert after.startswith("# atp-mcp.yaml written by atp 0.3.2 (reviewed by me)\n")
    assert "server_name: notes   # short name" in after
    raw = yaml.safe_load(after)
    assert raw["version"] == 1 and type(raw["version"]) is int
    _load_quietly("mcp-config", path)
    assert not migrate_file(path).changed


def test_migrate_normalises_json_version(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    path.write_text('{"delegations": [], "version": "1", "cases": []}', encoding="utf-8")
    assert migrate_file(path).changed
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated == {"delegations": [], "version": 1, "cases": []}
    assert list(migrated) == ["delegations", "version", "cases"]


@pytest.mark.parametrize("value", ["true", '"2"', "1.5", "2", '"1.0"'])
def test_migrate_leaves_other_bad_versions_at_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    text = f"version: {value}\n" + POLICIES
    path = tmp_path / "policies.yaml"
    path.write_text(text, encoding="utf-8")
    assert _run("migrate", str(path)) == 2
    assert "unsupported policies.yaml version" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == text

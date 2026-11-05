"""The 1.0 stability contract (docs/stability.md), held by golden files.

Every file in ``tests/compat/1.0/`` was written by ``scripts/gen_compat.py``.
These tests load each one with the current code, and compare today's output
shapes with the frozen ones key by key: same keys, same JSON types; values
may differ. ``reason-codes.txt`` may only grow. A failure here after the
freeze (Task H1) means a frozen surface changed: that needs a major version.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from atp_cli.main import main

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parent / "1.0"
CLI_JSON = ("trace-list", "policy-explain", "test", "policy-impact")
GOLDEN_FILES = (
    "atp-mcp.yaml",
    "policies.yaml",
    "regression-suite.yaml",
    "evidence-bundle.json",
    "trace-export.json",
    *(f"cli-json/{name}.json" for name in CLI_JSON),
    "reason-codes.txt",
    "http/authorize-request.json",
    "http/authorize-response.json",
)
JSON_SHAPED = (
    "evidence-bundle.json",
    "trace-export.json",
    "http/authorize-request.json",
    "http/authorize-response.json",
    *(f"cli-json/{name}.json" for name in CLI_JSON),
)


def _gen_compat() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_compat", ROOT / "scripts" / "gen_compat.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def current(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Today's code, run through the same scenario as the golden files."""
    out = tmp_path_factory.mktemp("compat-current")
    _gen_compat().generate(out)
    return out


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def assert_same_shape(golden: Any, current: Any, path: str = "$") -> None:
    """Same keys and JSON types at every level; values may differ. Arrays are
    compared element by element over their common length."""
    assert _kind(golden) == _kind(current), (
        f"{path}: frozen type {_kind(golden)}, now {_kind(current)}"
    )
    if isinstance(golden, dict):
        missing = sorted(set(golden) - set(current))
        added = sorted(set(current) - set(golden))
        assert not missing and not added, f"{path}: keys removed {missing}, keys added {added}"
        for key in golden:
            assert_same_shape(golden[key], current[key], f"{path}.{key}")
    elif isinstance(golden, list):
        for i, (g, c) in enumerate(zip(golden, current, strict=False)):
            assert_same_shape(g, c, f"{path}[{i}]")


def _run(*argv: str) -> int:
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    code = exc.value.code
    return code if isinstance(code, int) else 1


# ------------------------------------------------------------------ presence
def test_every_golden_file_is_present() -> None:
    missing = [name for name in GOLDEN_FILES if not (GOLDEN / name).is_file()]
    assert not missing, f"missing golden files: {missing}"


def test_shape_check_catches_a_renamed_field() -> None:
    golden = _json(GOLDEN / "http" / "authorize-response.json")
    renamed = json.loads(json.dumps(golden).replace('"reason_code"', '"reason"'))
    with pytest.raises(AssertionError, match="keys removed"):
        assert_same_shape(golden, renamed)


# ------------------------------------------------------------- file formats
def test_mcp_config_loads() -> None:
    from atp_adapter_mcp import load_config

    config = load_config(GOLDEN / "atp-mcp.yaml")
    assert config.version == 1
    assert config.authority is not None
    assert {t.mcp_tool for t in config.tools} >= {"write_note", "delete_note"}


def test_policy_file_loads() -> None:
    from atp_policy import PolicySetRegistry
    from atp_policy.declarative import load_policy_file

    policy_file = load_policy_file(GOLDEN / "policies.yaml")
    assert policy_file.version == 1
    registry = PolicySetRegistry.with_file(str(GOLDEN / "policies.yaml"))
    for version in ("notes-v1", "notes-v2"):
        registry.get(version)


def test_regression_suite_loads_and_still_passes(tmp_path: Path) -> None:
    from atp_evals.regression import load_suite

    suite = load_suite(GOLDEN / "regression-suite.yaml")
    assert suite.version == 1 and len(suite.cases) == 2
    report = tmp_path / "report.json"
    assert _run("test", str(GOLDEN / "regression-suite.yaml"), "--json", str(report)) == 0
    assert _json(report)["summary"]["ok"] is True


def test_evidence_bundle_verifies_and_loads() -> None:
    from atp_gateway.evidence import EvidenceBundle, verify_bundle

    data = _json(GOLDEN / "evidence-bundle.json")
    ok, detail = verify_bundle(data)
    assert ok, detail
    assert EvidenceBundle.model_validate(data).trace_format == "atp-trace/1"
    assert _run("evidence", "verify", str(GOLDEN / "evidence-bundle.json")) == 0


def test_trace_export_loads_and_its_chain_verifies() -> None:
    from atp_audit import TraceEvent, verify_events
    from atp_gateway.service import TraceView

    data = _json(GOLDEN / "trace-export.json")
    view = TraceView.model_validate(data)
    assert data["format"] == "atp-trace/1"
    events = [TraceEvent.model_validate(e) for e in data["events"]]
    report = verify_events(view.trace_id, events)
    assert report.valid, report.detail
    assert report.head_hash == data["integrity"]["head_hash"]


def test_http_authorize_request_and_response_load() -> None:
    from atp_adapter_http.client import AuthorizeResponse
    from atp_core import ActionEnvelope
    from atp_gateway.service import AuthorizationResult

    ActionEnvelope.model_validate(_json(GOLDEN / "http" / "authorize-request.json"))
    response = _json(GOLDEN / "http" / "authorize-response.json")
    AuthorizationResult.model_validate(response)
    parsed = AuthorizeResponse.model_validate(response)
    assert parsed.decision.outcome.value == "ALLOW" and parsed.execution_grant is not None


# ------------------------------------------------------------------- shapes
@pytest.mark.parametrize("name", JSON_SHAPED)
def test_json_shape_unchanged(name: str, current: Path) -> None:
    assert_same_shape(_json(GOLDEN / name), _json(current / name))


def test_reason_codes_only_grow() -> None:
    from atp_core import ReasonCode

    frozen = set((GOLDEN / "reason-codes.txt").read_text(encoding="utf-8").split())
    now = {r.value for r in ReasonCode}
    assert frozen <= now, f"reason codes removed or renamed: {sorted(frozen - now)}"


# --------------------------------------------------------------- exit codes
def test_exit_codes_atp_test(tmp_path: Path) -> None:
    suite = str(GOLDEN / "regression-suite.yaml")
    assert _run("test", suite, "--quiet") == 0
    assert _run("test", suite, "--policy-set", "notes-v2", "--quiet") == 1
    assert _run("test", str(tmp_path / "missing.yaml")) == 2


def test_exit_codes_policy_impact(capsys: pytest.CaptureFixture[str]) -> None:
    suite = str(GOLDEN / "regression-suite.yaml")
    base = ("policy", "impact", "--suite", suite, "--json")
    assert _run(*base, "--from", "notes-v1", "--to", "notes-v1", "--fail-on-widen") == 0
    # notes-v1 -> notes-v2 only narrows (ALLOW -> DENY): a report, not a failure.
    assert _run(*base, "--from", "notes-v1", "--to", "notes-v2", "--fail-on-widen") == 0
    # notes-v2 -> notes-v1 widens (DENY -> ALLOW): exit 1 under --fail-on-widen.
    assert _run(*base, "--from", "notes-v2", "--to", "notes-v1", "--fail-on-widen") == 1
    assert _run(*base, "--from", "notes-v1", "--to", "no-such-set") == 2
    capsys.readouterr()


def test_exit_codes_atp_migrate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name in ("atp-mcp.yaml", "policies.yaml", "regression-suite.yaml"):
        shutil.copyfile(GOLDEN / name, tmp_path / name)
    files = [str(tmp_path / n) for n in ("atp-mcp.yaml", "policies.yaml", "regression-suite.yaml")]
    assert _run("migrate", *files) == 0
    assert "already version 1" in capsys.readouterr().out
    for name in ("atp-mcp.yaml", "policies.yaml", "regression-suite.yaml"):
        assert (tmp_path / name).read_bytes() == (GOLDEN / name).read_bytes()
    assert _run("migrate", str(tmp_path / "missing.yaml")) == 2
    (tmp_path / "unknown.yaml").write_text("hello: world\n", encoding="utf-8")
    assert _run("migrate", str(tmp_path / "unknown.yaml")) == 2


def test_usage_errors_exit_2() -> None:
    assert _run("no-such-command") == 2
    assert _run("test") == 2

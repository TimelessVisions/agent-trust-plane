"""Layers drive a real suite server, directly (open) or behind the real ATP proxy (atp)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from atp_bench.annotations import Annotation
from atp_bench.dojo import Call, load_suite
from atp_bench.layers.atp_layer import AtpLayer, render_atp_config
from atp_bench.layers.open_layer import OpenLayer
from atp_bench.suite_server import read_journal

RATIONALE = "The prompt asks for the balance only; reading it is the whole delegation."


def _annotation() -> Annotation:
    return Annotation(
        user_task="user_task_0",
        status="ok",
        capabilities=("get_balance",),
        resource_scope=("tool:get_balance",),
        rationale=RATIONALE,
    )


def _server_argv(suite: str, journal: Path) -> list[str]:
    return [
        sys.executable, "-m", "atp_bench.suite_server",
        "--suite", suite, "--injection-task", "none", "--journal", str(journal),
    ]  # fmt: skip


def test_open_layer_allows_and_reaches(tmp_path):
    suite, journal = load_suite("banking"), tmp_path / "j.jsonl"
    with OpenLayer().open(suite, _annotation(), None, journal, tmp_path) as session:
        outcome = session.call(Call("send_money", {
            "recipient": "GB29NWBK60161331926819", "amount": 1.0,
            "subject": "x", "date": "2022-01-01",
        }))  # fmt: skip
    assert outcome.status == "ALLOWED"
    assert [c.function for c in read_journal(journal)] == ["send_money"]


def test_atp_denies_ungranted_tool_before_upstream(tmp_path):
    suite, journal = load_suite("banking"), tmp_path / "j.jsonl"
    with AtpLayer().open(suite, _annotation(), None, journal, tmp_path) as session:
        denied = session.call(Call("send_money", {
            "recipient": "GB29NWBK60161331926819", "amount": 1.0,
            "subject": "x", "date": "2022-01-01",
        }))  # fmt: skip
        granted = session.call(Call("get_balance", {}))
    assert denied.status == "DENIED"
    assert denied.detail.startswith("CAPABILITY_NOT_GRANTED")
    assert granted.status == "ALLOWED"
    assert [c.function for c in read_journal(journal)] == ["get_balance"]


def test_atp_allows_granted_call_and_reaches(tmp_path):
    suite, journal = load_suite("banking"), tmp_path / "j.jsonl"
    with AtpLayer().open(suite, _annotation(), None, journal, tmp_path) as session:
        outcome = session.call(Call("get_balance", {}))
    assert outcome.status == "ALLOWED"
    assert [c.function for c in read_journal(journal)] == ["get_balance"]


def test_atp_timeout_is_inconclusive(tmp_path, monkeypatch):
    hung = tmp_path / "hung_server.py"
    hung.write_text(
        "import time\n"
        "from mcp.server.mcpserver import MCPServer\n"
        "s = MCPServer('hung')\n"
        "@s.tool()\n"
        "def get_balance() -> str:\n"
        "    time.sleep(120)\n"
        "    return 'never'\n"
        "s.run(transport='stdio')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "atp_bench.layers.atp_layer.suite_server_argv",
        lambda suite, injection_task, journal: [sys.executable, str(hung)],
    )
    suite, journal = load_suite("banking"), tmp_path / "j.jsonl"
    with AtpLayer(timeout_s=2.0).open(suite, _annotation(), None, journal, tmp_path) as session:
        outcome = session.call(Call("get_balance", {}))
    assert outcome.status == "INCONCLUSIVE"
    assert outcome.detail.startswith("UPSTREAM_ERROR")


def test_render_config_uses_absolute_quoted_paths(tmp_path):
    suite, journal = load_suite("banking"), tmp_path / "my journal.jsonl"
    argv = _server_argv("banking", journal)
    ann = Annotation(
        user_task="user_task_0", status="ok",
        capabilities=("get_balance", "send_money"),
        resource_scope=("tool:get_balance", "dojo.banking:GB29*"),
        resource_args={"send_money": "recipient"},
        rules=({"id": "cap", "applies_to": {"tool": "dojo.banking", "action": "send_money"},
                "kind": "argument_max", "argument": "amount", "max": 100},),
        rationale=RATIONALE,
    )  # fmt: skip
    cfg, pol = render_atp_config(suite, ann, argv, tmp_path / "home")
    up = cfg["upstream"]
    assert up["command"] == sys.executable
    assert Path(up["command"]).is_absolute()
    assert str(journal) in up["args"]  # path with a space stays one argv element
    assert all(Path(a).is_absolute() for a in up["args"] if a.startswith(("/", "\\")) or ":" in a[:3])
    by_tool = {m["mcp_tool"]: m for m in cfg["tools"]}
    assert set(by_tool) == set(suite.tool_names)
    assert by_tool["send_money"]["resource_template"] == "dojo.banking:{recipient}"
    assert by_tool["get_balance"]["resource_template"] == "tool:get_balance"
    assert by_tool["send_money"]["capability"] == "dojo.banking:send_money"
    assert by_tool["send_money"]["tool"] == "dojo.banking"
    assert cfg["authority"]["capabilities"] == [
        "dojo.banking:get_balance", "dojo.banking:send_money",
    ]  # fmt: skip
    assert cfg["authority"]["resource_scope"] == list(ann.resource_scope)
    assert cfg["expose_unmapped_tools"] is False
    assert cfg["policy_set"] == "bench"
    assert pol["policy_sets"][0]["version"] == "bench"
    assert pol["policy_sets"][0]["rules"][0]["id"] == "cap"
    assert pol["policy_sets"][0]["rules"][0]["applies_to"]["tool"] == "mcp.dojo-banking"
    # both documents round-trip through ATP's own models and YAML
    from atp_adapter_mcp.config import ProxyConfig
    from atp_policy.declarative import PolicyFile

    ProxyConfig.model_validate(yaml.safe_load(yaml.safe_dump(cfg)))
    PolicyFile.model_validate(yaml.safe_load(yaml.safe_dump(pol)))


def test_render_config_refuses_argument_subset_of(tmp_path):
    import pytest

    ann = Annotation(
        user_task="user_task_0", status="ok", capabilities=("send_money",),
        resource_scope=("dojo.banking:*",), resource_args={"send_money": "recipient"},
        rules=({"id": "r", "applies_to": {"tool": "dojo.banking", "action": "send_money"},
                "kind": "argument_subset_of", "argument": "recipient", "values": ["a"]},),
        rationale=RATIONALE,
    )  # fmt: skip
    with pytest.raises(ValueError, match="argument_subset_of"):
        render_atp_config(
            load_suite("banking"), ann, _server_argv("banking", tmp_path / "j"), tmp_path / "h"
        )


def test_classify_only_policy_decisions_are_denials():
    import json

    from mcp import types

    from atp_bench.layers.atp_layer import classify

    def result(code):
        payload = {"reason_code": code, "message": "m"}
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload))],
            structured_content=payload, is_error=True,
        )  # fmt: skip

    for code in ("CAPABILITY_NOT_GRANTED", "RESOURCE_OUT_OF_SCOPE", "ACTION_DENIED_BY_POLICY",
                 "ARGUMENT_TOO_LONG", "ARGUMENT_NOT_ALLOWED", "PAYMENT_EXCEEDS_DELEGATED_AUTHORITY",
                 "DELEGATION_EXPIRED", "APPROVAL_REQUIRED_BY_POLICY", "TOOL_ARGUMENTS_INVALID"):
        assert classify(result(code)).status == "DENIED", code
    for code in ("POLICY_SET_NOT_FOUND", "TOOL_NOT_REGISTERED", "OPERATOR_KEY_REQUIRED",
                 "AGENT_CREDENTIAL_INVALID", "GRANT_EXPIRED", "EXECUTION_FAILED",
                 "TRACE_NOT_FOUND", "EVENT_TYPE_RESERVED", "UPSTREAM_ERROR", "SOMETHING_NEW"):
        assert classify(result(code)).status == "INCONCLUSIVE", code


def test_atp_missing_policy_set_is_inconclusive_not_denied(tmp_path, monkeypatch):
    import atp_bench.layers.atp_layer as mod

    real = mod.render_atp_config

    def broken(*a, **k):
        cfg, pol = real(*a, **k)
        cfg["policy_set"] = "does-not-exist"
        return cfg, pol

    monkeypatch.setattr(mod, "render_atp_config", broken)
    suite, journal = load_suite("banking"), tmp_path / "j.jsonl"
    import pytest

    # The wrapper refuses to start on an unknown policy set: a harness failure that surfaces
    # as an error from open(), never as a DENIED outcome.
    with pytest.raises(RuntimeError, match="failed to start"):
        with AtpLayer().open(suite, _annotation(), None, journal, tmp_path):
            pass
    assert read_journal(journal) == []


def test_atp_declared_rule_is_loaded_and_enforced(tmp_path):
    ann = Annotation(
        user_task="user_task_0", status="ok", capabilities=("send_money",),
        resource_scope=("dojo.banking:*",), resource_args={"send_money": "recipient"},
        rules=({"id": "short-subject",
                "applies_to": {"tool": "dojo.banking", "action": "send_money"},
                "kind": "argument_max_length", "argument": "subject", "max_length": 5},),
        rationale=RATIONALE,
    )  # fmt: skip
    suite, journal = load_suite("banking"), tmp_path / "j.jsonl"
    base = {"recipient": "GB29NWBK60161331926819", "amount": 1.0, "date": "2022-01-01"}
    with AtpLayer().open(suite, ann, None, journal, tmp_path) as session:
        too_long = session.call(Call("send_money", {**base, "subject": "far too long"}))
        fine = session.call(Call("send_money", {**base, "subject": "ok"}))
    assert too_long.status == "DENIED"
    assert too_long.detail.startswith("ARGUMENT_TOO_LONG")
    assert fine.status == "ALLOWED"
    assert [c.args["subject"] for c in read_journal(journal)] == ["ok"]

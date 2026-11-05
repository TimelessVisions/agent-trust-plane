"""Pinned ToolHive v0.55.2 Cedar policy renderer and real-binary behavior.

Each generated policy must be the strongest policy derivable from exactly the same
pre-injection annotation ATP gets. Unsupported constraints have an attributable,
versioned source URL, never a silent omission.
"""

from __future__ import annotations

import json
from pathlib import Path

from atp_bench.annotations import DEFAULT_ROOT, Annotation, load_annotations
from atp_bench.dojo import Call, load_suite
from atp_bench.layers.base import DroppedConstraint, EnvBlocked
from atp_bench.layers.toolhive_layer import ToolhiveLayer, render_toolhive_config
from atp_bench.run import run_benchmark
from atp_bench.suite_server import read_journal

RATIONALE = "test task scope is intentionally fixed to the pre-injection user request"


def _ann(**kw) -> Annotation:
    kw.setdefault("user_task", "user_task_0")
    kw.setdefault("status", "ok")
    kw.setdefault("rationale", RATIONALE)
    return Annotation.model_validate(kw)


def _policies(policy) -> list[str]:
    document = json.loads(policy.files["cedar.json"])
    assert document["version"] == "1.0"
    assert document["type"] == "cedarv1"
    assert json.loads(document["cedar"]["entities_json"]) == []
    return document["cedar"]["policies"]


def test_cedar_permits_only_annotated_tools():
    suite = load_suite("banking")
    ann = _ann(capabilities=["get_balance", "get_iban"], resource_scope=["tool:get_iban"])
    policies = _policies(render_toolhive_config(suite, ann, "http://127.0.0.1:9000/mcp"))
    assert len(policies) == 1
    assert 'resource == Tool::"get_iban"' in policies[0]
    assert 'action == Action::"call_tool"' in policies[0]
    assert "get_balance" not in "\n".join(policies)


def test_scalar_limit_rendered():
    suite = load_suite("banking")
    ann = _ann(
        capabilities=["send_money", "schedule_transaction"],
        resource_scope=["dojo.banking:UK*", "tool:schedule_transaction"],
        resource_args={"send_money": "recipient"},
        rules=[
            {
                "id": "max",
                "applies_to": {"tool": "dojo.banking", "action": "send_money"},
                "kind": "argument_max",
                "argument": "amount",
                "max": "50",
            },
            {
                "id": "min",
                "applies_to": {"tool": "dojo.banking", "action": "schedule_transaction"},
                "kind": "argument_min",
                "argument": "amount",
                "min": "2",
                "optional": True,
            },
        ],
    )
    policy = render_toolhive_config(suite, ann, "http://127.0.0.1:9/mcp")
    statements = "\n".join(_policies(policy))
    assert "resource.arg_amount" in statements
    assert 'resource.arg_amount.lessThanOrEqual(decimal("50.0"))' in statements
    assert 'resource.arg_amount.greaterThanOrEqual(decimal("2.0"))' in statements
    assert "resource has arg_amount" in statements


def test_list_subset_dropped_with_doc_url():
    suite = load_suite("banking")
    ann = _ann(
        capabilities=["send_money"],
        resource_scope=["tool:send_money"],
        rules=[
            {
                "id": "recipients",
                "applies_to": {"tool": "dojo.banking", "action": "send_money"},
                "kind": "argument_subset_of",
                "argument": "recipients",
                "values": ["Alice", "Bob"],
            }
        ],
    )
    policy = render_toolhive_config(suite, ann, "http://127.0.0.1:9/mcp")
    assert policy.dropped
    d = next((x for x in policy.dropped if x.source == "recipients"), None)
    assert isinstance(d, DroppedConstraint)
    assert "complex" in d.reason.lower() or "list" in d.reason.lower()
    assert d.doc_url.startswith("https://github.com/stacklok/toolhive/blob/v0.55.2/")


def test_trailing_star_becomes_like():
    suite = load_suite("banking")
    ann = _ann(
        capabilities=["send_money"],
        resource_scope=["dojo.banking:UK*"],
        resource_args={"send_money": "recipient"},
    )
    policies = _policies(render_toolhive_config(suite, ann, "http://127.0.0.1:9/mcp"))
    assert len(policies) == 1
    assert 'resource.arg_recipient like "UK*"' in policies[0]


def test_layer_e2e_or_env_blocked(tmp_path: Path):
    """Real ToolHive when runnable; otherwise verify the explicit ENV_BLOCKED status."""
    suite = load_suite("banking")
    ann = load_annotations(DEFAULT_ROOT, "banking")["user_task_0"]
    layer = ToolhiveLayer()
    journal = tmp_path / "journal.jsonl"
    try:
        context = layer.open(suite, ann, None, journal, tmp_path / "work")
        session = context.__enter__()
    except EnvBlocked as exc:
        assert exc.reason
        result = run_benchmark(
            [layer],
            ["banking"],
            tmp_path / "result",
            user_tasks=["user_task_0"],
            injections_per_task=0,
            require_preregistration=False,
        )
        assert {item.status for item in result.results} == {"ENV_BLOCKED"}
        assert all(item.detail for item in result.results)
        return

    try:
        allowed = session.call(Call("read_file", {"file_path": "bill-december-2023.txt"}))
        denied = session.call(Call("update_password", {"password": "x"}))
    finally:
        context.__exit__(None, None, None)
    assert allowed.status == "ALLOWED", allowed
    assert denied.status == "DENIED", denied
    assert [c.function for c in read_journal(journal)] == ["read_file"]

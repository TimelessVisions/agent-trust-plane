"""Pinned ToolHive v0.55.2 Cedar policy renderer and real-binary behavior.

Each generated policy must be the strongest policy derivable from exactly the same
pre-injection annotation ATP gets. Unsupported constraints have an attributable,
versioned source URL, never a silent omission.
"""

from __future__ import annotations

import json
import os
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
    ann = _ann(capabilities=["send_money", "read_file"], resource_scope=["tool:read_file"])
    policies = _policies(render_toolhive_config(suite, ann, "http://127.0.0.1:9000/mcp"))
    assert len(policies) == 1
    assert 'resource == Tool::"read_file"' in policies[0]
    assert 'action == Action::"call_tool"' in policies[0]
    assert "send_money" not in "\n".join(policies)


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
        print(f"ENV_BLOCKED: {exc.reason}")
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

    send = {"subject": "s", "date": "2022-01-01"}
    try:
        allowed = session.call(Call("read_file", {"file_path": "bill-december-2023.txt"}))
        paid = session.call(
            Call(
                "send_money",
                {"recipient": "UK12345678901234567890", "amount": 98.7, **send},
            )
        )
        over_limit = session.call(
            Call(
                "send_money",
                {"recipient": "UK12345678901234567890", "amount": 99, **send},
            )
        )
        wrong_recipient = session.call(
            Call("send_money", {"recipient": "UK00000000000000000000", "amount": 1, **send})
        )
        denied = session.call(Call("update_password", {"password": "x"}))
    finally:
        context.__exit__(None, None, None)
    assert allowed.status == "ALLOWED", allowed
    assert paid.status == "ALLOWED", paid
    assert over_limit.status == "DENIED", over_limit
    assert wrong_recipient.status == "DENIED", wrong_recipient
    assert denied.status == "DENIED", denied
    recorded = [c.function for c in read_journal(journal)]
    assert recorded == ["read_file", "send_money"], recorded
    if proof := os.environ.get("ATP_D3_E2E_PROOF"):
        Path(proof).write_text(
            json.dumps(
                {
                    "toolhive": "v0.55.2",
                    "allowed_statuses": [allowed.status, paid.status],
                    "denied_statuses": [
                        over_limit.status,
                        wrong_recipient.status,
                        denied.status,
                    ],
                    "journal_functions": recorded,
                }
            )
            + "\n",
            encoding="utf-8",
        )


def test_cedar_numeric_resource_id_has_decimal_alternative():
    suite = load_suite("banking")
    ann = _ann(
        capabilities=["update_scheduled_transaction"],
        resource_scope=["dojo.banking:7"],
        resource_args={"update_scheduled_transaction": "id"},
    )
    policies = _policies(render_toolhive_config(suite, ann, "http://127.0.0.1:9/mcp"))
    assert len(policies) == 1
    assert 'resource.arg_id == "7"' in policies[0]
    assert 'resource.arg_id == decimal("7.0")' in policies[0]


def test_explicit_deny_removes_permit():
    suite = load_suite("banking")
    ann = _ann(
        capabilities=["send_money"],
        resource_scope=["tool:send_money"],
        rules=[
            {
                "id": "deny",
                "kind": "deny",
                "applies_to": {"tool": "dojo.banking", "action": "send_money"},
            }
        ],
    )
    policies = _policies(render_toolhive_config(suite, ann, "http://127.0.0.1:9/mcp"))
    assert policies == ['forbid(principal, action == Action::"call_tool", resource);']


def test_all_preinjection_annotations_render_with_versioned_drop_refs():
    for name in ("workspace", "travel", "banking", "slack"):
        suite = load_suite(name)
        for ann in load_annotations(DEFAULT_ROOT, name).values():
            if ann.status != "ok":
                continue
            policy = render_toolhive_config(suite, ann, "http://127.0.0.1:9/mcp")
            assert _policies(policy), (name, ann.user_task)
            for dropped in policy.dropped:
                assert dropped.source and dropped.reason
                assert dropped.doc_url.startswith(
                    "https://github.com/stacklok/toolhive/blob/v0.55.2/"
                )

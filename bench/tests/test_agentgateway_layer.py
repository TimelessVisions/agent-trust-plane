"""agentgateway v1.6.0 layer: rendered policy, dropped constraints, and the real binary.

Ruling (D2): agentgateway 1.6.0 CEL in ``mcpAuthorization`` CAN see tool arguments, through
``json(request.body).params.arguments`` (``request.body`` is the raw MCP request the gateway
kept for authorization). ``mcp.tool.arguments`` itself is NOT populated at authorization time
(issue #2069). The renderer therefore enforces argument rules and resource scope, contrary to
the plan's assumption that they must be dropped. These tests pin that behaviour against the
real binary.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from atp_bench.annotations import DEFAULT_ROOT, Annotation, load_annotations
from atp_bench.dojo import Call, load_suite
from atp_bench.layers import EnvBlocked
from atp_bench.layers.agentgateway_layer import (
    DOC_URLS,
    AgentgatewayLayer,
    classify,
    classify_error,
    render_agentgateway_config,
)
from atp_bench.layers.base import DroppedConstraint, RenderedPolicy
from atp_bench.run import run_benchmark
from atp_bench.suite_server import read_journal
from mcp import types
from mcp.shared.exceptions import MCPError

RATIONALE = "test annotation written for the agentgateway layer tests"
# The real deny response of agentgateway v1.6.0, captured from the binary on 2026-11-05
# (POST /mcp tools/call for a tool the mcpAuthorization rules do not allow):
#   {"jsonrpc":"2.0","id":2,"error":{"code":-32602,"message":"Unknown tool: update_password"}}
# Source: crates/agentgateway/src/mcp/mcp_tests.rs, authorization_denied_returns_unknown_tool_error.
DENY_CODE = -32602


def _rules(policy: RenderedPolicy) -> list[str]:
    doc = yaml.safe_load(policy.files["config.yaml"])
    return doc["mcp"]["policies"]["mcpAuthorization"]["rules"]


def _ann(**kw) -> Annotation:
    kw.setdefault("user_task", "user_task_0")
    kw.setdefault("status", "ok")
    kw.setdefault("rationale", RATIONALE)
    return Annotation.model_validate(kw)


def test_render_allows_only_annotated_tools():
    suite = load_suite("banking")
    ann = load_annotations(DEFAULT_ROOT, "banking")["user_task_0"]
    policy = render_agentgateway_config(suite, ann, "http://127.0.0.1:9/mcp", 4000)
    doc = yaml.safe_load(policy.files["config.yaml"])
    assert doc["mcp"]["port"] == 4000
    assert doc["mcp"]["targets"] == [{"name": "dojo", "mcp": {"host": "http://127.0.0.1:9/mcp"}}]
    rules = _rules(policy)
    named = {r.split('"')[1] for r in rules}
    assert all(r.startswith('mcp.tool.name == "') for r in rules)
    assert named == set(ann.capabilities)
    for tool in set(suite.tool_names) - set(ann.capabilities):
        assert f'"{tool}"' not in policy.files["config.yaml"]
    # send_money's recipient is the scoped resource argument and must be enforced from the body.
    (send,) = [r for r in rules if r.startswith('mcp.tool.name == "send_money"')]
    assert "json(request.body).params" in send and "UK12345678901234567890" in send

    # A capability whose tool:<name> resource is outside resource_scope is not granted at all:
    # ATP's kernel would deny every call to it.
    narrow = _ann(capabilities=["get_balance", "get_iban"], resource_scope=["tool:get_iban"])
    named = {r.split('"')[1] for r in _rules(render_agentgateway_config(suite, narrow, "u", 1))}
    assert named == {"get_iban"}


def test_argument_rules_listed_as_dropped():
    """Argument rules are NOT dropped in 1.6.0 (see the module ruling); only what CEL over the
    request body cannot express exactly is, each with its source rule id, reason and doc URL."""
    suite = load_suite("banking")
    for name in ("banking", "slack", "travel", "workspace"):
        s = load_suite(name)
        for ann in load_annotations(DEFAULT_ROOT, name).values():
            if ann.status != "ok":
                continue
            policy = render_agentgateway_config(s, ann, "http://127.0.0.1:9/mcp", 4000)
            # Every rule kind the 1.0 annotations use is expressible: nothing is dropped.
            assert policy.dropped == [], (name, ann.user_task, policy.dropped)

    ann = _ann(
        capabilities=["send_money", "update_password"],
        resource_scope=["tool:send_money", "tool:update_password"],
        rules=[
            {"id": "cap-amount", "applies_to": {"tool": "dojo.banking", "action": "send_money"},
             "kind": "argument_max", "argument": "amount", "max": "50"},
            {"id": "subject-len", "applies_to": {"tool": "dojo.banking", "action": "send_money"},
             "kind": "argument_max_length", "argument": "subject", "max_length": 10},
        ],
    )  # fmt: skip
    policy = render_agentgateway_config(suite, ann, "http://127.0.0.1:9/mcp", 4000)
    (send,) = [r for r in _rules(policy) if '"send_money"' in r]
    assert "n - n == 0.0 && n <= 50.0" in send  # finite, as ATP's _to_decimal requires
    assert "size(a.subject) <= 10" in send
    (dropped,) = policy.dropped
    assert isinstance(dropped, DroppedConstraint)
    assert dropped.source == "subject-len"
    assert "canonical JSON" in dropped.reason
    assert dropped.doc_url in DOC_URLS.values()
    assert dropped.doc_url.startswith("https://github.com/agentgateway/agentgateway/blob/v1.6.0/")


def test_layer_denies_ungranted_tool_before_upstream(tmp_path):
    suite = load_suite("banking")
    ann = load_annotations(DEFAULT_ROOT, "banking")["user_task_0"]
    layer = AgentgatewayLayer(timeout_s=30)
    journal = tmp_path / "journal.jsonl"
    try:
        cm = layer.open(suite, ann, None, journal, tmp_path / "work")
        session = cm.__enter__()
    except EnvBlocked as exc:
        # The binary cannot run here: the layer says so, and the runner records ENV_BLOCKED
        # for every item (never DENIED). This branch is a real outcome, not a pass by default.
        assert exc.reason
        out = run_benchmark([layer], ["banking"], tmp_path / "out", user_tasks=["user_task_0"],
                            injections_per_task=0, require_preregistration=False)  # fmt: skip
        assert {r.status for r in out.results} == {"ENV_BLOCKED"}
        return
    try:
        granted = Call("read_file", {"file_path": "bill-december-2023.txt"})
        ungranted = Call("update_password", {"password": "hunter2"})
        wrong_recipient = Call(
            "send_money",
            {"recipient": "US133000000121212121212", "amount": 98.7, "subject": "x",
             "date": "2022-01-01"},
        )  # fmt: skip
        right = Call(
            "send_money",
            {"recipient": "UK12345678901234567890", "amount": 98.7, "subject": "x",
             "date": "2022-01-01"},
        )  # fmt: skip
        assert session.call(granted).status == "ALLOWED"
        denied = session.call(ungranted)
        assert denied.status == "DENIED", denied
        assert str(DENY_CODE) in denied.detail and "update_password" in denied.detail
        assert session.call(wrong_recipient).status == "DENIED"
        assert session.call(right).status == "ALLOWED"
    finally:
        cm.__exit__(None, None, None)
    reached = read_journal(journal)
    assert [c.function for c in reached] == ["read_file", "send_money"]
    assert reached[1].args["recipient"] == "UK12345678901234567890"


def test_denial_classification():
    call = Call("update_password", {"password": "x"})
    deny = MCPError(DENY_CODE, "Unknown tool: update_password")
    assert classify_error(deny, call).status == "DENIED"
    # Same code, another tool's name, or another code: not a policy decision we can attribute.
    assert classify_error(MCPError(DENY_CODE, "Unknown tool: send_money"), call).status == (
        "INCONCLUSIVE"
    )
    assert classify_error(MCPError(-32603, "upstream failed"), call).status == "INCONCLUSIVE"
    assert classify_error(TimeoutError("slow"), call).status == "INCONCLUSIVE"
    # Results that came back are let through, as in the ATP layer: an upstream tool error
    # (is_error) still reached the upstream.
    ok = types.CallToolResult(content=[types.TextContent(type="text", text="1810.0")])
    err = types.CallToolResult(content=[types.TextContent(type="text", text="boom")], is_error=True)
    assert classify(ok).status == "ALLOWED"
    assert classify(err).status == "ALLOWED"


def test_dropped_count_in_summary(tmp_path):
    """summary.md prints each layer's dropped-constraint count (render only, no binary)."""
    root = tmp_path / "ann"
    root.mkdir()
    (root / "banking.yaml").write_text(yaml.safe_dump([{
        "user_task": "user_task_0", "status": "ok", "capabilities": ["send_money"],
        "resource_scope": ["tool:send_money"], "rationale": RATIONALE,
        "rules": [{"id": "len", "applies_to": {"tool": "dojo.banking", "action": "send_money"},
                   "kind": "argument_max_length", "argument": "subject", "max_length": 5}],
    }]), encoding="utf-8")  # fmt: skip

    class Blocked(AgentgatewayLayer):
        def open(self, *a, **kw):
            raise EnvBlocked("test: no binary")

    out = run_benchmark([Blocked()], ["banking"], tmp_path / "out", user_tasks=["user_task_0"],
                        injections_per_task=0, require_preregistration=False,
                        annotations_root=root)  # fmt: skip
    md = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    assert "dropped constraints: 1" in md
    assert out.dropped["agentgateway"] == 1
    raw = json.loads((tmp_path / "out" / "dropped.json").read_text(encoding="utf-8"))
    assert raw["agentgateway"][0]["source"] == "len"
    assert Path(raw["agentgateway"][0]["doc_url"]).name


def test_rendered_rules_match_atp_semantics_on_binary(tmp_path):
    """Each rule kind, rendered to CEL, decides like ATP's DeclaredRule on the real binary."""
    suite = load_suite("banking")
    b = {"tool": "dojo.banking"}
    ann = _ann(
        capabilities=["send_money", "schedule_transaction", "update_scheduled_transaction",
                      "update_user_info", "get_most_recent_transactions", "get_balance"],
        resource_scope=["dojo.banking:UK1*", "tool:schedule_transaction",
                        "tool:update_scheduled_transaction", "tool:update_user_info",
                        "tool:get_most_recent_transactions"],
        resource_args={"send_money": "recipient"},
        rules=[
            {"id": "r1", "applies_to": {**b, "action": "send_money"}, "kind": "argument_max",
             "argument": "amount", "max": "50"},
            {"id": "r2", "applies_to": {**b, "action": "schedule_transaction"},
             "kind": "argument_allowed_values", "argument": "recurring", "values": [True]},
            {"id": "r3", "applies_to": {**b, "action": "update_scheduled_transaction"},
             "kind": "argument_min", "argument": "amount", "min": "1", "optional": True},
            {"id": "r4", "applies_to": {**b, "action": "update_user_info"},
             "kind": "argument_forbidden", "arguments": ["first_name"]},
            {"id": "r5", "applies_to": {**b, "action": "update_user_info"},
             "kind": "argument_required", "arguments": ["city"]},
            {"id": "r6", "applies_to": {**b, "action": "update_user_info"},
             "kind": "argument_subset_of", "argument": "street", "values": ["a", "b"],
             "optional": True},
            {"id": "r7", "applies_to": {**b, "action": "get_most_recent_transactions"},
             "kind": "argument_allowed_values", "argument": "n", "values": [5]},
        ],
    )  # fmt: skip
    send = {"subject": "s", "date": "2022-01-01"}
    sched = {"recipient": "x", "amount": 1.0, "subject": "s", "date": "2022-01-01"}
    cases = [
        (Call("get_balance", {}), "DENIED"),  # tool:get_balance is out of scope
        (Call("send_money", {"recipient": "UK12", "amount": 50, **send}), "ALLOWED"),
        (Call("send_money", {"recipient": "UK12", "amount": "49.5", **send}), "ALLOWED"),
        (Call("send_money", {"recipient": "UK12", "amount": 50.01, **send}), "DENIED"),
        (Call("send_money", {"recipient": "US12", "amount": 1, **send}), "DENIED"),
        (Call("send_money", {"recipient": "UK1*", "amount": 1, **send}), "DENIED"),
        (Call("send_money", {"amount": 1, **send}), "DENIED"),
        (Call("send_money", {"recipient": "UK12", "amount": "lots", **send}), "DENIED"),
        # ATP's _to_decimal rejects infinities and NaN; Decimal trims and takes 1_0.
        (Call("send_money", {"recipient": "UK12", "amount": "-inf", **send}), "DENIED"),
        (Call("send_money", {"recipient": "UK12", "amount": "-Infinity", **send}), "DENIED"),
        (Call("send_money", {"recipient": "UK12", "amount": "NaN", **send}), "DENIED"),
        (Call("send_money", {"recipient": "UK12", "amount": " 50 ", **send}), "ALLOWED"),
        (Call("send_money", {"recipient": "UK12", "amount": "1_0", **send}), "ALLOWED"),
        (Call("send_money", {"recipient": "UK12", "amount": "1__0", **send}), "DENIED"),
        (Call("send_money", {"recipient": "UK12", "amount": True, **send}), "DENIED"),
        # Resource id validity (RESOURCE_PATTERN): <= 255 code points, no control characters.
        (Call("send_money", {"recipient": "UK1\u0001", "amount": 1, **send}), "DENIED"),
        (Call("send_money", {"recipient": "UK1\n", "amount": 1, **send}), "DENIED"),
        (Call("send_money", {"recipient": "UK1" + "\u00e9" * 252, "amount": 1, **send}), "ALLOWED"),
        (Call("send_money", {"recipient": "UK1" + "\u00e9" * 253, "amount": 1, **send}), "DENIED"),
        (Call("schedule_transaction", {**sched, "recurring": True}), "ALLOWED"),
        (Call("schedule_transaction", {**sched, "recurring": False}), "DENIED"),
        (Call("schedule_transaction", {**sched, "recurring": 1}), "DENIED"),
        (Call("update_scheduled_transaction", {"id": 7}), "ALLOWED"),
        (Call("update_scheduled_transaction", {"id": 7, "amount": None}), "ALLOWED"),
        (Call("update_scheduled_transaction", {"id": 7, "amount": 0.5}), "DENIED"),
        (Call("update_scheduled_transaction", {"id": 7, "amount": "inf"}), "DENIED"),
        (Call("update_scheduled_transaction", {"id": 7, "amount": "NaN"}), "DENIED"),
        (Call("update_user_info", {"city": "c"}), "ALLOWED"),
        (Call("update_user_info", {"city": None}), "DENIED"),
        (Call("update_user_info", {"city": "c", "first_name": None}), "DENIED"),
        (Call("update_user_info", {"city": "c", "street": ["a", "b"]}), "ALLOWED"),
        (Call("update_user_info", {"city": "c", "street": "b"}), "ALLOWED"),
        (Call("update_user_info", {"city": "c", "street": ["a", "c"]}), "DENIED"),
        (Call("get_most_recent_transactions", {"n": 5}), "ALLOWED"),
        (Call("get_most_recent_transactions", {"n": 5.5}), "DENIED"),
        (Call("get_most_recent_transactions", {"n": "5"}), "DENIED"),
    ]
    journal = tmp_path / "journal.jsonl"
    try:
        cm = AgentgatewayLayer().open(suite, ann, None, journal, tmp_path / "work")
        session = cm.__enter__()
    except EnvBlocked as exc:  # the binary cannot run here; nothing to compare against
        assert exc.reason
        return
    try:
        got = [(c.function, c.args, session.call(c).status) for c, _ in cases]
    finally:
        cm.__exit__(None, None, None)
    assert [g[2] for g in got] == [want for _, want in cases], got
    allowed = [c.function for c, want in cases if want == "ALLOWED"]
    assert [c.function for c in read_journal(journal)] == allowed


def test_resource_ids_and_unicode_match_atp_on_binary(tmp_path):
    """'<type>:*' still applies ATP's resource id grammar; string lengths count code points;
    non-ASCII (non-BMP) allowed values match exactly."""
    suite = load_suite("banking")
    b = {"tool": "dojo.banking"}
    ann = _ann(
        capabilities=["send_money", "update_user_info"],
        resource_scope=["dojo.banking:*", "tool:update_user_info"],
        resource_args={"send_money": "recipient"},
        rules=[
            {"id": "l1", "applies_to": {**b, "action": "send_money"},
             "kind": "argument_max_length", "argument": "subject", "max_length": 3},
            {"id": "v1", "applies_to": {**b, "action": "update_user_info"},
             "kind": "argument_allowed_values", "argument": "city", "values": ["\U0001f600x"]},
        ],
    )  # fmt: skip
    send = {"amount": 1, "date": "2022-01-01"}
    cases = [
        (Call("send_money", {"recipient": "", "subject": "s", **send}), "DENIED"),
        (Call("send_money", {"recipient": "a*", "subject": "s", **send}), "DENIED"),
        (Call("send_money", {"recipient": "a\u007f", "subject": "s", **send}), "DENIED"),
        (Call("send_money", {"recipient": "\u00e9" * 255, "subject": "s", **send}), "ALLOWED"),
        (Call("send_money", {"recipient": "\u00e9" * 256, "subject": "s", **send}), "DENIED"),
        (Call("send_money", {"recipient": 12, "subject": "s", **send}), "ALLOWED"),
        (
            Call("send_money", {"recipient": "US1", "subject": "\u00e9\u00e9\u00e9", **send}),
            "ALLOWED",
        ),
        (Call("send_money", {"recipient": "US1", "subject": "\U0001f600" * 3, **send}), "ALLOWED"),
        (Call("send_money", {"recipient": "US1", "subject": "a\nb", **send}), "ALLOWED"),
        (Call("send_money", {"recipient": "US1", "subject": "abcd", **send}), "DENIED"),
        (Call("update_user_info", {"city": "\U0001f600x"}), "ALLOWED"),
        (Call("update_user_info", {"city": "x"}), "DENIED"),
    ]
    journal = tmp_path / "journal.jsonl"
    try:
        cm = AgentgatewayLayer().open(suite, ann, None, journal, tmp_path / "work")
        session = cm.__enter__()
    except EnvBlocked as exc:
        assert exc.reason
        return
    try:
        got = [(c.function, c.args, session.call(c).status) for c, _ in cases]
    finally:
        cm.__exit__(None, None, None)
    assert [g[2] for g in got] == [want for _, want in cases], got


def test_resource_guard_in_every_scope_branch():
    """'*', '<type>:*', exact and prefix scopes all carry the resource id guard."""
    suite = load_suite("banking")
    for scope in (["*"], ["dojo.banking:*"], ["dojo.banking:US1"], ["dojo.banking:US*"]):
        ann = _ann(capabilities=["send_money"], resource_scope=scope,
                   resource_args={"send_money": "recipient"})  # fmt: skip
        (rule,) = _rules(render_agentgateway_config(suite, ann, "http://127.0.0.1:9/mcp", 4000))
        assert "matches(" in rule and "x1f" in rule and "{1,255}" in rule, (scope, rule)


def test_long_max_length_is_byte_approximation():
    suite = load_suite("banking")
    ann = _ann(
        capabilities=["send_money"], resource_scope=["tool:send_money"],
        rules=[{"id": "big", "applies_to": {"tool": "dojo.banking", "action": "send_money"},
                "kind": "argument_max_length", "argument": "subject", "max_length": 20000}],
    )  # fmt: skip
    policy = render_agentgateway_config(suite, ann, "http://127.0.0.1:9/mcp", 4000)
    (dropped,) = policy.dropped
    assert "enforced on UTF-8 bytes (stricter for non-ASCII)" in dropped.reason

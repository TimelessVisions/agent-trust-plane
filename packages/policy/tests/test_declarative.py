"""Declarative policy sets: loading, evaluation, and the kernel policies that
a file can never switch off."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from atp_core import (
    ActionEnvelope,
    AuthorityConstraints,
    DecisionOutcome,
    EffectiveAuthority,
    PrincipalKind,
    PrincipalRef,
    ReasonCode,
)
from atp_policy import (
    PolicyContext,
    PolicyEngine,
    PolicyFile,
    PolicySetRegistry,
    build_policy_set,
    load_policy_sets,
)

from policy_fixtures import HUMAN, NOW, usd, vendors

AGENT = PrincipalRef(id="notes-assistant", kind=PrincipalKind.AGENT)


def authority(*caps: str, scope: tuple[str, ...] = ("note:*",)) -> EffectiveAuthority:
    return EffectiveAuthority(
        root_principal=HUMAN,
        holder=AGENT,
        grant_chain=("grt_root", "grt_leaf"),
        capabilities=frozenset(caps),
        resource_scope=scope,
        constraints=AuthorityConstraints(max_amount=usd(1000)),
        expires_at=NOW + timedelta(days=1),
    )


def ctx(
    tool: str = "mcp.notes",
    action: str = "write_note",
    capability: str = "notes:write",
    resource: str = "note:todo",
    arguments: dict[str, Any] | None = None,
    auth: EffectiveAuthority | None = None,
) -> PolicyContext:
    env = ActionEnvelope(
        principal=HUMAN,
        agent=AGENT,
        delegation_grant_id="grt_leaf",
        capability=capability,
        tool=tool,
        action=action,
        resource=resource,
        arguments=arguments or {},
    )
    return PolicyContext(
        envelope=env,
        vendors=vendors(),
        now=NOW,
        authority=auth if auth is not None else authority("notes:write", "notes:read"),
    )


FILE: dict[str, Any] = {
    "version": 1,
    "policy_sets": [
        {
            "version": "notes-v1",
            "description": "notes assistant",
            "rules": [
                {
                    "id": "short-notes",
                    "applies_to": {"tool": "mcp.notes", "action": "write_note"},
                    "kind": "argument_max_length",
                    "argument": "text",
                    "max_length": 20,
                },
                {
                    "id": "no-delete",
                    "applies_to": {"tool": "mcp.notes", "action": "delete_note"},
                    "kind": "deny",
                },
                {
                    "id": "priority-range",
                    "applies_to": {"tool": "mcp.notes"},
                    "kind": "argument_max",
                    "argument": "priority",
                    "max": 5,
                    "optional": True,
                },
                {
                    "id": "known-tags",
                    "applies_to": {"tool": "mcp.notes", "action": "write_note"},
                    "kind": "argument_allowed_values",
                    "argument": "tag",
                    "values": ["work", "home"],
                    "optional": True,
                },
                {
                    "id": "no-raw-path",
                    "applies_to": {"tool": "*"},
                    "kind": "argument_forbidden",
                    "arguments": ["path"],
                },
                {
                    "id": "archive-needs-approval",
                    "applies_to": {"tool": "mcp.notes", "action": "archive"},
                    "kind": "require_approval",
                    "approver_role": "owner",
                },
            ],
        }
    ],
}


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    p = tmp_path / "policies.yaml"
    p.write_text(yaml.safe_dump(FILE), encoding="utf-8")
    return p


class TestLoading:
    def test_loads_and_contains_kernel_policies(self, policy_file: Path) -> None:
        (ps,) = load_policy_sets(policy_file)
        ids = [p.id for p in ps.policies]
        assert ids[:3] == ["delegation.valid", "capability.required", "resource.scope"]
        assert "rule.short-notes" in ids

    def test_registry_with_file_keeps_builtins(self, policy_file: Path) -> None:
        reg = PolicySetRegistry.with_file(policy_file, default_version="notes-v1")
        assert {s.version for s in reg.versions()} == {"payments-v1", "payments-v2", "notes-v1"}
        assert reg.default_version == "notes-v1"

    def test_cannot_shadow_builtin(self, tmp_path: Path) -> None:
        data = {"version": 1, "policy_sets": [{"version": "payments-v2", "rules": []}]}
        p = tmp_path / "p.yaml"
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
        with pytest.raises(ValueError, match="shadows a built-in"):
            PolicySetRegistry.with_file(p)

    @pytest.mark.parametrize(
        "rule",
        [
            {"id": "x", "applies_to": {"tool": "t"}, "kind": "argument_max", "argument": "a"},
            {
                "id": "x",
                "applies_to": {"tool": "t"},
                "kind": "argument_max_length",
                "argument": "a",
            },
            {"id": "x", "applies_to": {"tool": "t"}, "kind": "argument_required"},
            {"id": "x", "applies_to": {"tool": "t"}, "kind": "argument_max", "max": 1},
            {
                "id": "x",
                "applies_to": {"tool": "t"},
                "kind": "argument_max",
                "argument": "a",
                "max": "NaN",
            },
            {"id": "x", "applies_to": {"tool": "t"}, "kind": "regex", "argument": "a"},
            {"id": "x", "applies_to": {"tool": "t"}, "kind": "deny", "extra": 1},
            {"id": "bad id!", "applies_to": {"tool": "t"}, "kind": "deny"},
        ],
    )
    def test_malformed_rules_rejected(self, rule: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            PolicyFile.model_validate(
                {"version": 1, "policy_sets": [{"version": "v", "rules": [rule]}]}
            )

    def test_duplicate_rule_ids_rejected(self) -> None:
        rule = {"id": "same", "applies_to": {"tool": "t"}, "kind": "deny"}
        with pytest.raises(ValueError, match="duplicate rule id"):
            PolicyFile.model_validate(
                {"version": 1, "policy_sets": [{"version": "v", "rules": [rule, rule]}]}
            )

    def test_unknown_top_level_keys_rejected(self) -> None:
        with pytest.raises(ValueError):
            PolicyFile.model_validate({"version": 1, "policy_sets": [], "default_allow": True})


class TestEvaluation:
    def _set(self, policy_file: Path) -> Any:
        (ps,) = load_policy_sets(policy_file)
        return ps

    def test_allow_when_all_rules_pass(self, policy_file: Path) -> None:
        d = PolicyEngine().evaluate(self._set(policy_file), ctx(arguments={"text": "buy milk"}))
        assert d.outcome is DecisionOutcome.ALLOW
        assert [e.policy.id for e in d.evaluations] == [
            "delegation.valid",
            "capability.required",
            "resource.scope",
            "rule.short-notes",
            "rule.priority-range",
            "rule.known-tags",
            "rule.no-raw-path",
        ]

    def test_max_length_denies_with_constraint(self, policy_file: Path) -> None:
        d = PolicyEngine().evaluate(self._set(policy_file), ctx(arguments={"text": "x" * 21}))
        assert d.outcome is DecisionOutcome.DENY
        assert d.reason_code is ReasonCode.ARGUMENT_TOO_LONG
        assert d.matched_policy is not None and d.matched_policy.id == "rule.short-notes"
        c = next(e for e in d.evaluations if e.policy.id == "rule.short-notes").constraints[0]
        assert (c.requested, c.limit, c.satisfied) == (21, 20, False)

    def test_deny_rule(self, policy_file: Path) -> None:
        d = PolicyEngine().evaluate(
            self._set(policy_file),
            ctx(action="delete_note", capability="notes:write", arguments={"id": "todo"}),
        )
        assert (d.outcome, d.reason_code) == (
            DecisionOutcome.DENY,
            ReasonCode.ACTION_DENIED_BY_POLICY,
        )

    def test_numeric_max_with_optional_argument(self, policy_file: Path) -> None:
        ok = PolicyEngine().evaluate(
            self._set(policy_file), ctx(arguments={"text": "a", "priority": 5})
        )
        assert ok.outcome is DecisionOutcome.ALLOW
        over = PolicyEngine().evaluate(
            self._set(policy_file), ctx(arguments={"text": "a", "priority": "5.01"})
        )
        assert over.reason_code is ReasonCode.ARGUMENT_EXCEEDS_LIMIT
        nan = PolicyEngine().evaluate(
            self._set(policy_file), ctx(arguments={"text": "a", "priority": "NaN"})
        )
        assert nan.reason_code is ReasonCode.ARGUMENT_INVALID
        boolean = PolicyEngine().evaluate(
            self._set(policy_file), ctx(arguments={"text": "a", "priority": True})
        )
        assert boolean.reason_code is ReasonCode.ARGUMENT_INVALID

    def test_allowed_values_are_type_strict(self, policy_file: Path) -> None:
        ok = PolicyEngine().evaluate(
            self._set(policy_file), ctx(arguments={"text": "a", "tag": "work"})
        )
        assert ok.outcome is DecisionOutcome.ALLOW
        bad = PolicyEngine().evaluate(
            self._set(policy_file), ctx(arguments={"text": "a", "tag": "Work"})
        )
        assert bad.reason_code is ReasonCode.ARGUMENT_NOT_ALLOWED
        # 1 == True in Python; the rule must not let a bool through as an int.
        rule = {
            "id": "n",
            "applies_to": {"tool": "*"},
            "kind": "argument_allowed_values",
            "argument": "n",
            "values": [1],
        }
        ps = build_policy_set(
            PolicyFile.model_validate(
                {"version": 1, "policy_sets": [{"version": "v", "rules": [rule]}]}
            ).policy_sets[0]
        )
        assert (
            PolicyEngine().evaluate(ps, ctx(arguments={"n": True})).reason_code
            is ReasonCode.ARGUMENT_NOT_ALLOWED
        )
        assert PolicyEngine().evaluate(ps, ctx(arguments={"n": 1})).outcome is DecisionOutcome.ALLOW

    def test_forbidden_argument_applies_to_every_tool(self, policy_file: Path) -> None:
        d = PolicyEngine().evaluate(
            self._set(policy_file), ctx(tool="mcp.other", action="x", arguments={"path": "/etc"})
        )
        assert d.reason_code is ReasonCode.ARGUMENT_FORBIDDEN

    def test_missing_required_argument_fails_closed(self, tmp_path: Path) -> None:
        rule = {
            "id": "needs-id",
            "applies_to": {"tool": "*"},
            "kind": "argument_required",
            "arguments": ["id"],
        }
        ps = build_policy_set(
            PolicyFile.model_validate(
                {"version": 1, "policy_sets": [{"version": "v", "rules": [rule]}]}
            ).policy_sets[0]
        )
        assert (
            PolicyEngine().evaluate(ps, ctx(arguments={})).reason_code
            is ReasonCode.ARGUMENT_MISSING
        )

    def test_non_optional_numeric_rule_denies_when_absent(self) -> None:
        rule = {
            "id": "amt",
            "applies_to": {"tool": "*"},
            "kind": "argument_max",
            "argument": "amount",
            "max": 10,
        }
        ps = build_policy_set(
            PolicyFile.model_validate(
                {"version": 1, "policy_sets": [{"version": "v", "rules": [rule]}]}
            ).policy_sets[0]
        )
        assert (
            PolicyEngine().evaluate(ps, ctx(arguments={})).reason_code
            is ReasonCode.ARGUMENT_MISSING
        )

    def test_require_approval_carries_role(self, policy_file: Path) -> None:
        d = PolicyEngine().evaluate(self._set(policy_file), ctx(action="archive", arguments={}))
        assert d.outcome is DecisionOutcome.REQUIRE_APPROVAL
        assert d.approval is not None and d.approval.approver_role == "owner"

    def test_kernel_policies_still_deny_without_capability(self, policy_file: Path) -> None:
        d = PolicyEngine().evaluate(
            self._set(policy_file), ctx(arguments={"text": "a"}, auth=authority("notes:read"))
        )
        assert d.reason_code is ReasonCode.CAPABILITY_NOT_GRANTED

    def test_kernel_policies_still_deny_out_of_scope(self, policy_file: Path) -> None:
        d = PolicyEngine().evaluate(
            self._set(policy_file),
            ctx(
                resource="note:secret",
                arguments={"text": "a"},
                auth=authority("notes:write", scope=("note:todo",)),
            ),
        )
        assert d.reason_code is ReasonCode.RESOURCE_OUT_OF_SCOPE

    def test_deterministic(self, policy_file: Path) -> None:
        a = PolicyEngine().evaluate(self._set(policy_file), ctx(arguments={"text": "x" * 21}))
        b = PolicyEngine().evaluate(self._set(policy_file), ctx(arguments={"text": "x" * 21}))
        assert (a.outcome, a.reason_code, a.matched_policy) == (
            b.outcome,
            b.reason_code,
            b.matched_policy,
        )
        assert [e.model_dump() for e in a.evaluations] == [e.model_dump() for e in b.evaluations]


def test_payments_include_reuses_builtin_policies(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "policy_sets": [{"version": "ap-v1", "include": ["payments"], "approval_threshold": "500"}],
    }
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    (ps,) = load_policy_sets(p)
    ids = {pol.id for pol in ps.policies}
    assert {"payments.vendor.max_amount", "payments.vendor.approved_destination"} <= ids
    threshold = next(pol for pol in ps.policies if pol.id == "payments.approval_threshold")
    assert str(threshold.threshold.amount) == "500"  # type: ignore[attr-defined]


# ---------------------------------------------------------- argument_subset_of
def _subset_set(optional: bool = False, values: list[Any] | None = None) -> Any:
    rule: dict[str, Any] = {
        "id": "recipients",
        "applies_to": {"tool": "mcp.notes", "action": "write_note"},
        "kind": "argument_subset_of",
        "argument": "to",
        "values": values if values is not None else ["a@x", "b@x", "c@x"],
    }
    if optional:
        rule["optional"] = True
    return build_policy_set(
        PolicyFile.model_validate(
            {"version": 1, "policy_sets": [{"version": "v", "rules": [rule]}]}
        ).policy_sets[0]
    )


def test_subset_allows_all_known() -> None:
    d = PolicyEngine().evaluate(_subset_set(), ctx(arguments={"to": ["a@x", "b@x"]}))
    assert d.outcome is DecisionOutcome.ALLOW
    empty = PolicyEngine().evaluate(_subset_set(), ctx(arguments={"to": []}))
    assert empty.outcome is DecisionOutcome.ALLOW


def test_subset_denies_one_unknown() -> None:
    d = PolicyEngine().evaluate(_subset_set(), ctx(arguments={"to": ["a@x", "evil@y"]}))
    assert d.outcome is DecisionOutcome.DENY
    assert d.reason_code is ReasonCode.ARGUMENT_NOT_ALLOWED
    assert d.matched_policy is not None and d.matched_policy.id == "rule.recipients"
    ev = next(e for e in d.evaluations if e.policy.id == "rule.recipients")
    c = ev.constraints[0]
    assert c.satisfied is False
    assert c.limit == {"allowed": ["a@x", "b@x", "c@x"], "offending": ["evil@y"]}
    assert "evil@y" in ev.message
    # case-sensitive, like argument_allowed_values
    upper = PolicyEngine().evaluate(_subset_set(), ctx(arguments={"to": ["A@x"]}))
    assert upper.outcome is DecisionOutcome.DENY


def test_subset_scalar_treated_as_list() -> None:
    ok = PolicyEngine().evaluate(_subset_set(), ctx(arguments={"to": "a@x"}))
    assert ok.outcome is DecisionOutcome.ALLOW
    bad = PolicyEngine().evaluate(_subset_set(), ctx(arguments={"to": "evil@y"}))
    assert bad.reason_code is ReasonCode.ARGUMENT_NOT_ALLOWED


def test_subset_missing_argument_denies_unless_optional() -> None:
    d = PolicyEngine().evaluate(_subset_set(), ctx(arguments={"text": "a"}))
    assert d.outcome is DecisionOutcome.DENY
    assert d.reason_code is ReasonCode.ARGUMENT_MISSING
    ok = PolicyEngine().evaluate(_subset_set(optional=True), ctx(arguments={"text": "a"}))
    assert ok.outcome is DecisionOutcome.ALLOW


def test_subset_requires_values() -> None:
    from pydantic import ValidationError

    base = {
        "id": "r",
        "applies_to": {"tool": "*"},
        "kind": "argument_subset_of",
        "argument": "to",
    }
    with pytest.raises(ValidationError, match=r"argument_subset_of needs .values."):
        PolicyFile.model_validate(
            {"version": 1, "policy_sets": [{"version": "v", "rules": [base]}]}
        )


def _subset_decide(values: list[Any], arg: Any) -> Any:
    return PolicyEngine().evaluate(_subset_set(values=values), ctx(arguments={"to": arg}))


def test_subset_is_type_strict() -> None:
    assert _subset_decide([1], [1]).outcome is DecisionOutcome.ALLOW
    assert _subset_decide([1, 2], [2, 1]).outcome is DecisionOutcome.ALLOW
    for values, arg in (
        ([1], ["1"]),
        (["1"], [1]),
        (["True"], [True]),
        ([True], ["True"]),
        ([1], [True]),
        ([True], [1]),
    ):
        d = _subset_decide(values, arg)
        assert d.outcome is DecisionOutcome.DENY, (values, arg)
        assert d.reason_code is ReasonCode.ARGUMENT_NOT_ALLOWED, (values, arg)
    assert _subset_decide([True], True).outcome is DecisionOutcome.ALLOW


def test_subset_malformed_shapes_deny_as_invalid() -> None:
    for arg in (
        [None],
        ["a@x", None],
        [{"k": "a@x"}],
        [["a@x"]],
        [1.0],
        {"k": "a@x"},
        {},
        None,
        1.5,
    ):
        d = _subset_decide(["a@x", "None", "{'k': 'a@x'}", "['a@x']", "1.0"], arg)
        assert d.outcome is DecisionOutcome.DENY, arg
        assert d.reason_code is ReasonCode.ARGUMENT_INVALID, arg


def test_subset_malformed_multibyte_does_not_raise() -> None:
    # canonical JSON keeps non-ASCII; 150 two-byte chars straddle the 200-byte mark.
    for arg in ({"k": "é" * 150}, [{"k": "é" * 150}], [["é" * 150]]):
        d = _subset_decide(["a@x"], arg)
        assert d.outcome is DecisionOutcome.DENY, arg
        assert d.reason_code is ReasonCode.ARGUMENT_INVALID, arg
        ev = next(e for e in d.evaluations if e.policy.id == "rule.recipients")
        assert len(ev.constraints[0].requested) <= 200


def test_allowed_values_multibyte_dict_argument_denies_without_raising() -> None:
    rule = {
        "id": "tag",
        "applies_to": {"tool": "*"},
        "kind": "argument_allowed_values",
        "argument": "tag",
        "values": ["work"],
    }
    ps = build_policy_set(
        PolicyFile.model_validate(
            {"version": 1, "policy_sets": [{"version": "v", "rules": [rule]}]}
        ).policy_sets[0]
    )
    d = PolicyEngine().evaluate(ps, ctx(arguments={"tag": [{"k": "é" * 150}]}))
    assert d.outcome is DecisionOutcome.DENY
    assert d.reason_code is ReasonCode.ARGUMENT_NOT_ALLOWED


_NULL_RULES: dict[str, dict[str, Any]] = {
    "argument_subset_of": {"values": ["a"]},
    "argument_allowed_values": {"values": ["a"]},
    "argument_max": {"max": 10},
    "argument_min": {"min": 1},
    "argument_max_length": {"max_length": 20},
}


@pytest.mark.parametrize("kind", sorted(_NULL_RULES))
def test_explicit_null_is_absent_only_when_optional(kind: str) -> None:
    def decide(optional: bool) -> Any:
        rule = {
            "id": "r",
            "applies_to": {"tool": "*"},
            "kind": kind,
            "argument": "x",
            "optional": optional,
            **_NULL_RULES[kind],
        }
        ps = build_policy_set(
            PolicyFile.model_validate(
                {"version": 1, "policy_sets": [{"version": "v", "rules": [rule]}]}
            ).policy_sets[0]
        )
        return PolicyEngine().evaluate(ps, ctx(arguments={"x": None}))

    assert decide(True).outcome is DecisionOutcome.ALLOW
    denied = decide(False)
    assert denied.outcome is DecisionOutcome.DENY
    if kind == "argument_max_length":
        assert denied.reason_code is ReasonCode.ARGUMENT_INVALID


def test_subset_deny_message_is_bounded() -> None:
    values = [f"v{n}@x" for n in range(500)]
    d = _subset_decide(values, ["evil@y"])
    ev = next(e for e in d.evaluations if e.policy.id == "rule.recipients")
    assert "evil@y" in ev.message and len(ev.message) < 300


def _one_rule_decide(rule: dict[str, Any], arguments: dict[str, Any]) -> Any:
    ps = build_policy_set(
        PolicyFile.model_validate(
            {"version": 1, "policy_sets": [{"version": "v", "rules": [rule]}]}
        ).policy_sets[0]
    )
    return PolicyEngine().evaluate(ps, ctx(arguments=arguments))


def test_required_denies_explicit_null() -> None:
    rule = {"id": "r", "applies_to": {"tool": "*"}, "kind": "argument_required", "arguments": ["x"]}
    d = _one_rule_decide(rule, {"x": None})
    assert d.outcome is DecisionOutcome.DENY
    assert d.reason_code is ReasonCode.ARGUMENT_MISSING
    assert "missing or null" in d.explanation
    assert _one_rule_decide(rule, {"x": "v"}).outcome is DecisionOutcome.ALLOW


def test_forbidden_denies_explicit_null() -> None:
    rule = {
        "id": "r",
        "applies_to": {"tool": "*"},
        "kind": "argument_forbidden",
        "arguments": ["x"],
    }
    d = _one_rule_decide(rule, {"x": None})
    assert d.outcome is DecisionOutcome.DENY
    assert d.reason_code is ReasonCode.ARGUMENT_FORBIDDEN
    assert _one_rule_decide(rule, {}).outcome is DecisionOutcome.ALLOW


_OUT_OF_BOUNDS: dict[str, tuple[dict[str, Any], Any, ReasonCode]] = {
    "argument_subset_of": ({"values": ["a"]}, ["a", "b"], ReasonCode.ARGUMENT_NOT_ALLOWED),
    "argument_allowed_values": ({"values": ["a"]}, "b", ReasonCode.ARGUMENT_NOT_ALLOWED),
    "argument_max": ({"max": 10}, 11, ReasonCode.ARGUMENT_EXCEEDS_LIMIT),
    "argument_min": ({"min": 1}, 0, ReasonCode.ARGUMENT_BELOW_MINIMUM),
    "argument_max_length": ({"max_length": 2}, "abc", ReasonCode.ARGUMENT_TOO_LONG),
}


@pytest.mark.parametrize("kind", sorted(_OUT_OF_BOUNDS))
def test_optional_with_out_of_bounds_value_still_denies(kind: str) -> None:
    extra, value, code = _OUT_OF_BOUNDS[kind]
    rule = {
        "id": "r",
        "applies_to": {"tool": "*"},
        "kind": kind,
        "argument": "x",
        "optional": True,
        **extra,
    }
    d = _one_rule_decide(rule, {"x": value})
    assert d.outcome is DecisionOutcome.DENY
    assert d.reason_code is code

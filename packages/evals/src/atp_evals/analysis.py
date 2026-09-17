"""Offline analyses over recorded actions: policy impact and request mutation.

Both run recorded (or derived) actions through ``/authorize`` on an ephemeral
in-process gateway. Nothing here can execute a tool: the runner never calls
``/execute``, and the ephemeral gateway's only tools are the demo ledger and
external ``mcp.*`` stubs that release to nobody.

Prior art: mutation testing of access-control *policies* (Martin & Xie,
WWW 2007; Xu et al., SACMAT 2020) mutates the policy and derives requests.
``mutate`` here does the reverse: it perturbs a recorded *request* along
high-risk dimensions and reports what the fixed policy decides, so a
developer can see holes around an action they actually observed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atp_evals.regression.format import CaseSpec, Expectation, GrantSpec, Suite
from atp_evals.regression.runner import CaseResult, decide_cases

# ---------------------------------------------------------------- impact

Transition = Literal[
    "UNCHANGED_ALLOW",
    "UNCHANGED_DENY",
    "UNCHANGED_REQUIRE_APPROVAL",
    "ALLOW_TO_DENY",
    "DENY_TO_ALLOW",
    "ALLOW_TO_REQUIRE_APPROVAL",
    "REQUIRE_APPROVAL_TO_ALLOW",
    "DENY_TO_REQUIRE_APPROVAL",
    "REQUIRE_APPROVAL_TO_DENY",
    "ERROR",
]


class ImpactRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case: str
    transition: Transition
    from_outcome: str | None
    from_reason: str | None
    to_outcome: str | None
    to_reason: str | None
    to_policy: str | None


class ImpactReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    from_version: str
    to_version: str
    rows: list[ImpactRow]

    def count(self, transition: Transition) -> int:
        return sum(1 for r in self.rows if r.transition == transition)

    @property
    def widened(self) -> list[ImpactRow]:
        """Transitions that grant more than before: the ones to look at first."""
        return [
            r
            for r in self.rows
            if r.transition
            in ("DENY_TO_ALLOW", "REQUIRE_APPROVAL_TO_ALLOW", "DENY_TO_REQUIRE_APPROVAL")
        ]


def _transition(a: CaseResult, b: CaseResult) -> Transition:
    if a.observed_outcome is None or b.observed_outcome is None:
        return "ERROR"
    if a.observed_outcome == b.observed_outcome:
        return f"UNCHANGED_{a.observed_outcome}"  # type: ignore[return-value]
    return f"{a.observed_outcome}_TO_{b.observed_outcome}"  # type: ignore[return-value]


def policy_impact(
    suite: Suite, *, from_version: str, to_version: str, policy_file: str | None = None
) -> ImpactReport:
    before = decide_cases(suite, suite.cases, policy_set=from_version, policy_file=policy_file)
    after = decide_cases(suite, suite.cases, policy_set=to_version, policy_file=policy_file)
    rows = [
        ImpactRow(
            case=a.name,
            transition=_transition(a, b),
            from_outcome=a.observed_outcome,
            from_reason=a.observed_reason,
            to_outcome=b.observed_outcome,
            to_reason=b.observed_reason,
            to_policy=b.observed_policy,
        )
        for a, b in zip(before, after, strict=True)
    ]
    return ImpactReport(from_version=from_version, to_version=to_version, rows=rows)


def format_impact(r: ImpactReport) -> str:
    w = 78
    lines = ["=" * w, f"policy impact: {r.from_version} -> {r.to_version}", "=" * w]
    order: list[Transition] = [
        "DENY_TO_ALLOW",
        "REQUIRE_APPROVAL_TO_ALLOW",
        "DENY_TO_REQUIRE_APPROVAL",
        "ALLOW_TO_DENY",
        "ALLOW_TO_REQUIRE_APPROVAL",
        "REQUIRE_APPROVAL_TO_DENY",
        "UNCHANGED_ALLOW",
        "UNCHANGED_DENY",
        "UNCHANGED_REQUIRE_APPROVAL",
        "ERROR",
    ]
    for t in order:
        rows = [x for x in r.rows if x.transition == t]
        if not rows:
            continue
        flag = (
            "  <-- authority WIDENED, review"
            if t
            in (
                "DENY_TO_ALLOW",
                "REQUIRE_APPROVAL_TO_ALLOW",
                "DENY_TO_REQUIRE_APPROVAL",
            )
            else ""
        )
        lines.append(
            f"\n{t.replace('_TO_', ' -> ').replace('UNCHANGED_', 'unchanged ')}  "
            f"({len(rows)}){flag}"
        )
        for x in rows:
            lines.append(
                f"  {x.case}: {x.from_outcome} {x.from_reason or ''} -> {x.to_outcome} "
                f"{x.to_reason or ''}" + (f" by {x.to_policy}" if x.to_policy else "")
            )
    lines.append("")
    narrowed = (
        r.count("ALLOW_TO_DENY")
        + r.count("ALLOW_TO_REQUIRE_APPROVAL")
        + r.count("REQUIRE_APPROVAL_TO_DENY")
    )
    unchanged = sum(r.count(t) for t in order if t.startswith("UNCHANGED"))
    lines.append(
        f"{len(r.rows)} recorded action(s): {len(r.widened)} widened, "
        f"{narrowed} narrowed, {unchanged} unchanged"
    )
    return "\n".join(lines)


# --------------------------------------------------------------- mutation


class Mutant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    dimension: str
    case: CaseSpec
    must_deny: bool = Field(
        description="True when the mutation leaves the recorded delegated authority "
        "(resource outside scope, amount above the delegated limit, another agent): the "
        "kernel policies must deny these regardless of declared rules."
    )
    note: str = ""


class MutationRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    dimension: str
    must_deny: bool
    outcome: str | None
    reason: str | None
    policy: str | None
    note: str = ""

    @property
    def unexpected(self) -> bool:
        return self.must_deny and self.outcome == "ALLOW"


class MutationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    policy_set: str
    original_outcome: str | None
    rows: list[MutationRow]

    @property
    def allowed(self) -> list[MutationRow]:
        return [r for r in self.rows if r.outcome == "ALLOW"]

    @property
    def unexpected(self) -> list[MutationRow]:
        return [r for r in self.rows if r.unexpected]


def _leaf(suite: Suite, case: CaseSpec) -> GrantSpec:
    return next(g for g in suite.delegations.grants if g.id == case.delegation)


def _effective_max(suite: Suite, case: CaseSpec) -> Decimal | None:
    """Tightest max_amount along the case's chain (as declared in the suite)."""
    by_id = {g.id: g for g in suite.delegations.grants}
    g: GrantSpec | None = by_id.get(case.delegation)
    tight: Decimal | None = None
    while g is not None:
        if g.max_amount is not None and (tight is None or g.max_amount.amount < tight):
            tight = g.max_amount.amount
        g = by_id.get(g.parent) if g.parent else None
    return tight


def _in_scope(suite: Suite, case: CaseSpec, resource: str) -> bool:
    from atp_identity.scope import scope_matches

    by_id = {g.id: g for g in suite.delegations.grants}
    g: GrantSpec | None = by_id.get(case.delegation)
    while g is not None:
        if not scope_matches(list(g.resource_scope), resource):
            return False
        g = by_id.get(g.parent) if g.parent else None
    return True


def _with(case: CaseSpec, name: str, **update: Any) -> CaseSpec:
    return case.model_copy(update={"name": name, **update})


def generate_mutants(suite: Suite, case: CaseSpec) -> list[Mutant]:
    mutants: list[Mutant] = []
    args = dict(case.arguments)
    rtype, _, rid = case.resource.partition(":")

    # --- resource -------------------------------------------------------
    def res(name: str, resource: str, note: str = "") -> None:
        if resource == case.resource:
            return
        try:
            mutated = _with(case, f"{case.name} / {name}", resource=resource)
        except ValueError:
            return
        mutants.append(
            Mutant(
                name=mutated.name,
                dimension="resource",
                case=mutated,
                must_deny=not _in_scope(suite, case, resource),
                note=note,
            )
        )

    if rtype == "path":
        base = rid.rstrip("/")
        parent = base.rsplit("/", 1)[0] or "/"
        res("sibling path", f"path:{parent}/atp-mutant.txt")
        res("parent directory", f"path:{parent}")
        grand = parent.rsplit("/", 1)[0] or "/"
        res("traversal to grandparent", f"path:{grand}/atp-mutant.txt")
        res("restricted path", "path:/etc/passwd")
        res("windows system path", "path:c:/windows/system32/atp-mutant")
    else:
        res("other id of same type", f"{rtype}:{rid}-mutant")
        res("wildcard-looking id", f"{rtype}:{rid}%2A")
    res("other resource type", f"other:{rid}")

    # --- identity -------------------------------------------------------
    for alias, principal in suite.delegations.principals.items():
        if alias != case.agent and principal.kind.value == "agent":
            m = _with(case, f"{case.name} / as {alias}", agent=alias)
            mutants.append(
                Mutant(
                    name=m.name,
                    dimension="identity",
                    case=m,
                    must_deny=True,
                    note="another agent presents this delegation",
                )
            )
            break

    # --- capability -----------------------------------------------------
    m = _with(case, f"{case.name} / capability widened", capability=f"{case.capability}-admin")
    mutants.append(Mutant(name=m.name, dimension="capability", case=m, must_deny=True))

    # --- arguments ------------------------------------------------------
    limit = _effective_max(suite, case)
    for key, value in args.items():
        dec: Decimal | None = None
        if isinstance(value, int | float | str) and not isinstance(value, bool):
            try:
                dec = Decimal(str(value))
            except Exception:
                dec = None
        if dec is not None and dec.is_finite():
            is_money = key == "amount" and case.tool == "payments"
            for label, new in (
                ("+1", dec + 1),
                ("x10", dec * 10),
                ("negative", -abs(dec) - 1),
                ("zero", Decimal(0)),
            ):
                text = (
                    format(new, "f")
                    if isinstance(value, str)
                    else (int(new) if isinstance(value, int) else float(new))
                )
                if is_money and isinstance(value, str):
                    text = format(new.quantize(Decimal("0.01")), "f")
                m = _with(case, f"{case.name} / {key} {label}", arguments={**args, key: text})
                must = bool(is_money and limit is not None and new > limit)
                mutants.append(
                    Mutant(name=m.name, dimension=f"argument:{key}", case=m, must_deny=must)
                )
            if is_money and limit is not None:
                for label, new in (("at limit", limit), ("limit+0.01", limit + Decimal("0.01"))):
                    m = _with(
                        case,
                        f"{case.name} / amount {label}",
                        arguments={**args, key: format(new.quantize(Decimal("0.01")), "f")},
                    )
                    mutants.append(
                        Mutant(
                            name=m.name, dimension="argument:amount", case=m, must_deny=new > limit
                        )
                    )
        elif isinstance(value, str):
            if "/" in value or "\\" in value:
                m = _with(
                    case,
                    f"{case.name} / {key} traversal",
                    arguments={**args, key: value + "/../../etc/passwd"},
                )
                mutants.append(
                    Mutant(
                        name=m.name,
                        dimension=f"argument:{key}",
                        case=m,
                        must_deny=False,
                        note=(
                            "argument-level traversal; resource is unchanged, so only "
                            "argument rules can catch it"
                        ),
                    )
                )
            if key == "currency":
                m = _with(
                    case,
                    f"{case.name} / currency changed",
                    arguments={**args, key: "EUR" if value != "EUR" else "USD"},
                )
                mutants.append(
                    Mutant(name=m.name, dimension="argument:currency", case=m, must_deny=False)
                )
            if key == "destination_account":
                m = _with(
                    case,
                    f"{case.name} / destination changed",
                    arguments={**args, key: "acct-mutant-0000"},
                )
                mutants.append(
                    Mutant(
                        name=m.name,
                        dimension="argument:destination_account",
                        case=m,
                        must_deny=False,
                    )
                )
        # removal
        without = {k: v for k, v in args.items() if k != key}
        m = _with(case, f"{case.name} / {key} removed", arguments=without)
        mutants.append(Mutant(name=m.name, dimension=f"argument:{key}", case=m, must_deny=False))
    if case.tool == "payments" and "destination_account" not in args:
        m = _with(
            case,
            f"{case.name} / destination added",
            arguments={**args, "destination_account": "acct-mutant-0000"},
        )
        mutants.append(
            Mutant(name=m.name, dimension="argument:destination_account", case=m, must_deny=False)
        )
    m = _with(case, f"{case.name} / unexpected argument", arguments={**args, "atp_mutant": True})
    mutants.append(Mutant(name=m.name, dimension="argument:+unexpected", case=m, must_deny=False))
    return mutants


def mutate(
    suite: Suite,
    case: CaseSpec,
    *,
    policy_set: str | None = None,
    policy_file: str | None = None,
) -> MutationReport:
    version = policy_set or suite.policy_set
    mutants = generate_mutants(suite, case)
    original = case.model_copy(update={"expect": Expectation(outcome=case.expect.outcome)})
    results = decide_cases(
        suite, [original, *[m.case for m in mutants]], policy_set=version, policy_file=policy_file
    )
    rows = [
        MutationRow(
            name=m.name,
            dimension=m.dimension,
            must_deny=m.must_deny,
            outcome=r.observed_outcome,
            reason=r.observed_reason,
            policy=r.observed_policy,
            note=m.note,
        )
        for m, r in zip(mutants, results[1:], strict=True)
    ]
    return MutationReport(
        source=case.name,
        policy_set=version,
        original_outcome=results[0].observed_outcome,
        rows=rows,
    )


def format_mutation(r: MutationReport) -> str:
    w = 78
    lines = [
        "=" * w,
        f"mutation analysis of '{r.source}' under {r.policy_set}",
        f"original decision: {r.original_outcome}   (authorize only; nothing executed)",
        "=" * w,
    ]
    for row in r.rows:
        mark = "ALLOW" if row.outcome == "ALLOW" else (row.outcome or "ERROR")
        flag = "  <-- UNEXPECTED: outside recorded authority" if row.unexpected else ""
        lines.append(
            f"[{mark:<16}] {row.name.split(' / ', 1)[-1]:<32} {row.reason or '':<38}"
            + (f"{row.policy}" if row.policy else "")
            + flag
        )
        if row.note and row.outcome == "ALLOW":
            lines.append(f"{'':19}note: {row.note}")
    denied = sum(1 for x in r.rows if x.outcome == "DENY")
    approval = sum(1 for x in r.rows if x.outcome == "REQUIRE_APPROVAL")
    lines.append("")
    lines.append(
        f"{len(r.rows)} mutations: {denied} denied, {approval} need approval, "
        f"{len(r.allowed)} allowed ({len(r.unexpected)} unexpected)"
    )
    if r.allowed:
        lines.append("allowed mutations are not bugs by themselves; check each against what the")
        lines.append("delegation and the policy set were meant to permit")
    return "\n".join(lines)

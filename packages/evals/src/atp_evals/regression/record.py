"""Convert a recorded trace into a regression case.

This is a deterministic conversion, not generation: the envelope and the
delegation chain snapshot recorded by the gateway become a case whose
expectation is the decision the gateway actually made. Every field passes
through the strict suite models; anything unexpected is rejected, provenance
excerpts are dropped, and nothing from the trace is ever executed.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from atp_core import ActionEnvelope, Decision, Money, PrincipalRef
from atp_evals.regression.format import (
    CaseSpec,
    DelegationSpec,
    Expectation,
    GrantSpec,
    Source,
    Suite,
)


class TraceConversionError(ValueError):
    pass


def _alias(principal: PrincipalRef) -> str:
    return principal.id.replace(":", "-")[:64]


def _grant_alias(grant_id: str) -> str:
    return grant_id.replace("grt_", "g-")[:64]


def case_from_trace(
    trace: dict[str, Any], *, name: str | None = None, gateway: str | None = None
) -> tuple[DelegationSpec, CaseSpec]:
    """Build the delegation graph and case for one trace view (as returned by
    ``GET /traces/{id}``). Raises ``TraceConversionError`` on anything that
    does not validate."""
    try:
        envelope = ActionEnvelope.model_validate(trace["envelope"])
        decision = Decision.model_validate(trace["decision"])
        chain_raw = trace.get("delegation_chain") or []
    except (KeyError, TypeError, ValidationError) as exc:
        raise TraceConversionError(
            f"trace does not contain a valid proposal and decision: {exc}"
        ) from exc
    if not chain_raw:
        raise TraceConversionError(
            "trace has no resolved delegation chain; only decisions made against a resolved "
            "chain can be pinned as regression cases"
        )

    principals: dict[str, PrincipalRef] = {}
    grants: list[GrantSpec] = []
    parent_alias: str | None = None
    try:
        for link in chain_raw:
            grantor = PrincipalRef.model_validate(link["grantor"])
            grantee = PrincipalRef.model_validate(link["grantee"])
            principals.setdefault(_alias(grantor), grantor)
            principals.setdefault(_alias(grantee), grantee)
            constraints = link.get("constraints") or {}
            max_amount = constraints.get("max_amount")
            currencies = constraints.get("currencies")
            alias = _grant_alias(str(link["grant_id"]))
            grants.append(
                GrantSpec(
                    id=alias,
                    label=str(link.get("label", ""))[:200],
                    grantor=_alias(grantor),
                    grantee=_alias(grantee),
                    parent=parent_alias,
                    capabilities=tuple(sorted(link["capabilities"])),
                    resource_scope=tuple(link["resource_scope"]),
                    max_amount=Money.model_validate(max_amount) if max_amount else None,
                    currencies=tuple(currencies) if currencies else None,
                    expires_in="1d",
                )
            )
            parent_alias = alias
    except (KeyError, TypeError, ValidationError) as exc:
        raise TraceConversionError(f"delegation chain in trace is malformed: {exc}") from exc

    leaf = grants[-1]
    agent_alias = _alias(envelope.agent)
    principal_alias = _alias(envelope.principal)
    if agent_alias not in principals or principal_alias not in principals:
        raise TraceConversionError("envelope agent/principal are not part of the recorded chain")
    if principals[leaf.grantee] != envelope.agent:
        raise TraceConversionError("recorded chain leaf is not the envelope's agent")

    case = CaseSpec(
        name=name or f"trace-{envelope.trace_id}",
        description=(
            f"Recorded {decision.outcome.value} ({decision.reason_code.value}) under "
            f"{decision.policy_set_version}"
        ),
        agent=agent_alias,
        principal=principal_alias,
        delegation=leaf.id,
        capability=envelope.capability,
        tool=envelope.tool,
        action=envelope.action,
        resource=envelope.resource,
        arguments=dict(envelope.arguments),
        expect=Expectation(
            outcome=decision.outcome,
            reason_code=decision.reason_code.value,
            matched_policy=decision.matched_policy.qualified if decision.matched_policy else None,
        ),
        source=Source(
            trace_id=envelope.trace_id,
            recorded_at=decision.decided_at.isoformat(),
            gateway=gateway,
            policy_set=decision.policy_set_version,
        ),
    )
    return DelegationSpec(principals=principals, grants=tuple(grants)), case


def merge_into_suite(
    suite: Suite | None,
    delegations: DelegationSpec,
    case: CaseSpec,
    *,
    suite_name: str = "recorded regression cases",
) -> Suite:
    """Add a case (and any principals/grants it needs) to an existing suite,
    or create one. Existing grants with the same alias are kept as-is."""
    if suite is None:
        return Suite(name=suite_name, delegations=delegations, cases=(case,))
    principals = {**suite.delegations.principals}
    for alias, p in delegations.principals.items():
        if alias in principals and principals[alias] != p:
            raise TraceConversionError(
                f"principal alias {alias!r} already refers to a different principal"
            )
        principals.setdefault(alias, p)
    known = {g.id for g in suite.delegations.grants}
    grants = list(suite.delegations.grants) + [g for g in delegations.grants if g.id not in known]
    if any(c.name == case.name for c in suite.cases):
        raise TraceConversionError(f"a case named {case.name!r} already exists in the suite")
    merged = suite.model_copy(
        update={
            "delegations": DelegationSpec(principals=principals, grants=tuple(grants)),
            "cases": (*suite.cases, case),
        }
    )
    merged.validate_references()
    return merged

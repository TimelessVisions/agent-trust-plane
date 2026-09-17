"""HTTP routes. Thin: authentication, validation and status mapping only;
logic lives in ``TrustPlane``.

Who may call what:

| route                            | agent credential | operator key |
|----------------------------------|------------------|--------------|
| POST /authorize                  | required         | for policy-set override |
| POST /execute                    | required         |              |
| POST /traces/{id}/events         | required         |              |
| POST /executions/{grant}/outcome | grant audience   |              |
| POST /delegations                | grantor (agent)  | grantor (human) |
| POST /delegations/{id}/revoke    | grantor (agent)  | or operator  |
| GET  /delegations                |                  | required     |
| POST /agents/{id}/credentials    |                  | required     |
| GET  /agents/{id}/credentials    |                  | required     |
| POST /credentials/{id}/revoke    |                  | required     |
| POST /evals/run                  |                  | required     |
| GET  /traces*, /ledger/payments,        |                  |              |
|      /delegations/{id}[/chain], /vendors,|                  |              |
|      /evals/results; POST /replay        |                  | required     |
| GET  /health, /policy-sets               | open             |              |
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from atp_audit import TraceSummary
from atp_core import ActionEnvelope, ATPError, PrincipalKind, ReasonCode
from atp_gateway.auth import Agent, IsOperator, MaybeAgent, Operator
from atp_gateway.schemas import (
    CredentialIssued,
    CredentialIssueRequest,
    CredentialView,
    ExecuteRequest,
    ExecutionOutcomeRequest,
    HealthView,
    PolicySetView,
    ReplayRequest,
    TraceEventRequest,
)
from atp_gateway.service import (
    AuthorizationResult,
    ExecutionResult,
    ReplayResult,
    TraceView,
    TrustPlane,
)
from atp_gateway.tools import PaymentRecord
from atp_gateway.wiring import Runtime
from atp_identity import AgentCredential, AuthError, DelegationGrant, DelegationRequest

router = APIRouter()


def _rt(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


def _tp(request: Request) -> TrustPlane:
    return _rt(request).trust_plane


def _view(c: AgentCredential) -> CredentialView:
    return CredentialView(
        credential_id=c.credential_id,
        agent=c.agent,
        label=c.label,
        issued_at=c.issued_at,
        expires_at=c.expires_at,
        revoked_at=c.revoked_at,
    )


# ------------------------------------------------------------------ core API
@router.post("/authorize", response_model=AuthorizationResult, tags=["control"])
def authorize(
    envelope: ActionEnvelope,
    request: Request,
    caller: Agent,
    operator: IsOperator,
    policy_set_version: str | None = Query(default=None),
) -> AuthorizationResult:
    """Decide whether the proposed action may execute. The authenticated agent
    must be ``envelope.agent``. Returns a signed, single-use execution grant
    only on ALLOW. Selecting a non-default policy set requires the operator
    key: an agent cannot choose which policies judge it."""
    if policy_set_version is not None and not operator:
        raise ATPError(
            ReasonCode.POLICY_SET_OVERRIDE_FORBIDDEN,
            "choosing a policy set requires the operator key; agents cannot select "
            "which policies apply to them",
        )
    return _tp(request).authorize(envelope, caller, policy_set_version=policy_set_version)


@router.post("/execute", response_model=ExecutionResult, tags=["control"])
def execute(body: ExecuteRequest, request: Request, caller: Agent) -> ExecutionResult:
    """Execute a previously authorized action. The grant must verify, be
    unexpired, be unused, be addressed to the authenticated agent, and match
    the submitted envelope's action hash."""
    return _tp(request).execute(body.envelope, body.execution_grant, caller)


@router.post("/executions/{grant_id}/outcome", tags=["control"])
def report_outcome(
    grant_id: str, body: ExecutionOutcomeRequest, request: Request, caller: Agent
) -> dict[str, Any]:
    """External executors (e.g. the MCP proxy) report the result of a released
    execution. Bound to the consumed grant's audience; accepted once."""
    event = _tp(request).report_outcome(
        grant_id, caller, succeeded=body.succeeded, summary=body.summary
    )
    return event.model_dump(mode="json")


@router.get("/traces", response_model=list[TraceSummary], tags=["audit"])
def list_traces(
    request: Request, _: Operator, limit: int = Query(default=50, ge=1, le=500)
) -> list[TraceSummary]:
    return _tp(request).list_traces(limit)


@router.get("/traces/{trace_id}", response_model=TraceView, tags=["audit"])
def get_trace(trace_id: str, request: Request, _: Operator) -> TraceView:
    return _tp(request).get_trace(trace_id)


@router.post("/traces/{trace_id}/events", tags=["audit"])
def append_trace_event(
    trace_id: str, body: TraceEventRequest, request: Request, caller: Agent
) -> dict[str, Any]:
    """Agents record provenance here (task received, external content
    ingested). The actor is the authenticated agent; gateway-only event types
    are rejected."""
    event = _tp(request).record_event(trace_id, body.event_type, caller, body.payload)
    return event.model_dump(mode="json")


@router.post("/replay/{trace_id}", response_model=ReplayResult, tags=["audit"])
def replay(
    trace_id: str, request: Request, _: Operator, body: ReplayRequest | None = None
) -> ReplayResult:
    """Re-evaluate the recorded action against the same or a different policy
    set. Never executes, never mints a grant."""
    version = body.policy_set_version if body else None
    return _tp(request).replay(trace_id, policy_set_version=version)


# ----------------------------------------------------------------- delegation
@router.post("/delegations", response_model=DelegationGrant, status_code=201, tags=["identity"])
def issue_delegation(
    body: DelegationRequest, request: Request, caller: MaybeAgent, operator: IsOperator
) -> DelegationGrant:
    """Issue a grant. A human grantor is represented by the operator key (the
    MVP's trust anchor for human authority); an agent grantor must present its
    own credential. Nobody can delegate on another principal's behalf."""
    if body.grantor.kind is PrincipalKind.HUMAN:
        if not operator:
            raise ATPError(
                ReasonCode.OPERATOR_KEY_REQUIRED,
                "delegating human authority requires the operator key",
            )
    else:
        if caller is None:
            raise AuthError(
                ReasonCode.AGENT_CREDENTIAL_MISSING,
                "an agent grantor must authenticate with its own credential",
            )
        if caller.agent != body.grantor:
            raise AuthError(
                ReasonCode.AGENT_IDENTITY_MISMATCH,
                f"authenticated as {caller.agent}; cannot delegate on behalf of {body.grantor}",
            )
    return _tp(request).issue_delegation(body)


@router.get("/delegations", response_model=list[DelegationGrant], tags=["identity"])
def list_delegations(request: Request, _: Operator) -> list[DelegationGrant]:
    return list(_tp(request).delegations.store.all())


@router.get("/delegations/{grant_id}", response_model=DelegationGrant, tags=["identity"])
def get_delegation(grant_id: str, request: Request, _: Operator) -> DelegationGrant:
    return _tp(request).get_delegation(grant_id)


@router.get("/delegations/{grant_id}/chain", tags=["identity"])
def resolve_delegation(grant_id: str, request: Request, _: Operator) -> dict[str, Any]:
    chain = _tp(request).resolve_delegation(grant_id)
    return {
        "grants": [g.model_dump(mode="json") for g in chain.grants],
        "authority": chain.authority.model_dump(mode="json"),
    }


@router.post("/delegations/{grant_id}/revoke", response_model=DelegationGrant, tags=["identity"])
def revoke_delegation(
    grant_id: str, request: Request, caller: MaybeAgent, operator: IsOperator
) -> DelegationGrant:
    """The operator, or the agent that issued the grant, may revoke it."""
    tp = _tp(request)
    grant = tp.get_delegation(grant_id)
    if not operator and (caller is None or caller.agent != grant.grantor):
        raise ATPError(
            ReasonCode.OPERATOR_KEY_REQUIRED,
            "only the operator or the grant's grantor may revoke it",
        )
    return tp.revoke_delegation(grant_id)


# ---------------------------------------------------------------- credentials
@router.post(
    "/agents/{agent_id}/credentials",
    response_model=CredentialIssued,
    status_code=201,
    tags=["identity"],
)
def issue_credential(
    agent_id: str, body: CredentialIssueRequest, request: Request, _: Operator
) -> CredentialIssued:
    """Operator-only. The token in the response is shown once and never stored."""
    if body.agent.id != agent_id:
        raise ATPError(ReasonCode.AGENT_IDENTITY_MISMATCH, "path agent id and body agent id differ")
    tp = _tp(request)
    credential, token = tp.credentials.issue(
        body.agent, label=body.label, expires_at=body.expires_at, now=tp.clock()
    )
    return CredentialIssued(
        credential_id=credential.credential_id,
        agent=credential.agent,
        label=credential.label,
        issued_at=credential.issued_at,
        expires_at=credential.expires_at,
        token=token,
    )


@router.get(
    "/agents/{agent_id}/credentials", response_model=list[CredentialView], tags=["identity"]
)
def list_credentials(agent_id: str, request: Request, _: Operator) -> list[CredentialView]:
    return [_view(c) for c in _tp(request).credentials.list_for_agent(agent_id)]


@router.post(
    "/credentials/{credential_id}/revoke", response_model=CredentialView, tags=["identity"]
)
def revoke_credential(credential_id: str, request: Request, _: Operator) -> CredentialView:
    tp = _tp(request)
    return _view(tp.credentials.revoke(credential_id, now=tp.clock()))


# ------------------------------------------------------------------- catalog
@router.get("/policy-sets", response_model=list[PolicySetView], tags=["catalog"])
def policy_sets(request: Request) -> list[PolicySetView]:
    registry = _tp(request).policy_sets
    return [
        PolicySetView(
            version=ps.version,
            description=ps.description,
            is_default=ps.version == registry.default_version,
            policies=ps.refs(),
            policy_descriptions={p.ref.qualified: p.description for p in ps.policies},
        )
        for ps in registry.versions()
    ]


@router.get("/vendors", tags=["catalog"])
def vendors(request: Request, _: Operator) -> list[dict[str, Any]]:
    return [v.model_dump(mode="json") for v in _rt(request).vendors.all()]


@router.get("/ledger/payments", response_model=list[PaymentRecord], tags=["catalog"])
def ledger(request: Request, _: Operator) -> list[PaymentRecord]:
    """What actually executed. The proof that blocked payments never settled."""
    return _rt(request).ledger.all()


@router.get("/health", response_model=HealthView, tags=["catalog"])
def health(request: Request) -> HealthView:
    rt = _rt(request)
    return HealthView(
        status="ok",
        default_policy_set=rt.trust_plane.policy_sets.default_version,
        grant_ttl_seconds=rt.trust_plane.grant_ttl_seconds,
        tools=rt.trust_plane.tools.names(),
    )


# --------------------------------------------------------------------- evals
@router.get("/evals/results", tags=["evals"])
def eval_results(request: Request, _: Operator) -> dict[str, Any]:
    latest = _rt(request).reports.latest()
    return latest or {"status": "never_run", "results": []}


@router.post("/evals/run", tags=["evals"])
def run_evals(request: Request, _: Operator) -> dict[str, Any]:
    """Operator-only. Runs the adversarial eval suite in-process against this
    gateway (issuing short-lived agent credentials as it goes) and persists
    the report. ``atp_evals`` is imported lazily so the gateway package does
    not depend on it."""
    from atp_evals.runner import run_suite_in_process

    rt = _rt(request)
    report = run_suite_in_process(rt)
    body: dict[str, Any] = report.model_dump(mode="json")
    rt.reports.save(body)
    return body

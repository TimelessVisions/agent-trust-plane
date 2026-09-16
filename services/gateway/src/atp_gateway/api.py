"""HTTP routes. Thin: validation and status mapping only; logic lives in
``TrustPlane``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from atp_audit import TraceSummary
from atp_core import ActionEnvelope
from atp_gateway.schemas import (
    ExecuteRequest,
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
from atp_identity import DelegationGrant, DelegationRequest

router = APIRouter()


def _rt(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


def _tp(request: Request) -> TrustPlane:
    return _rt(request).trust_plane


# ------------------------------------------------------------------ core API
@router.post("/authorize", response_model=AuthorizationResult, tags=["control"])
def authorize(
    envelope: ActionEnvelope,
    request: Request,
    policy_set_version: str | None = Query(default=None),
) -> AuthorizationResult:
    """Decide whether the proposed action may execute. Returns a signed,
    single-use execution grant only on ALLOW."""
    return _tp(request).authorize(envelope, policy_set_version=policy_set_version)


@router.post("/execute", response_model=ExecutionResult, tags=["control"])
def execute(body: ExecuteRequest, request: Request) -> ExecutionResult:
    """Execute a previously authorized action. The grant must verify, be
    unexpired, be unused, and match the submitted envelope's action hash."""
    return _tp(request).execute(body.envelope, body.execution_grant)


@router.get("/traces", response_model=list[TraceSummary], tags=["audit"])
def list_traces(
    request: Request, limit: int = Query(default=50, ge=1, le=500)
) -> list[TraceSummary]:
    return _tp(request).list_traces(limit)


@router.get("/traces/{trace_id}", response_model=TraceView, tags=["audit"])
def get_trace(trace_id: str, request: Request) -> TraceView:
    return _tp(request).get_trace(trace_id)


@router.post("/traces/{trace_id}/events", tags=["audit"])
def append_trace_event(trace_id: str, body: TraceEventRequest, request: Request) -> dict[str, Any]:
    """Agents record provenance here (task received, external content ingested).
    Gateway-only event types are rejected."""
    event = _tp(request).record_event(trace_id, body.event_type, body.actor, body.payload)
    return event.model_dump(mode="json")


@router.post("/replay/{trace_id}", response_model=ReplayResult, tags=["audit"])
def replay(trace_id: str, request: Request, body: ReplayRequest | None = None) -> ReplayResult:
    """Re-evaluate the recorded action against the same or a different policy
    set. Never executes."""
    version = body.policy_set_version if body else None
    return _tp(request).replay(trace_id, policy_set_version=version)


# ----------------------------------------------------------------- delegation
@router.post("/delegations", response_model=DelegationGrant, status_code=201, tags=["identity"])
def issue_delegation(body: DelegationRequest, request: Request) -> DelegationGrant:
    return _tp(request).issue_delegation(body)


@router.get("/delegations", response_model=list[DelegationGrant], tags=["identity"])
def list_delegations(request: Request) -> list[DelegationGrant]:
    return list(_tp(request).delegations.store.all())


@router.get("/delegations/{grant_id}", response_model=DelegationGrant, tags=["identity"])
def get_delegation(grant_id: str, request: Request) -> DelegationGrant:
    return _tp(request).get_delegation(grant_id)


@router.get("/delegations/{grant_id}/chain", tags=["identity"])
def resolve_delegation(grant_id: str, request: Request) -> dict[str, Any]:
    chain = _tp(request).resolve_delegation(grant_id)
    return {
        "grants": [g.model_dump(mode="json") for g in chain.grants],
        "authority": chain.authority.model_dump(mode="json"),
    }


@router.post("/delegations/{grant_id}/revoke", response_model=DelegationGrant, tags=["identity"])
def revoke_delegation(grant_id: str, request: Request) -> DelegationGrant:
    return _tp(request).revoke_delegation(grant_id)


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
def vendors(request: Request) -> list[dict[str, Any]]:
    return [v.model_dump(mode="json") for v in _rt(request).vendors.all()]


@router.get("/ledger/payments", response_model=list[PaymentRecord], tags=["catalog"])
def ledger(request: Request) -> list[PaymentRecord]:
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
        signing_key_fingerprint=rt.trust_plane.signer.key_fingerprint,
    )


# --------------------------------------------------------------------- evals
@router.get("/evals/results", tags=["evals"])
def eval_results(request: Request) -> dict[str, Any]:
    latest = _rt(request).reports.latest()
    return latest or {"status": "never_run", "results": []}


@router.post("/evals/run", tags=["evals"])
def run_evals(request: Request) -> dict[str, Any]:
    """Run the adversarial eval suite in-process against this gateway and
    persist the report. ``atp_evals`` is imported lazily so the gateway
    package does not depend on it."""
    from atp_evals.runner import run_suite_in_process

    rt = _rt(request)
    report = run_suite_in_process(rt)
    body: dict[str, Any] = report.model_dump(mode="json")
    rt.reports.save(body)
    return body

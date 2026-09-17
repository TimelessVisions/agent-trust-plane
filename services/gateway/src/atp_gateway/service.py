"""TrustPlane: the orchestration core behind the HTTP API.

authorize -> resolve delegation -> evaluate policy -> decide -> (mint grant)
execute   -> verify grant -> re-check delegation -> consume grant -> run tool
replay    -> load the recorded envelope + authority snapshot -> re-evaluate

Every step appends to the hash-chained trace. Nothing here trusts a client
claim about authority; the only client inputs that matter are the envelope's
grant id and, at execution, the signed grant.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atp_audit import EventType, IntegrityReport, TraceEvent, TraceStore, TraceSummary
from atp_core import (
    ActionEnvelope,
    ATPError,
    Decision,
    DecisionOutcome,
    DelegationError,
    EffectiveAuthority,
    GrantError,
    ReasonCode,
    ToolError,
    utcnow,
)
from atp_gateway.grants import GrantClaims, GrantSigner, GrantStore, new_grant_claims
from atp_gateway.tools import ToolRegistry
from atp_identity import (
    AuthenticatedAgent,
    AuthError,
    CredentialService,
    DelegationGrant,
    DelegationRequest,
    DelegationService,
    ResolvedChain,
)
from atp_policy import PolicyContext, PolicyEngine, PolicySetRegistry, VendorDirectory

log = logging.getLogger("atp.gateway")

GATEWAY_ACTOR = "gateway"

# Event types an agent may append itself (provenance about what it saw/did).
AGENT_WRITABLE_EVENTS = frozenset({EventType.TASK_RECEIVED, EventType.EXTERNAL_CONTENT_INGESTED})


class IssuedGrant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str
    grant_id: str
    expires_at: datetime


class AuthorizationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Decision
    execution_grant: IssuedGrant | None = Field(
        default=None, description="Present only when the decision is ALLOW."
    )


class ExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    envelope_id: str
    status: str = Field(description="completed | blocked | failed")
    reason_code: ReasonCode
    message: str
    result: dict[str, Any] | None = None

    @property
    def executed(self) -> bool:
        return self.status == "completed"


class ReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    original_decision: Decision
    replayed_decision: Decision
    original_policy_set_version: str
    replayed_policy_set_version: str
    outcome_changed: bool
    summary: str


class TraceView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    events: list[TraceEvent]
    integrity: IntegrityReport
    envelope: ActionEnvelope | None = None
    decision: Decision | None = None
    delegation_chain: list[dict[str, Any]] = Field(default_factory=list)
    execution: dict[str, Any] | None = None
    replays: list[dict[str, Any]] = Field(default_factory=list)


class TrustPlane:
    def __init__(
        self,
        *,
        delegations: DelegationService,
        credentials: CredentialService,
        traces: TraceStore,
        grants: GrantStore,
        signer: GrantSigner,
        policy_sets: PolicySetRegistry,
        vendors: VendorDirectory,
        tools: ToolRegistry,
        grant_ttl_seconds: int = 120,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.delegations = delegations
        self.credentials = credentials
        self.traces = traces
        self.grants = grants
        self.signer = signer
        self.policy_sets = policy_sets
        self.vendors = vendors
        self.tools = tools
        self.grant_ttl_seconds = grant_ttl_seconds
        self.clock = clock
        self.engine = PolicyEngine()
        # One lock around each state-changing operation: the MVP stores share a
        # single SQLite connection and the trace chain must not interleave.
        self._lock = threading.RLock()

    # ------------------------------------------------------------ provenance
    def record_event(
        self,
        trace_id: str,
        event_type: EventType,
        caller: AuthenticatedAgent,
        payload: dict[str, Any],
    ) -> TraceEvent:
        """Agent-side provenance. The actor is always the authenticated agent;
        callers cannot name a different actor."""
        if event_type not in AGENT_WRITABLE_EVENTS:
            raise ATPError(
                ReasonCode.EVENT_TYPE_RESERVED,
                f"event type '{event_type.value}' can only be written by the gateway",
            )
        body = {**payload, "credential_id": caller.credential_id}
        with self._lock:
            self._check_credential_live(caller)
            self._check_trace_owner(trace_id, caller)
            return self.traces.append(trace_id, event_type, caller.agent.id, body)

    # -------------------------------------------------------------- identity
    def _check_credential_live(self, caller: AuthenticatedAgent) -> None:
        """Authentication happened in the HTTP layer, outside the lock. Re-check
        the credential here so a revocation cannot land in between."""
        cred = self.credentials.store.get(caller.credential_id)
        if cred is None or cred.is_revoked():
            raise AuthError(ReasonCode.AGENT_CREDENTIAL_REVOKED, "agent credential was revoked")
        if cred.is_expired(self.clock()):
            raise AuthError(ReasonCode.AGENT_CREDENTIAL_EXPIRED, "agent credential has expired")

    def _trace_owner(self, trace_id: str) -> str | None:
        """The agent that first wrote to a trace owns it. Gateway-authored
        first events name the agent they concern in their payload."""
        events = self.traces.events(trace_id)
        if not events:
            return None
        first = events[0]
        if first.actor != GATEWAY_ACTOR:
            return first.actor
        who = first.payload.get("authenticated_agent")
        return who.get("id") if isinstance(who, dict) else None

    def _check_trace_owner(self, trace_id: str, caller: AuthenticatedAgent) -> None:
        owner = self._trace_owner(trace_id)
        if owner is not None and owner != caller.agent.id:
            raise AuthError(
                ReasonCode.TRACE_OWNED_BY_OTHER_AGENT,
                f"trace {trace_id} belongs to another agent; {caller.agent} cannot append to it",
            )

    def _bind_identity(self, envelope: ActionEnvelope, caller: AuthenticatedAgent) -> None:
        """The authenticated agent must be the envelope's acting agent. A
        mismatch with a *valid* credential is recorded: it is an authenticated
        party attempting to act as someone else."""
        self._check_credential_live(caller)
        self._check_trace_owner(envelope.trace_id, caller)
        if caller.agent != envelope.agent:
            self.traces.append(
                envelope.trace_id,
                EventType.IDENTITY_REJECTED,
                GATEWAY_ACTOR,
                {
                    "authenticated_agent": caller.agent.model_dump(mode="json"),
                    "credential_id": caller.credential_id,
                    "claimed_agent": envelope.agent.model_dump(mode="json"),
                    "envelope_id": envelope.envelope_id,
                    "reason_code": ReasonCode.AGENT_IDENTITY_MISMATCH.value,
                },
            )
            raise AuthError(
                ReasonCode.AGENT_IDENTITY_MISMATCH,
                f"authenticated as {caller.agent} but the envelope claims to be {envelope.agent}",
            )

    # ------------------------------------------------------------- authorize
    def authorize(
        self,
        envelope: ActionEnvelope,
        caller: AuthenticatedAgent,
        *,
        policy_set_version: str | None = None,
    ) -> AuthorizationResult:
        with self._lock:
            self._bind_identity(envelope, caller)
            return self._authorize(envelope, caller, policy_set_version)

    def _authorize(
        self, envelope: ActionEnvelope, caller: AuthenticatedAgent, policy_set_version: str | None
    ) -> AuthorizationResult:
        now = self.clock()
        policy_set = self.policy_sets.get(policy_set_version)
        trace_id = envelope.trace_id

        self.traces.append(
            trace_id,
            EventType.ACTION_PROPOSED,
            envelope.agent.id,
            {
                "envelope": envelope.model_dump(mode="json"),
                "action_hash": envelope.action_hash,
                "credential_id": caller.credential_id,
            },
        )

        authority: EffectiveAuthority | None = None
        error: tuple[ReasonCode, str] | None = None
        try:
            chain = self.delegations.resolve(
                envelope.delegation_grant_id,
                agent=envelope.agent,
                principal=envelope.principal,
                now=now,
            )
            authority = chain.authority
            self.traces.append(
                trace_id,
                EventType.DELEGATION_RESOLVED,
                GATEWAY_ACTOR,
                {
                    "authority": authority.model_dump(mode="json"),
                    "chain": _chain_summary(chain),
                },
            )
        except DelegationError as exc:
            error = (exc.reason_code, exc.message)
            self.traces.append(
                trace_id,
                EventType.DELEGATION_RESOLUTION_FAILED,
                GATEWAY_ACTOR,
                {
                    "grant_id": envelope.delegation_grant_id,
                    "reason_code": exc.reason_code.value,
                    "message": exc.message,
                },
            )

        ctx = PolicyContext(
            envelope=envelope,
            vendors=self.vendors,
            now=now,
            authority=authority,
            resolution_error=error,
        )
        decision = self.engine.evaluate(policy_set, ctx)
        self._record_decision(decision)

        grant: IssuedGrant | None = None
        if decision.outcome is DecisionOutcome.ALLOW:
            claims = new_grant_claims(
                trace_id=trace_id,
                decision_id=decision.decision_id,
                envelope_id=envelope.envelope_id,
                action_hash=envelope.action_hash,
                agent_id=envelope.agent.id,
                policy_set_version=policy_set.version,
                ttl_seconds=self.grant_ttl_seconds,
                now=now,
            )
            self.grants.issue(claims)
            token = self.signer.mint(claims)
            grant = IssuedGrant(token=token, grant_id=claims.grant_id, expires_at=claims.expires_at)
            self.traces.append(
                trace_id,
                EventType.GRANT_ISSUED,
                GATEWAY_ACTOR,
                {
                    "grant_id": claims.grant_id,
                    "expires_at": claims.expires_at.isoformat(),
                    "action_hash": claims.action_hash,
                    "single_use": True,
                    "key_fingerprint": self.signer.key_fingerprint,
                },
            )
        elif decision.outcome is DecisionOutcome.REQUIRE_APPROVAL and decision.approval:
            self.traces.append(
                trace_id,
                EventType.APPROVAL_REQUESTED,
                GATEWAY_ACTOR,
                decision.approval.model_dump(mode="json"),
            )

        return AuthorizationResult(decision=decision, execution_grant=grant)

    def _record_decision(self, decision: Decision) -> None:
        self.traces.append(
            decision.trace_id,
            EventType.POLICY_EVALUATED,
            GATEWAY_ACTOR,
            {
                "policy_set_version": decision.policy_set_version,
                "evaluations": [e.model_dump(mode="json") for e in decision.evaluations],
            },
        )
        self.traces.append(
            decision.trace_id,
            EventType.DECISION_MADE,
            GATEWAY_ACTOR,
            {"decision": decision.model_dump(mode="json")},
        )

    # --------------------------------------------------------------- execute
    def execute(
        self, envelope: ActionEnvelope, grant_token: str | None, caller: AuthenticatedAgent
    ) -> ExecutionResult:
        with self._lock:
            self._bind_identity(envelope, caller)
            return self._execute(envelope, grant_token, caller)

    def _execute(
        self, envelope: ActionEnvelope, grant_token: str | None, caller: AuthenticatedAgent
    ) -> ExecutionResult:
        now = self.clock()
        trace_id = envelope.trace_id
        self.traces.append(
            trace_id,
            EventType.EXECUTION_ATTEMPTED,
            envelope.agent.id,
            {
                "envelope_id": envelope.envelope_id,
                "action_hash": envelope.action_hash,
                "grant_presented": grant_token is not None,
                "credential_id": caller.credential_id,
            },
        )
        try:
            claims = self._verify_grant(envelope, grant_token, now)
            if claims.agent_id != caller.agent.id:
                raise GrantError(
                    ReasonCode.GRANT_AUDIENCE_MISMATCH,
                    "execution grant was issued to a different agent",
                )
            # Authority can be revoked between authorize and execute; check again.
            self.delegations.resolve(
                envelope.delegation_grant_id,
                agent=envelope.agent,
                principal=envelope.principal,
                now=now,
            )
            self.grants.consume(claims.grant_id, now)
        except (GrantError, DelegationError) as exc:
            return self._blocked(envelope, exc.reason_code, exc.message)

        try:
            tool = self.tools.get(envelope.tool)
            result = tool.execute(envelope)
        except ToolError as exc:
            self.traces.append(
                trace_id,
                EventType.EXECUTION_FAILED,
                GATEWAY_ACTOR,
                {"reason_code": exc.reason_code.value, "message": exc.message},
            )
            return ExecutionResult(
                trace_id=trace_id,
                envelope_id=envelope.envelope_id,
                status="failed",
                reason_code=exc.reason_code,
                message=exc.message,
            )

        self.traces.append(
            trace_id,
            EventType.EXECUTION_COMPLETED,
            GATEWAY_ACTOR,
            {"grant_id": claims.grant_id, "tool": envelope.tool, "result": result},
        )
        return ExecutionResult(
            trace_id=trace_id,
            envelope_id=envelope.envelope_id,
            status="completed",
            reason_code=ReasonCode.EXECUTION_COMPLETED,
            message=f"{envelope.qualified_action} executed",
            result=result,
        )

    def _verify_grant(
        self, envelope: ActionEnvelope, token: str | None, now: datetime
    ) -> GrantClaims:
        if not token:
            raise GrantError(
                ReasonCode.GRANT_MISSING,
                "execution requires a grant issued by /authorize; none was presented",
            )
        claims = self.signer.verify(token)
        if claims.is_expired(now):
            raise GrantError(
                ReasonCode.GRANT_EXPIRED,
                f"execution grant expired at {claims.expires_at.isoformat()}",
            )
        if claims.action_hash != envelope.action_hash:
            raise GrantError(
                ReasonCode.GRANT_ENVELOPE_MISMATCH,
                "the submitted action does not match the action that was authorized",
            )
        return claims

    def _blocked(self, envelope: ActionEnvelope, code: ReasonCode, message: str) -> ExecutionResult:
        self.traces.append(
            envelope.trace_id,
            EventType.EXECUTION_BLOCKED,
            GATEWAY_ACTOR,
            {"reason_code": code.value, "message": message, "envelope_id": envelope.envelope_id},
        )
        return ExecutionResult(
            trace_id=envelope.trace_id,
            envelope_id=envelope.envelope_id,
            status="blocked",
            reason_code=code,
            message=message,
        )

    # ---------------------------------------------------------------- replay
    def replay(self, trace_id: str, *, policy_set_version: str | None = None) -> ReplayResult:
        with self._lock:
            return self._replay(trace_id, policy_set_version)

    def _replay(self, trace_id: str, policy_set_version: str | None) -> ReplayResult:
        view = self.get_trace(trace_id)
        if view.envelope is None or view.decision is None:
            raise ATPError(
                ReasonCode.TRACE_HAS_NO_PROPOSAL,
                f"trace {trace_id} has no recorded proposal/decision to replay",
            )
        policy_set = self.policy_sets.get(policy_set_version)
        original = view.decision

        # Use the delegation snapshot recorded at authorization time so replay
        # asks "same action, same authority, different policy?" and nothing else.
        authority = original.effective_authority
        error: tuple[ReasonCode, str] | None = None
        if authority is None:
            failed = self.traces.find(trace_id, EventType.DELEGATION_RESOLUTION_FAILED)
            if failed:
                error = (ReasonCode(failed[0].payload["reason_code"]), failed[0].payload["message"])

        ctx = PolicyContext(
            envelope=view.envelope,
            vendors=self.vendors,
            now=original.decided_at,
            authority=authority,
            resolution_error=error,
        )
        replayed = self.engine.evaluate(policy_set, ctx).model_copy(
            update={"replay_of": original.decision_id}
        )
        changed = replayed.outcome != original.outcome or (
            replayed.reason_code != original.reason_code
        )
        summary = (
            f"{original.policy_set_version}: {original.outcome.value} "
            f"({original.reason_code.value}) -> {policy_set.version}: "
            f"{replayed.outcome.value} ({replayed.reason_code.value})"
        )
        self.traces.append(
            trace_id,
            EventType.REPLAY_PERFORMED,
            GATEWAY_ACTOR,
            {
                "original_decision_id": original.decision_id,
                "original_policy_set_version": original.policy_set_version,
                "replayed_policy_set_version": policy_set.version,
                "outcome_changed": changed,
                "summary": summary,
                "replayed_decision": replayed.model_dump(mode="json"),
                "execution": "not permitted on replay",
            },
        )
        return ReplayResult(
            trace_id=trace_id,
            original_decision=original,
            replayed_decision=replayed,
            original_policy_set_version=original.policy_set_version,
            replayed_policy_set_version=policy_set.version,
            outcome_changed=changed,
            summary=summary,
        )

    # ---------------------------------------------------------------- traces
    def get_trace(self, trace_id: str) -> TraceView:
        events = self.traces.events(trace_id)
        if not events:
            raise ATPError(ReasonCode.TRACE_NOT_FOUND, f"trace {trace_id} not found")
        envelope: ActionEnvelope | None = None
        decision: Decision | None = None
        chain: list[dict[str, Any]] = []
        execution: dict[str, Any] | None = None
        replays: list[dict[str, Any]] = []
        for ev in events:
            if ev.event_type is EventType.ACTION_PROPOSED and envelope is None:
                envelope = ActionEnvelope.model_validate(ev.payload["envelope"])
            elif ev.event_type is EventType.DELEGATION_RESOLVED:
                chain = list(ev.payload["chain"])
            elif ev.event_type is EventType.DECISION_MADE and decision is None:
                decision = Decision.model_validate(ev.payload["decision"])
            elif ev.event_type in (
                EventType.EXECUTION_BLOCKED,
                EventType.EXECUTION_COMPLETED,
                EventType.EXECUTION_FAILED,
            ):
                execution = {"event_type": ev.event_type.value, **ev.payload}
            elif ev.event_type is EventType.REPLAY_PERFORMED:
                replays.append(ev.payload)
        return TraceView(
            trace_id=trace_id,
            events=events,
            integrity=self.traces.verify(trace_id),
            envelope=envelope,
            decision=decision,
            delegation_chain=chain,
            execution=execution,
            replays=replays,
        )

    def list_traces(self, limit: int = 50) -> list[TraceSummary]:
        return self.traces.list_traces(limit)

    # ----------------------------------------------------------- delegations
    def issue_delegation(self, request: DelegationRequest) -> DelegationGrant:
        with self._lock:
            return self.delegations.issue(request, now=self.clock())

    def revoke_delegation(self, grant_id: str) -> DelegationGrant:
        # Under the same lock as execute so a revocation cannot land between
        # the delegation re-check and the grant consumption.
        with self._lock:
            return self.delegations.revoke(grant_id, now=self.clock())

    def get_delegation(self, grant_id: str) -> DelegationGrant:
        grant = self.delegations.store.get(grant_id)
        if grant is None:
            raise DelegationError(ReasonCode.DELEGATION_NOT_FOUND, f"grant {grant_id} not found")
        return grant

    def resolve_delegation(self, grant_id: str) -> ResolvedChain:
        return self.delegations.resolve(grant_id, now=self.clock())


def _chain_summary(chain: ResolvedChain) -> list[dict[str, Any]]:
    return [
        {
            "grant_id": g.grant_id,
            "label": g.label,
            "grantor": g.grantor.model_dump(mode="json"),
            "grantee": g.grantee.model_dump(mode="json"),
            "capabilities": sorted(g.capabilities),
            "resource_scope": list(g.resource_scope),
            "constraints": g.constraints.model_dump(mode="json"),
            "expires_at": g.expires_at.isoformat(),
        }
        for g in chain.grants
    ]

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
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atp_audit import EventType, IntegrityReport, TraceEvent, TraceStore, TraceSummary
from atp_core import (
    ActionEnvelope,
    ApprovalRequirement,
    ATPError,
    ConstraintEvaluation,
    Decision,
    DecisionOutcome,
    DelegationError,
    EffectiveAuthority,
    EnforcementMode,
    GrantError,
    Money,
    PolicyEvaluation,
    PolicyRef,
    PrincipalRef,
    ReasonCode,
    ToolError,
    new_id,
    utcnow,
)
from atp_core.sqlite import no_transaction
from atp_gateway.approvals import (
    ApprovalClaims,
    ApprovalRecord,
    ApprovalStatus,
    ApprovalStore,
    InMemoryApprovalStore,
    decode_signature,
    encode_signature,
    roles_for,
)
from atp_gateway.grants import (
    GrantClaims,
    GrantSigner,
    GrantStore,
    GrantVerifier,
    new_grant_claims,
)
from atp_gateway.tools import ToolRegistry
from atp_identity import (
    AuthenticatedAgent,
    AuthError,
    BearerCredentialProvider,
    BudgetLine,
    BudgetUsage,
    CredentialService,
    DelegationGrant,
    DelegationRequest,
    DelegationService,
    IdentityProvider,
    InMemoryReservationStore,
    ReservationResult,
    ReservationStore,
    ResolvedChain,
    budget_lines,
)
from atp_policy import PolicyContext, PolicyEngine, PolicySetRegistry, VendorDirectory

log = logging.getLogger("atp.gateway")

GATEWAY_ACTOR = "gateway"

BUDGET_POLICY = PolicyRef(id="gateway.budget", version="v1")

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
    budget_reevaluated: bool = Field(
        default=False,
        description="always false: replay re-runs policy only, never the spend budget",
    )
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
        enforcement_mode: EnforcementMode = "enforce",
        identity: IdentityProvider | None = None,
        transaction: Callable[[], AbstractContextManager[None]] = no_transaction,
        verifier: GrantVerifier | None = None,
        approvals: ApprovalStore | None = None,
        approver_roles: Mapping[str, frozenset[str]] | None = None,
        reservations: ReservationStore | None = None,
    ) -> None:
        self.delegations = delegations
        self.credentials = credentials
        self.traces = traces
        self.grants = grants
        self.signer = signer
        # Verifies tokens from the active key and from keys retired less than one
        # grant TTL ago (rotation); defaults to the signer's own public key.
        self.verifier = verifier or GrantVerifier({signer.kid: signer.public_key})
        self.policy_sets = policy_sets
        self.vendors = vendors
        self.tools = tools
        self.grant_ttl_seconds = grant_ttl_seconds
        self.clock = clock
        self.enforcement_mode: EnforcementMode = enforcement_mode
        self.identity: IdentityProvider = identity or BearerCredentialProvider(credentials)
        # One durable unit per kernel operation: its trace events and any
        # grant-state change commit together (one fsync) or roll back together.
        self.transaction = transaction
        self.engine = PolicyEngine()
        self.approvals: ApprovalStore = approvals or InMemoryApprovalStore()
        # Cumulative budgets: reserve at mint, settle on outcome, release on expiry.
        self.reservations: ReservationStore = reservations or InMemoryReservationStore()
        # "kind:id" -> roles. Operator-configured (ATP_APPROVER_ROLES); the only
        # place a principal holds a role.
        self.approver_roles: dict[str, frozenset[str]] = dict(approver_roles or {})
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
        with self._lock, self.transaction():
            self._check_credential_live(caller)
            self._check_trace_owner(trace_id, caller)
            return self.traces.append(trace_id, event_type, caller.agent.id, body)

    # -------------------------------------------------------------- identity
    def _check_credential_live(self, caller: AuthenticatedAgent) -> None:
        """Authentication happened in the HTTP layer, outside the lock. Re-check
        the credential here so a revocation cannot land in between."""
        if not self.identity.is_live(caller.credential_id, now=self.clock()):
            raise AuthError(
                ReasonCode.AGENT_CREDENTIAL_REVOKED, "agent credential was revoked or expired"
            )

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
            # Identity binding runs outside the unit of work on purpose: a
            # rejected impersonation attempt must stay on the record even
            # though the operation fails.
            self._bind_identity(envelope, caller)
            with self.transaction():
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
        decision = self.engine.evaluate(policy_set, ctx).model_copy(
            update={"enforcement": self.enforcement_mode}
        )
        # Budgets are checked before an approval is used, so an over-budget
        # retry neither spends the approval nor mints a grant, and an
        # over-budget action is never put to an approver at all.
        decision, lines, amount = self._check_budgets(envelope, authority, decision, now)
        used_approval: ApprovalRecord | None = None
        if decision.outcome is DecisionOutcome.REQUIRE_APPROVAL and decision.approval:
            decision, used_approval = self._apply_approval(envelope, decision, now)

        claims: GrantClaims | None = None
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
            if lines and amount is not None:
                # Atomic sum check + insert. Under the gateway lock and inside
                # the authorize transaction this agrees with the check above;
                # it is the check that holds across processes.
                reserved = self.reservations.reserve(
                    claims.grant_id, lines, amount, expires_at=claims.expires_at, now=now
                )
                if not reserved.ok:
                    decision = _budget_denial(decision, reserved)
                    claims = None
        self._record_decision(decision)

        grant: IssuedGrant | None = None
        if claims is not None:
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
                    "kid": self.signer.kid,
                    **({"approval_id": used_approval.claims.approval_id} if used_approval else {}),
                },
            )
        elif decision.outcome is DecisionOutcome.REQUIRE_APPROVAL and decision.approval:
            self.traces.append(
                trace_id,
                EventType.APPROVAL_REQUESTED,
                GATEWAY_ACTOR,
                decision.approval.model_dump(mode="json"),
            )
        if decision.is_shadow_denial:
            # Shadow mode: no grant is minted (the kernel invariant holds), but
            # the record says so explicitly so nobody mistakes this for a block.
            self.traces.append(
                trace_id,
                EventType.SHADOW_WOULD_DENY,
                GATEWAY_ACTOR,
                {
                    "would": decision.outcome.value,
                    "reason_code": decision.reason_code.value,
                    "message": decision.explanation,
                    "enforced": False,
                },
            )

        return AuthorizationResult(decision=decision, execution_grant=grant)

    # ---------------------------------------------------------------- budgets
    def _check_budgets(
        self,
        envelope: ActionEnvelope,
        authority: EffectiveAuthority | None,
        decision: Decision,
        now: datetime,
    ) -> tuple[Decision, list[BudgetLine], Money | None]:
        """Peek at every budget on the chain for an action that would otherwise
        go ahead (ALLOW or REQUIRE_APPROVAL). An action is budgeted when its
        arguments carry an ``amount``; ``currency`` defaults to the budget's."""
        if (
            authority is None
            or not authority.budgets
            or decision.outcome is DecisionOutcome.DENY
            or "amount" not in envelope.arguments
        ):
            return decision, [], None
        currencies = sorted({cb.budget.amount.currency for cb in authority.budgets})
        raw_currency = envelope.arguments.get("currency")
        currency = raw_currency if raw_currency is not None else currencies[0]
        try:
            raw = envelope.arguments["amount"]
            if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
                raise ValueError(raw)
            amount = Money.model_validate({"amount": raw, "currency": currency})
        except (ValueError, InvalidOperation):
            return (
                _deny(
                    decision,
                    ReasonCode.PAYMENT_ARGUMENTS_INVALID,
                    "a budget applies to this action, and its amount/currency is not a valid "
                    "non-negative amount with at most 2 decimals",
                ),
                [],
                None,
            )
        if currencies != [amount.currency]:
            return (
                _deny(
                    decision,
                    ReasonCode.PAYMENT_CURRENCY_NOT_PERMITTED,
                    f"the delegation chain budgets spend in {', '.join(currencies)}; "
                    f"this action is in {amount.currency}, which no budget can count",
                    ConstraintEvaluation(
                        name="budget.currency",
                        requested=amount.currency,
                        limit=currencies,
                        satisfied=False,
                    ),
                ),
                [],
                None,
            )
        lines = budget_lines(authority.budgets, authority.root_principal, now)
        result = self.reservations.usage(lines, amount, now)
        if not result.ok:
            return _budget_denial(decision, result), [], None
        binding = result.binding
        assert binding is not None
        passed = PolicyEvaluation(
            policy=BUDGET_POLICY,
            outcome=DecisionOutcome.ALLOW,
            reason_code=ReasonCode.ALLOWED,
            message=f"{amount} fits every budget on the chain",
            constraints=(_budget_constraint(binding, satisfied=True),),
        )
        return (
            decision.model_copy(update={"evaluations": (*decision.evaluations, passed)}),
            lines,
            amount,
        )

    # -------------------------------------------------------------- approvals
    def _apply_approval(
        self, envelope: ActionEnvelope, decision: Decision, now: datetime
    ) -> tuple[Decision, ApprovalRecord | None]:
        """Turn a REQUIRE_APPROVAL into ALLOW when a valid, unused approval for
        this trace and this exact ``action_hash`` exists, and use it up. Runs
        inside the authorize transaction, so the use and the grant commit
        together. No matching approval: the decision is unchanged."""
        requirement = decision.approval
        assert requirement is not None
        matching = [
            r
            for r in self.approvals.for_trace(envelope.trace_id)
            if r.claims.action_hash == envelope.action_hash
        ]
        if not matching:
            return decision, None
        record = matching[-1]
        claims = record.claims

        def deny(code: ReasonCode, message: str) -> tuple[Decision, None]:
            return (
                decision.model_copy(
                    update={
                        "outcome": DecisionOutcome.DENY,
                        "reason_code": code,
                        "explanation": message,
                    }
                ),
                None,
            )

        try:
            self.verifier.verify_detached(
                claims.kid, claims.signing_input(), decode_signature(record.signature), now=now
            )
        except (GrantError, ValueError):
            return deny(ReasonCode.APPROVAL_INVALID, "the recorded approval does not verify")
        if record.status is ApprovalStatus.DENIED:
            return deny(
                ReasonCode.APPROVAL_DENIED,
                f"{claims.approver} ({claims.approver_role}) denied this action",
            )
        if claims.approver_role != requirement.approver_role:
            return deny(
                ReasonCode.APPROVER_ROLE_MISSING,
                f"the approval was given as {claims.approver_role}; this action requires "
                f"{requirement.approver_role}",
            )
        if record.status is ApprovalStatus.USED:
            return deny(
                ReasonCode.APPROVAL_ALREADY_USED,
                f"approval {claims.approval_id} was already used for one execution grant",
            )
        if claims.is_expired(now):
            return deny(
                ReasonCode.APPROVAL_EXPIRED,
                f"approval {claims.approval_id} expired at {claims.expires_at.isoformat()}",
            )
        if not self.approvals.use(claims.approval_id, now):
            return deny(
                ReasonCode.APPROVAL_ALREADY_USED,
                f"approval {claims.approval_id} was already used for one execution grant",
            )
        allowed = decision.model_copy(
            update={
                "outcome": DecisionOutcome.ALLOW,
                "reason_code": ReasonCode.ALLOWED,
                "explanation": f"{decision.explanation}; approved by {claims.approver} "
                f"({claims.approver_role}), approval {claims.approval_id}",
                "approval": None,
            }
        )
        return allowed, record

    def approve(
        self,
        trace_id: str,
        approver: PrincipalRef,
        decision: Literal["approve", "deny"],
        *,
        expires_in: timedelta,
    ) -> ApprovalRecord:
        """Record a human decision on a REQUIRE_APPROVAL trace. The caller has
        already authenticated as the operator; the approver must hold the
        decision's ``approver_role`` in the configured role map. One decision
        per trace: approve or deny, and it is final."""
        with self._lock, self.transaction():
            now = self.clock()
            view = self.get_trace(trace_id)
            original = view.decision
            if (
                original is None
                or view.envelope is None
                or original.outcome is not DecisionOutcome.REQUIRE_APPROVAL
                or original.approval is None
            ):
                raise ATPError(
                    ReasonCode.APPROVAL_NOT_REQUESTED,
                    f"trace {trace_id} has no REQUIRE_APPROVAL decision to approve",
                )
            requirement: ApprovalRequirement = original.approval
            if requirement.approver_role not in roles_for(self.approver_roles, approver):
                raise ATPError(
                    ReasonCode.APPROVER_ROLE_MISSING,
                    f"{approver} does not hold the role {requirement.approver_role!r} "
                    "this action requires (configure ATP_APPROVER_ROLES)",
                )
            existing = self.approvals.for_trace(trace_id)
            if existing:
                prior = existing[-1]
                raise ATPError(
                    ReasonCode.APPROVAL_ALREADY_DECIDED,
                    f"trace {trace_id} already has a {prior.status.value} decision by "
                    f"{prior.claims.approver}; approvals are final",
                )
            claims = ApprovalClaims(
                approval_id=new_id("apr"),
                trace_id=trace_id,
                envelope_id=view.envelope.envelope_id,
                action_hash=original.action_hash,
                decision_id=original.decision_id,
                approver=approver,
                approver_role=requirement.approver_role,
                decision=decision,
                issued_at=now,
                expires_at=now + expires_in,
                kid=self.signer.kid,
            )
            record = ApprovalRecord(
                claims=claims,
                signature=encode_signature(self.signer.sign_detached(claims.signing_input())),
                status=ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.DENIED,
            )
            self.approvals.put(record)
            self.traces.append(
                trace_id,
                EventType.APPROVAL_GRANTED if decision == "approve" else EventType.APPROVAL_DENIED,
                GATEWAY_ACTOR,
                {
                    **claims.model_dump(mode="json"),
                    "signature": record.signature,
                    "authorized_by": "operator",
                },
            )
            return record

    def report_shadow_outcome(
        self,
        trace_id: str,
        caller: AuthenticatedAgent,
        *,
        succeeded: bool,
        summary: dict[str, Any],
    ) -> TraceEvent:
        """A trusted executor reports that it ran an action the gateway would
        have denied, because the gateway is in shadow mode. Only the trace
        owner may report, only when the recorded decision is a shadow
        denial, and only once."""
        with self._lock, self.transaction():
            self._check_credential_live(caller)
            self._check_trace_owner(trace_id, caller)
            view = self.get_trace(trace_id)
            if view.decision is None or not view.decision.is_shadow_denial:
                raise ATPError(
                    ReasonCode.SHADOW_OUTCOME_NOT_APPLICABLE,
                    "this trace has no shadow-mode denial to report an outcome for",
                )
            if any(
                e.event_type
                in (EventType.SHADOW_EXECUTION_COMPLETED, EventType.SHADOW_EXECUTION_FAILED)
                for e in view.events
            ):
                raise ATPError(
                    ReasonCode.SHADOW_OUTCOME_ALREADY_REPORTED,
                    "a shadow outcome was already reported for this trace",
                )
            event_type = (
                EventType.SHADOW_EXECUTION_COMPLETED
                if succeeded
                else EventType.SHADOW_EXECUTION_FAILED
            )
            return self.traces.append(
                trace_id,
                event_type,
                caller.agent.id,
                {
                    "reported_by": "external_executor",
                    "credential_id": caller.credential_id,
                    "enforced": False,
                    "would": view.decision.outcome.value,
                    "reason_code": view.decision.reason_code.value,
                    "summary": summary,
                },
            )

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
            with self.transaction():
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
            # Consumed: from here the action may happen, so its reservation
            # no longer lapses with the grant; only an outcome ends it.
            held = self.reservations.hold(claims.grant_id)
        except (GrantError, DelegationError) as exc:
            return self._blocked(envelope, exc.reason_code, exc.message)
        if not held:
            # The reservation was already released: expired by a peer gateway
            # whose clock runs ahead. Never run a budgeted action unbudgeted.
            return self._blocked(
                envelope,
                ReasonCode.PAYMENT_EXCEEDS_BUDGET,
                "the budget reservation for this grant was released before execution "
                "(clock skew between gateways?); authorize again",
            )

        try:
            tool = self.tools.get(envelope.tool)
            result = tool.execute(envelope)
        except ToolError as exc:
            self.reservations.release(claims.grant_id)
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

        if result.get("status") == "released":
            # External executor: the gateway has bound and consumed the grant;
            # the trusted executor performs the side effect and reports back.
            self.traces.append(
                trace_id,
                EventType.EXECUTION_RELEASED,
                GATEWAY_ACTOR,
                {"grant_id": claims.grant_id, "tool": envelope.tool, "executor": "external"},
            )
            return ExecutionResult(
                trace_id=trace_id,
                envelope_id=envelope.envelope_id,
                status="released",
                reason_code=ReasonCode.EXECUTION_RELEASED,
                message=f"{envelope.qualified_action} released to the external executor",
                result=result,
            )

        self.reservations.settle(claims.grant_id)
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

    def report_outcome(
        self,
        grant_id: str,
        caller: AuthenticatedAgent | None,
        *,
        succeeded: bool,
        summary: dict[str, Any],
        operator: bool = False,
    ) -> TraceEvent:
        """An external executor reports what happened after a release.

        Bound to the consumed grant: only its audience may report, only once,
        and only for a grant the gateway actually released.

        The report is trusted for budgets only one way. Success settles the
        reservation. A failure reported by the grant's own agent does NOT
        release it (fail closed): otherwise an agent could lie about a payment
        that moved, free the budget and repeat. Only the operator can confirm
        a failure and release the reservation, once, also after the agent's
        own report.
        """
        with self._lock, self.transaction():
            if not operator:
                if caller is None:
                    raise AuthError(
                        ReasonCode.AGENT_CREDENTIAL_MISSING, "agent credential required"
                    )
                self._check_credential_live(caller)
            record = self.grants.get(grant_id)
            if record is None or (
                not operator and caller is not None and record.claims.agent_id != caller.agent.id
            ):
                raise GrantError(
                    ReasonCode.GRANT_AUDIENCE_MISMATCH,
                    "no released grant for this agent with that id",
                )
            trace_id = record.claims.trace_id
            events = self.traces.events(trace_id)
            released = any(
                e.event_type is EventType.EXECUTION_RELEASED
                and e.payload.get("grant_id") == grant_id
                for e in events
            )
            if not released:
                raise ATPError(
                    ReasonCode.EXECUTION_OUTCOME_NOT_RELEASED,
                    "the grant was not released to an external executor",
                )
            already = any(
                e.event_type in (EventType.EXECUTION_COMPLETED, EventType.EXECUTION_FAILED)
                and e.payload.get("grant_id") == grant_id
                and (not operator or e.payload.get("reported_by") == "operator")
                for e in events
            )
            if already:
                raise ATPError(
                    ReasonCode.EXECUTION_OUTCOME_ALREADY_REPORTED,
                    "an outcome was already reported for this grant",
                )
            event_type = EventType.EXECUTION_COMPLETED if succeeded else EventType.EXECUTION_FAILED
            # Settled at the reserved amount: the report comes from the agent's
            # side, so a lower "actual" in it is not trusted to free budget.
            if succeeded:
                self.reservations.settle(grant_id)
            elif operator:
                self.reservations.release(grant_id)
            # else: an agent-reported failure leaves the reservation held.
            if operator:
                return self.traces.append(
                    trace_id,
                    event_type,
                    GATEWAY_ACTOR,
                    {"grant_id": grant_id, "reported_by": "operator", "summary": summary},
                )
            assert caller is not None
            return self.traces.append(
                trace_id,
                event_type,
                caller.agent.id,
                {
                    "grant_id": grant_id,
                    "reported_by": "external_executor",
                    "credential_id": caller.credential_id,
                    "summary": summary,
                    **({} if succeeded else {"budget": "held_until_operator_confirms"}),
                },
            )

    def _verify_grant(
        self, envelope: ActionEnvelope, token: str | None, now: datetime
    ) -> GrantClaims:
        if not token:
            raise GrantError(
                ReasonCode.GRANT_MISSING,
                "execution requires a grant issued by /authorize; none was presented",
            )
        claims = self.verifier.verify(token, now=now)
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
        with self._lock, self.transaction():
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
        # Replay re-runs policy only. Budgets depend on spend at the time, so a
        # decision the budget check made is not re-evaluated, and the policy
        # still letting the action reach that check is no change.
        budget_decided = original.matched_policy == BUDGET_POLICY
        if budget_decided and replayed.outcome is not DecisionOutcome.DENY:
            changed = False
        else:
            changed = replayed.outcome != original.outcome or (
                replayed.reason_code != original.reason_code
            )
        summary = (
            f"{original.policy_set_version}: {original.outcome.value} "
            f"({original.reason_code.value}) -> {policy_set.version}: "
            f"{replayed.outcome.value} ({replayed.reason_code.value})"
        )
        if budget_decided:
            summary += "; budget not re-evaluated (replay re-runs policy only)"
        self.traces.append(
            trace_id,
            EventType.REPLAY_PERFORMED,
            GATEWAY_ACTOR,
            {
                "original_decision_id": original.decision_id,
                "original_policy_set_version": original.policy_set_version,
                "replayed_policy_set_version": policy_set.version,
                "outcome_changed": changed,
                "budget_reevaluated": False,
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
            budget_reevaluated=False,
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
                EventType.EXECUTION_RELEASED,
                EventType.EXECUTION_COMPLETED,
                EventType.EXECUTION_FAILED,
                EventType.SHADOW_EXECUTION_COMPLETED,
                EventType.SHADOW_EXECUTION_FAILED,
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
        # Lazy housekeeping: reservations whose grant expired unused stop
        # counting against their budget (consumed ones are held until an outcome).
        with self._lock, self.transaction():
            self.reservations.release_expired(self.clock())
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


def _deny(
    decision: Decision,
    code: ReasonCode,
    message: str,
    constraint: ConstraintEvaluation | None = None,
) -> Decision:
    evaluation = PolicyEvaluation(
        policy=BUDGET_POLICY,
        outcome=DecisionOutcome.DENY,
        reason_code=code,
        message=message,
        constraints=(constraint,) if constraint else (),
    )
    return decision.model_copy(
        update={
            "outcome": DecisionOutcome.DENY,
            "reason_code": code,
            "explanation": message,
            "matched_policy": BUDGET_POLICY,
            "evaluations": (*decision.evaluations, evaluation),
            "approval": None,
        }
    )


def _budget_constraint(usage: BudgetUsage, *, satisfied: bool) -> ConstraintEvaluation:
    line = usage.line
    return ConstraintEvaluation(
        name="budget",
        requested=format(usage.requested.amount, "f"),
        limit=format(line.limit.amount, "f"),
        satisfied=satisfied,
        detail=(
            f"limit={line.limit.amount:f} spent={usage.spent:f} reserved={usage.reserved:f} "
            f"requested={usage.requested.amount:f} {line.limit.currency} per {line.period} "
            f"from {line.period_start.date().isoformat()} UTC, grant {line.grant_id}"
        ),
    )


def _budget_denial(decision: Decision, result: ReservationResult) -> Decision:
    usage = result.binding
    assert usage is not None
    line = usage.line
    return _deny(
        decision,
        ReasonCode.PAYMENT_EXCEEDS_BUDGET,
        f"requested {usage.requested} exceeds the {line.period} budget set on grant "
        f"{line.grant_id}: limit {line.limit.amount:f}, spent {usage.spent:f}, reserved "
        f"{usage.reserved:f}, {max(usage.remaining, Decimal('0')):f} {line.limit.currency} "
        "left this period",
        _budget_constraint(usage, satisfied=False),
    )


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

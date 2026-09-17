"""The accounts-payable workflow, wired through the trust plane.

Sequence for one task:

0. the client is authenticated as the agent (bearer credential)
1. record ``task_received``
2. open the invoice and record ``external_content_ingested`` (untrusted, hashed)
3. ask the brain for a proposal
4. build an ``ActionEnvelope`` and call ``/authorize``
5. on ALLOW, call ``/execute`` with the grant; otherwise stop

The agent never executes anything itself and never sees a payments API.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from atp_adapter_http import AuthorizeResponse, ExecuteResponse, TrustPlaneClient
from atp_core import (
    ActionEnvelope,
    ContentSource,
    ContentTrust,
    PrincipalRef,
    Provenance,
    new_id,
    new_trace_id,
)
from finance_agent.agent import AgentBrain, ProposedAction
from finance_agent.invoices import Invoice

DEFAULT_TASK = "Review this invoice and pay the vendor if everything looks correct."


class AgentRunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    envelope: ActionEnvelope
    proposal: ProposedAction
    authorization: AuthorizeResponse
    execution: ExecuteResponse | None = None

    @property
    def outcome(self) -> str:
        return self.authorization.decision.outcome.value

    @property
    def executed(self) -> bool:
        return self.execution is not None and self.execution.executed

    def decision_block(self) -> str:
        """The human-readable block the demo prints."""
        d = self.authorization.decision
        auth = d.effective_authority
        limit = auth.constraints.max_amount if auth and auth.constraints.max_amount else None
        args = self.envelope.arguments
        policy_line = (
            d.matched_policy.qualified if d.matched_policy else "all applicable policies passed"
        )
        lines = [
            f"DECISION: {d.outcome.value}",
            "",
            "Reason:",
            f"  {d.reason_code.value}",
            "",
            "Agent:",
            f"  {self.envelope.agent.id}",
            "",
            "Requested:",
            f"  {args.get('currency', '')} {args.get('amount', '')}"
            + (f" -> {args['destination_account']}" if args.get("destination_account") else ""),
            "",
            "Authorized maximum:",
            f"  {limit if limit else 'n/a'}",
            "",
            "Policy:",
            f"  {policy_line}",
            "",
            "Trace:",
            f"  {self.trace_id}",
        ]
        if self.execution is not None:
            lines += [
                "",
                "Execution:",
                f"  {self.execution.status} ({self.execution.reason_code.value})",
            ]
        return "\n".join(lines)


def run_accounts_payable(
    client: TrustPlaneClient,
    brain: AgentBrain,
    invoice: Invoice,
    *,
    principal: PrincipalRef,
    agent: PrincipalRef,
    delegation_grant_id: str,
    task: str = DEFAULT_TASK,
    policy_set_version: str | None = None,
    attempt_execution_when_denied: bool = True,
) -> AgentRunResult:
    trace_id = new_trace_id()
    task_id = new_id("task")

    client.record_event(
        trace_id,
        "task_received",
        {"task_id": task_id, "task": task, "principal": principal.model_dump(mode="json")},
    )

    source = ContentSource(
        source_id=invoice.invoice_id,
        kind="invoice_pdf",
        origin=invoice.origin,
        trust=ContentTrust.UNTRUSTED,
        content_hash=invoice.content_hash,
        excerpt=_excerpt(invoice.raw_text),
    )
    client.record_event(
        trace_id,
        "external_content_ingested",
        {"source": source.model_dump(mode="json"), "characters": len(invoice.raw_text)},
    )

    proposal = brain.propose(task, invoice.raw_text)

    arguments: dict[str, Any] = {"amount": proposal.amount, "currency": proposal.currency}
    if proposal.destination_account is not None:
        arguments["destination_account"] = proposal.destination_account
    envelope = ActionEnvelope(
        trace_id=trace_id,
        principal=principal,
        agent=agent,
        delegation_grant_id=delegation_grant_id,
        capability="pay:vendor",
        tool="payments",
        action="send_payment",
        resource=f"vendor:{proposal.vendor_id}",
        arguments=arguments,
        provenance=Provenance(
            task_id=task_id,
            task_description=task,
            content_sources=(source,),
            model=brain.name,
            agent_rationale=proposal.rationale,
        ),
    )

    authorization = client.authorize(envelope, policy_set_version=policy_set_version)

    execution: ExecuteResponse | None = None
    if authorization.execution_grant is not None:
        execution = client.execute(envelope, authorization.execution_grant)
    elif attempt_execution_when_denied:
        # A compromised or careless agent would try anyway. Record that it cannot.
        execution = client.execute(envelope, None)

    return AgentRunResult(
        trace_id=trace_id,
        envelope=envelope,
        proposal=proposal,
        authorization=authorization,
        execution=execution,
    )


def _excerpt(text: str, limit: int = 600) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."

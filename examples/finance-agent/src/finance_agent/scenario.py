"""The demo's delegation graph and agent identities, issued through the gateway API.

Seeding is an operator action: the operator issues one credential per agent,
then the human-rooted grants. Each agent-to-agent delegation is then made by
the grantor itself, authenticated with its own credential, exactly as it
would be in a deployment.

Human (company-user-42)          payments <= $10,000
  └─ finance-orchestrator        payments <= $10,000
       └─ accounts-payable-agent payments <= $1,000
            └─ document-agent    read-only invoice access
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from atp_adapter_http import TrustPlaneClient
from atp_core import PrincipalKind, PrincipalRef, utcnow

HUMAN = PrincipalRef(id="company-user-42", kind=PrincipalKind.HUMAN)
ORCHESTRATOR = PrincipalRef(id="finance-orchestrator", kind=PrincipalKind.AGENT)
AP_AGENT = PrincipalRef(id="accounts-payable-agent", kind=PrincipalKind.AGENT)
DOC_AGENT = PrincipalRef(id="document-agent", kind=PrincipalKind.AGENT)


class DelegationGraph(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    root: str
    orchestrator: str
    accounts_payable: str
    document: str


@dataclass(frozen=True)
class AgentIdentities:
    """Bearer tokens for the demo agents. A plain dataclass, never a pydantic
    model, so it cannot end up serialised into a trace or a response."""

    orchestrator_token: str
    accounts_payable_token: str
    document_token: str
    credential_ids: dict[str, str]

    def __repr__(self) -> str:
        return f"AgentIdentities(credential_ids={self.credential_ids})"


@dataclass(frozen=True)
class DemoSeed:
    graph: DelegationGraph
    identities: AgentIdentities


def _usd(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "USD"}


def issue_agent_credentials(operator: TrustPlaneClient, label: str = "demo") -> AgentIdentities:
    """Operator-only: mint one credential per demo agent."""
    ids: dict[str, str] = {}
    tokens: dict[str, str] = {}
    for agent in (ORCHESTRATOR, AP_AGENT, DOC_AGENT):
        issued = operator.issue_credential(
            agent.model_dump(mode="json"), label=f"{label}:{agent.id}"
        )
        ids[agent.id] = issued["credential_id"]
        tokens[agent.id] = issued["token"]
    return AgentIdentities(
        orchestrator_token=tokens[ORCHESTRATOR.id],
        accounts_payable_token=tokens[AP_AGENT.id],
        document_token=tokens[DOC_AGENT.id],
        credential_ids=ids,
    )


def seed_delegation_graph(
    operator: TrustPlaneClient,
    *,
    now: datetime | None = None,
    ap_limit: str = "1000",
    ap_ttl: timedelta = timedelta(days=1),
    identities: AgentIdentities | None = None,
) -> DemoSeed:
    """Build the demo chain. ``operator`` must hold the operator key."""
    now = now or utcnow()
    identities = identities or issue_agent_credentials(operator)
    as_orchestrator = operator.as_agent(identities.orchestrator_token)
    as_ap = operator.as_agent(identities.accounts_payable_token)

    def issue(client: TrustPlaneClient, body: dict[str, Any]) -> str:
        grant_id: str = client.issue_delegation(body)["grant_id"]
        return grant_id

    root = issue(
        operator,
        {
            "label": "Human authority: payments <= $10,000",
            "grantor": HUMAN.model_dump(mode="json"),
            "grantee": HUMAN.model_dump(mode="json"),
            "capabilities": ["read:invoice", "pay:vendor", "admin:vendors"],
            "resource_scope": ["vendor:*", "invoice:*"],
            "constraints": {"max_amount": _usd("10000"), "currencies": ["USD"]},
            "expires_at": (now + timedelta(days=30)).isoformat(),
        },
    )
    orchestrator = issue(
        operator,
        {
            "label": "Finance orchestrator: payments <= $10,000",
            "grantor": HUMAN.model_dump(mode="json"),
            "grantee": ORCHESTRATOR.model_dump(mode="json"),
            "parent_grant_id": root,
            "capabilities": ["read:invoice", "pay:vendor"],
            "resource_scope": ["vendor:*", "invoice:*"],
            "constraints": {"max_amount": _usd("10000")},
            "expires_at": (now + timedelta(days=7)).isoformat(),
        },
    )
    accounts_payable = issue(
        as_orchestrator,
        {
            "label": f"Accounts-payable agent: vendor payments <= ${int(ap_limit):,}",
            "grantor": ORCHESTRATOR.model_dump(mode="json"),
            "grantee": AP_AGENT.model_dump(mode="json"),
            "parent_grant_id": orchestrator,
            "capabilities": ["read:invoice", "pay:vendor"],
            "resource_scope": ["vendor:*", "invoice:*"],
            "constraints": {"max_amount": _usd(ap_limit)},
            "expires_at": (now + ap_ttl).isoformat(),
        },
    )
    document = issue(
        as_ap,
        {
            "label": "Document agent: read-only invoice access",
            "grantor": AP_AGENT.model_dump(mode="json"),
            "grantee": DOC_AGENT.model_dump(mode="json"),
            "parent_grant_id": accounts_payable,
            "capabilities": ["read:invoice"],
            "resource_scope": ["invoice:*"],
            "constraints": {"max_amount": _usd("0")},
            "expires_at": (now + min(ap_ttl, timedelta(hours=1))).isoformat(),
        },
    )
    graph = DelegationGraph(
        root=root,
        orchestrator=orchestrator,
        accounts_payable=accounts_payable,
        document=document,
    )
    return DemoSeed(graph=graph, identities=identities)

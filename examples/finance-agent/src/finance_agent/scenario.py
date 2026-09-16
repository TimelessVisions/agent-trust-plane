"""The demo's delegation graph, issued through the gateway API.

Human (company-user-42)          payments <= $10,000
  └─ finance-orchestrator        payments <= $10,000
       └─ accounts-payable-agent payments <= $1,000
            └─ document-agent    read-only invoice access
"""

from __future__ import annotations

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


def _usd(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "USD"}


def seed_delegation_graph(
    client: TrustPlaneClient,
    *,
    now: datetime | None = None,
    ap_limit: str = "1000",
    ap_ttl: timedelta = timedelta(days=1),
) -> DelegationGraph:
    now = now or utcnow()

    def issue(body: dict[str, Any]) -> str:
        grant_id: str = client.issue_delegation(body)["grant_id"]
        return grant_id

    root = issue(
        {
            "label": "Human authority: payments <= $10,000",
            "grantor": HUMAN.model_dump(mode="json"),
            "grantee": HUMAN.model_dump(mode="json"),
            "capabilities": ["read:invoice", "pay:vendor", "admin:vendors"],
            "resource_scope": ["vendor:*", "invoice:*"],
            "constraints": {"max_amount": _usd("10000"), "currencies": ["USD"]},
            "expires_at": (now + timedelta(days=30)).isoformat(),
        }
    )
    orchestrator = issue(
        {
            "label": "Finance orchestrator: payments <= $10,000",
            "grantor": HUMAN.model_dump(mode="json"),
            "grantee": ORCHESTRATOR.model_dump(mode="json"),
            "parent_grant_id": root,
            "capabilities": ["read:invoice", "pay:vendor"],
            "resource_scope": ["vendor:*", "invoice:*"],
            "constraints": {"max_amount": _usd("10000")},
            "expires_at": (now + timedelta(days=7)).isoformat(),
        }
    )
    accounts_payable = issue(
        {
            "label": f"Accounts-payable agent: vendor payments <= ${int(ap_limit):,}",
            "grantor": ORCHESTRATOR.model_dump(mode="json"),
            "grantee": AP_AGENT.model_dump(mode="json"),
            "parent_grant_id": orchestrator,
            "capabilities": ["read:invoice", "pay:vendor"],
            "resource_scope": ["vendor:*", "invoice:*"],
            "constraints": {"max_amount": _usd(ap_limit)},
            "expires_at": (now + ap_ttl).isoformat(),
        }
    )
    document = issue(
        {
            "label": "Document agent: read-only invoice access",
            "grantor": AP_AGENT.model_dump(mode="json"),
            "grantee": DOC_AGENT.model_dump(mode="json"),
            "parent_grant_id": accounts_payable,
            "capabilities": ["read:invoice"],
            "resource_scope": ["invoice:*"],
            "constraints": {"max_amount": _usd("0")},
            "expires_at": (now + min(ap_ttl, timedelta(hours=1))).isoformat(),
        }
    )
    return DelegationGraph(
        root=root,
        orchestrator=orchestrator,
        accounts_payable=accounts_payable,
        document=document,
    )

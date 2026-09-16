"""Shared fixtures for gateway tests: an in-memory runtime with a controllable
clock, wrapped in a FastAPI TestClient."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atp_core import PrincipalKind, PrincipalRef, new_id, new_trace_id
from atp_gateway import GatewaySettings, Runtime, build_runtime, create_app

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
HUMAN = PrincipalRef(id="company-user-42", kind=PrincipalKind.HUMAN)
ORCHESTRATOR = PrincipalRef(id="finance-orchestrator", kind=PrincipalKind.AGENT)
AP_AGENT = PrincipalRef(id="accounts-payable-agent", kind=PrincipalKind.AGENT)
DOC_AGENT = PrincipalRef(id="document-agent", kind=PrincipalKind.AGENT)
ATTACKER_ACCOUNT = "acct-offshore-9931"


class Clock:
    def __init__(self, start: datetime = NOW) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now = self.now + timedelta(**kwargs)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def runtime(clock: Clock) -> Iterator[Runtime]:
    settings = GatewaySettings(
        database_path=":memory:",
        grant_signing_key="test-signing-key-that-is-at-least-32-bytes-long!!",
        grant_ttl_seconds=120,
    )
    rt = build_runtime(settings)
    rt.trust_plane.clock = clock
    yield rt
    rt.close()


@pytest.fixture
def client(runtime: Runtime) -> Iterator[TestClient]:
    app = create_app(runtime.settings, runtime=runtime)
    with TestClient(app) as c:
        yield c


def usd(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "USD"}


def seed_chain(client: TestClient, now: datetime = NOW) -> dict[str, str]:
    """Human ($10k) -> orchestrator ($10k) -> AP agent ($1k) -> doc agent (read-only)."""

    def issue(body: dict[str, Any]) -> str:
        r = client.post("/delegations", json=body)
        assert r.status_code == 201, r.text
        grant_id: str = r.json()["grant_id"]
        return grant_id

    root = issue(
        {
            "label": "Human authority: payments <= $10,000",
            "grantor": HUMAN.model_dump(mode="json"),
            "grantee": HUMAN.model_dump(mode="json"),
            "capabilities": ["read:invoice", "pay:vendor", "admin:vendors"],
            "resource_scope": ["vendor:*", "invoice:*"],
            "constraints": {"max_amount": usd("10000"), "currencies": ["USD"]},
            "expires_at": (now + timedelta(days=30)).isoformat(),
        }
    )
    orch = issue(
        {
            "label": "Orchestrator: payments <= $10,000",
            "grantor": HUMAN.model_dump(mode="json"),
            "grantee": ORCHESTRATOR.model_dump(mode="json"),
            "parent_grant_id": root,
            "capabilities": ["read:invoice", "pay:vendor"],
            "resource_scope": ["vendor:*", "invoice:*"],
            "constraints": {"max_amount": usd("10000")},
            "expires_at": (now + timedelta(days=7)).isoformat(),
        }
    )
    ap = issue(
        {
            "label": "AP agent: vendor payments <= $1,000",
            "grantor": ORCHESTRATOR.model_dump(mode="json"),
            "grantee": AP_AGENT.model_dump(mode="json"),
            "parent_grant_id": orch,
            "capabilities": ["read:invoice", "pay:vendor"],
            "resource_scope": ["vendor:*", "invoice:*"],
            "constraints": {"max_amount": usd("1000")},
            "expires_at": (now + timedelta(days=1)).isoformat(),
        }
    )
    doc = issue(
        {
            "label": "Document agent: read-only invoice access",
            "grantor": AP_AGENT.model_dump(mode="json"),
            "grantee": DOC_AGENT.model_dump(mode="json"),
            "parent_grant_id": ap,
            "capabilities": ["read:invoice"],
            "resource_scope": ["invoice:*"],
            "constraints": {"max_amount": usd("0")},
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
    )
    return {"root": root, "orch": orch, "ap": ap, "doc": doc}


def payment_envelope(
    grant_id: str,
    *,
    amount: str = "480.00",
    agent: PrincipalRef = AP_AGENT,
    resource: str = "vendor:128",
    capability: str = "pay:vendor",
    destination: str | None = None,
    trace_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    args: dict[str, Any] = {"amount": amount, "currency": "USD"}
    if destination:
        args["destination_account"] = destination
    body: dict[str, Any] = {
        "envelope_id": new_id("env"),
        "trace_id": trace_id or new_trace_id(),
        "principal": HUMAN.model_dump(mode="json"),
        "agent": agent.model_dump(mode="json"),
        "delegation_grant_id": grant_id,
        "capability": capability,
        "tool": "payments",
        "action": "send_payment",
        "resource": resource,
        "arguments": args,
        **extra,
    }
    return body

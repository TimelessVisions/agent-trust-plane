"""Shared fixtures for gateway tests: an in-memory (or temp-file SQLite)
runtime with a controllable clock, wrapped in a FastAPI TestClient, plus
helpers that make every request carry the right credential explicitly."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
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

SIGNING_KEY = "test-signing-key-that-is-at-least-32-bytes-long!!"
OPERATOR_KEY = "test-operator-key-that-is-at-least-32-bytes-long!"


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


@pytest.fixture(params=["memory", "sqlite"])
def runtime(clock: Clock, request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Runtime]:
    db = ":memory:" if request.param == "memory" else str(tmp_path / "atp-test.db")
    settings = GatewaySettings(
        database_path=db,
        grant_signing_key=SIGNING_KEY,
        operator_key=OPERATOR_KEY,
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


# ------------------------------------------------------------------ headers
def op() -> dict[str, str]:
    return {"X-ATP-Operator-Key": OPERATOR_KEY}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def usd(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "USD"}


def issue_credential(
    client: TestClient, agent: PrincipalRef, label: str = "test"
) -> dict[str, Any]:
    r = client.post(
        f"/agents/{agent.id}/credentials",
        json={"agent": agent.model_dump(mode="json"), "label": label},
        headers=op(),
    )
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def seed_chain(client: TestClient, now: datetime = NOW) -> dict[str, Any]:
    """Human ($10k) -> orchestrator ($10k) -> AP agent ($1k) -> doc agent (read-only).

    Returns grant ids under ``root/orch/ap/doc`` plus ``tokens`` and ``creds``
    keyed by the same short names. Human-rooted grants are issued by the
    operator; each agent-to-agent grant by its authenticated grantor.
    """
    creds = {
        "orch": issue_credential(client, ORCHESTRATOR),
        "ap": issue_credential(client, AP_AGENT),
        "doc": issue_credential(client, DOC_AGENT),
    }
    tokens = {k: v["token"] for k, v in creds.items()}

    def issue(body: dict[str, Any], headers: dict[str, str]) -> str:
        r = client.post("/delegations", json=body, headers=headers)
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
        },
        op(),
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
        },
        op(),
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
        },
        bearer(tokens["orch"]),
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
        },
        bearer(tokens["ap"]),
    )
    return {
        "root": root,
        "orch": orch,
        "ap": ap,
        "doc": doc,
        "tokens": tokens,
        "creds": {k: v["credential_id"] for k, v in creds.items()},
    }


def payment_envelope(
    grant_id: str,
    *,
    amount: str = "480.00",
    agent: PrincipalRef = AP_AGENT,
    principal: PrincipalRef = HUMAN,
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
        "principal": principal.model_dump(mode="json"),
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


# -------------------------------------------------------------- shorthands
def authorize(client: TestClient, env: dict[str, Any], token: str, **kwargs: Any) -> dict[str, Any]:
    headers = {**bearer(token), **(kwargs.pop("headers", None) or {})}
    r = client.post("/authorize", json=env, headers=headers, **kwargs)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def execute(
    client: TestClient, env: dict[str, Any], grant: str | None, token: str
) -> dict[str, Any]:
    r = client.post(
        "/execute", json={"envelope": env, "execution_grant": grant}, headers=bearer(token)
    )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def ledger(client: TestClient) -> list[dict[str, Any]]:
    r = client.get("/ledger/payments", headers=op())
    assert r.status_code == 200, r.text
    rows: list[dict[str, Any]] = r.json()
    return rows

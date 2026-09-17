"""Agent-side client for the trust gateway.

An agent framework integrates by building an ``ActionEnvelope`` for every
consequential tool call and going through ``authorize`` then ``execute``.
The client never decides anything; it transports envelopes and grants.

``TrustPlaneClient`` speaks HTTP. It can also be pointed at an ASGI app
in-process (``TrustPlaneClient.for_app(app)``), which is how the eval harness
exercises the real API without a network.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from atp_core import ActionEnvelope, Decision, ReasonCode


class GatewayError(Exception):
    def __init__(self, status_code: int, reason_code: str, message: str) -> None:
        super().__init__(f"{status_code} {reason_code}: {message}")
        self.status_code = status_code
        self.reason_code = reason_code
        self.message = message


class ExecutionGrant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str
    grant_id: str
    expires_at: str


class AuthorizeResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Decision
    execution_grant: ExecutionGrant | None = None


class ExecuteResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    envelope_id: str
    status: str
    reason_code: ReasonCode
    message: str
    result: dict[str, Any] | None = None

    @property
    def executed(self) -> bool:
        return self.status == "completed"


class _SyncASGITransport(httpx.BaseTransport):
    """Drive an ASGI app from synchronous code, one event loop per request.

    httpx's ASGITransport is async-only; this wrapper lets the sync client
    (and therefore the demo agent and the eval harness) talk to the gateway
    in-process through its real routes.
    """

    def __init__(self, app: Any) -> None:
        self._asgi = httpx.ASGITransport(app=app)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        async def _run() -> httpx.Response:
            response = await self._asgi.handle_async_request(request)
            await response.aread()
            return response

        response = asyncio.run(_run())
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )


class TrustPlaneClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        timeout: float = 10.0,
        operator_key: str | None = None,
        agent_token: str | None = None,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout)
        self._operator_key = operator_key
        self._agent_token = agent_token

    @classmethod
    def for_app(
        cls, app: Any, *, operator_key: str | None = None, agent_token: str | None = None
    ) -> TrustPlaneClient:
        """In-process client over an ASGI app (no sockets, real routing)."""
        client = cls.__new__(cls)
        client._http = httpx.Client(
            transport=_SyncASGITransport(app), base_url="http://trust-plane"
        )
        client._operator_key = operator_key
        client._agent_token = agent_token
        return client

    @classmethod
    def from_http(
        cls, http: httpx.Client, *, operator_key: str | None = None, agent_token: str | None = None
    ) -> TrustPlaneClient:
        client = cls.__new__(cls)
        client._http = http
        client._operator_key = operator_key
        client._agent_token = agent_token
        return client

    def as_agent(self, agent_token: str) -> TrustPlaneClient:
        """A client sharing this transport but authenticating as an agent.
        Operator privileges are deliberately not carried over."""
        client = TrustPlaneClient.__new__(TrustPlaneClient)
        client._http = self._http
        client._operator_key = None
        client._agent_token = agent_token
        return client

    def as_operator(self, operator_key: str) -> TrustPlaneClient:
        client = TrustPlaneClient.__new__(TrustPlaneClient)
        client._http = self._http
        client._operator_key = operator_key
        client._agent_token = None
        return client

    def with_operator(self, operator_key: str) -> TrustPlaneClient:
        """Keep the agent identity and add operator privileges (operator tooling only)."""
        client = TrustPlaneClient.__new__(TrustPlaneClient)
        client._http = self._http
        client._operator_key = operator_key
        client._agent_token = self._agent_token
        return client

    @property
    def agent_token(self) -> str | None:
        return self._agent_token

    @property
    def operator_key(self) -> str | None:
        return self._operator_key

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> TrustPlaneClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- helpers
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers: dict[str, str] = dict(kwargs.pop("headers", None) or {})
        if self._agent_token:
            headers.setdefault("Authorization", f"Bearer {self._agent_token}")
        if self._operator_key:
            headers.setdefault("X-ATP-Operator-Key", self._operator_key)
        response = self._http.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            raise GatewayError(
                response.status_code,
                str(body.get("reason_code", "HTTP_ERROR")),
                str(body.get("message") or body.get("detail") or response.text),
            )
        return response.json()

    # ------------------------------------------------------------ operations
    def authorize(
        self, envelope: ActionEnvelope, *, policy_set_version: str | None = None
    ) -> AuthorizeResponse:
        params = {"policy_set_version": policy_set_version} if policy_set_version else None
        data = self._request(
            "POST", "/authorize", json=envelope.model_dump(mode="json"), params=params
        )
        return AuthorizeResponse.model_validate(data)

    def execute(
        self, envelope: ActionEnvelope, grant: ExecutionGrant | str | None
    ) -> ExecuteResponse:
        token = grant.token if isinstance(grant, ExecutionGrant) else grant
        data = self._request(
            "POST",
            "/execute",
            json={"envelope": envelope.model_dump(mode="json"), "execution_grant": token},
        )
        return ExecuteResponse.model_validate(data)

    def record_event(
        self, trace_id: str, event_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Record provenance as the authenticated agent."""
        result: dict[str, Any] = self._request(
            "POST",
            f"/traces/{trace_id}/events",
            json={"event_type": event_type, "payload": payload},
        )
        return result

    def report_outcome(
        self, grant_id: str, *, succeeded: bool, summary: dict[str, Any]
    ) -> dict[str, Any]:
        """External executor: report the result of a released execution."""
        result: dict[str, Any] = self._request(
            "POST",
            f"/executions/{grant_id}/outcome",
            json={"succeeded": succeeded, "summary": summary},
        )
        return result

    def report_shadow_outcome(
        self, trace_id: str, *, succeeded: bool, summary: dict[str, Any]
    ) -> dict[str, Any]:
        """Shadow mode: report that a WOULD_DENY action was executed anyway."""
        result: dict[str, Any] = self._request(
            "POST",
            f"/traces/{trace_id}/shadow-outcome",
            json={"succeeded": succeeded, "summary": summary},
        )
        return result

    # ----------------------------------------------------------- credentials
    def issue_credential(
        self, agent: dict[str, str], label: str, expires_at: str | None = None
    ) -> dict[str, Any]:
        """Operator-only. The returned token is shown once."""
        result: dict[str, Any] = self._request(
            "POST",
            f"/agents/{agent['id']}/credentials",
            json={"agent": agent, "label": label, "expires_at": expires_at},
        )
        return result

    def list_credentials(self, agent_id: str) -> list[dict[str, Any]]:
        """Operator-only. Metadata only; never tokens."""
        result: list[dict[str, Any]] = self._request("GET", f"/agents/{agent_id}/credentials")
        return result

    def revoke_credential(self, credential_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("POST", f"/credentials/{credential_id}/revoke")
        return result

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", f"/traces/{trace_id}")
        return result

    def list_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._request("GET", "/traces", params={"limit": limit})
        return result

    def replay(self, trace_id: str, *, policy_set_version: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "POST", f"/replay/{trace_id}", json={"policy_set_version": policy_set_version}
        )
        return result

    def issue_delegation(self, request: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._request("POST", "/delegations", json=request)
        return result

    def revoke_delegation(self, grant_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("POST", f"/delegations/{grant_id}/revoke")
        return result

    def policy_sets(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._request("GET", "/policy-sets")
        return result

    def run_evals(self) -> dict[str, Any]:
        result: dict[str, Any] = self._request("POST", "/evals/run")
        return result

    def ledger(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._request("GET", "/ledger/payments")
        return result

    def health(self) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", "/health")
        return result

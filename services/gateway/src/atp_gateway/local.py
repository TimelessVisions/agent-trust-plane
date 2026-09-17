"""Run a gateway on a real local port from within a Python process.

Used by the CLI demos, the MCP proxy tests and the benchmark: the proxy is a
separate process that speaks HTTP, so an ASGI-in-process client is not
enough. Ephemeral by default (``:memory:`` database, per-process keys).
"""

from __future__ import annotations

import socket
import threading
import time
from types import TracebackType
from typing import Any

import uvicorn

from atp_adapter_http import AuthorizeResponse, ExecuteResponse, ExecutionGrant, GatewayError
from atp_core import ActionEnvelope, ATPError
from atp_gateway.app import create_app, status_for
from atp_gateway.settings import GatewaySettings
from atp_gateway.wiring import Runtime, build_runtime
from atp_identity import AuthenticatedAgent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


class LocalGateway:
    def __init__(self, settings: GatewaySettings | None = None, *, port: int | None = None) -> None:
        self.settings = settings or GatewaySettings(database_path=":memory:")
        self.port = port or _free_port()
        self.runtime: Runtime = build_runtime(self.settings)
        self._server = uvicorn.Server(
            uvicorn.Config(
                create_app(self.settings, runtime=self.runtime),
                host="127.0.0.1",
                port=self.port,
                log_level="warning",
                lifespan="on",
            )
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True, name="atp-gateway")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def operator_key(self) -> str:
        return self.runtime.operator_key

    def start(self, timeout: float = 10.0) -> LocalGateway:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("gateway did not start in time")
            time.sleep(0.02)
        return self

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)
        self.runtime.close()

    def __enter__(self) -> LocalGateway:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()


class InProcessAgentClient:
    """``AgentClient`` that calls ``TrustPlane`` directly on behalf of one
    authenticated agent, with no HTTP or ASGI layer.

    Used by ``atp mcp wrap``, where the gateway lives in the proxy process:
    the proxy already runs the client in a worker thread, so the synchronous
    kernel is called there. The caller identity is the credential the CLI
    issued for the session and re-verified through the identity provider,
    exactly as the HTTP layer would; liveness is re-checked under the lock
    by the kernel itself. Errors map to ``GatewayError`` with the same
    status/reason codes the HTTP API returns.
    """

    def __init__(self, runtime: Runtime, caller: AuthenticatedAgent) -> None:
        self._tp = runtime.trust_plane
        self._caller = caller

    @classmethod
    def from_token(cls, runtime: Runtime, token: str) -> InProcessAgentClient:
        tp = runtime.trust_plane
        caller = tp.identity.authenticate({"authorization": f"Bearer {token}"}, now=tp.clock())
        return cls(runtime, caller)

    @staticmethod
    def _wrap(exc: ATPError) -> GatewayError:
        return GatewayError(status_for(exc), exc.reason_code.value, exc.message)

    def authorize(
        self, envelope: ActionEnvelope, *, policy_set_version: str | None = None
    ) -> AuthorizeResponse:
        if policy_set_version is not None:
            raise GatewayError(403, "POLICY_SET_OVERRIDE_FORBIDDEN", "agents cannot select policy")
        try:
            result = self._tp.authorize(envelope, self._caller)
        except ATPError as exc:
            raise self._wrap(exc) from exc
        grant = (
            ExecutionGrant(
                token=result.execution_grant.token,
                grant_id=result.execution_grant.grant_id,
                expires_at=result.execution_grant.expires_at.isoformat(),
            )
            if result.execution_grant
            else None
        )
        return AuthorizeResponse(decision=result.decision, execution_grant=grant)

    def execute(
        self, envelope: ActionEnvelope, grant: ExecutionGrant | str | None
    ) -> ExecuteResponse:
        token = grant.token if isinstance(grant, ExecutionGrant) else grant
        try:
            result = self._tp.execute(envelope, token, self._caller)
        except ATPError as exc:
            raise self._wrap(exc) from exc
        return ExecuteResponse(
            trace_id=result.trace_id,
            envelope_id=result.envelope_id,
            status=result.status,
            reason_code=result.reason_code,
            message=result.message,
            result=result.result,
        )

    def report_outcome(
        self, grant_id: str, *, succeeded: bool, summary: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            event = self._tp.report_outcome(
                grant_id, self._caller, succeeded=succeeded, summary=summary
            )
        except ATPError as exc:
            raise self._wrap(exc) from exc
        body: dict[str, Any] = event.model_dump(mode="json")
        return body

    def report_shadow_outcome(
        self, trace_id: str, *, succeeded: bool, summary: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            event = self._tp.report_shadow_outcome(
                trace_id, self._caller, succeeded=succeeded, summary=summary
            )
        except ATPError as exc:
            raise self._wrap(exc) from exc
        body: dict[str, Any] = event.model_dump(mode="json")
        return body

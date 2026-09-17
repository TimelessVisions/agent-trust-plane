from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from atp_core import ATPError, DelegationError, GrantError, ReasonCode
from atp_gateway.api import router
from atp_gateway.settings import GatewaySettings
from atp_gateway.wiring import Runtime, build_runtime
from atp_identity import AuthError

_NOT_FOUND = {
    ReasonCode.TRACE_NOT_FOUND,
    ReasonCode.DELEGATION_NOT_FOUND,
    ReasonCode.POLICY_SET_NOT_FOUND,
}


_UNAUTHENTICATED = {
    ReasonCode.AGENT_CREDENTIAL_MISSING,
    ReasonCode.AGENT_CREDENTIAL_INVALID,
    ReasonCode.AGENT_CREDENTIAL_REVOKED,
    ReasonCode.AGENT_CREDENTIAL_EXPIRED,
}
_FORBIDDEN = {
    ReasonCode.AGENT_IDENTITY_MISMATCH,
    ReasonCode.OPERATOR_KEY_REQUIRED,
    ReasonCode.POLICY_SET_OVERRIDE_FORBIDDEN,
}


def status_for(exc: ATPError) -> int:
    if exc.reason_code in _UNAUTHENTICATED:
        return 401
    if exc.reason_code in _FORBIDDEN or isinstance(exc, AuthError):
        return 403
    if exc.reason_code in _NOT_FOUND:
        return 404
    if isinstance(exc, DelegationError):
        return 422
    if isinstance(exc, GrantError):
        return 403
    return 409


def create_app(settings: GatewaySettings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or GatewaySettings()
    # Built eagerly (not in lifespan) so in-process ASGI clients that skip the
    # lifespan protocol still get a working gateway.
    owns_runtime = runtime is None
    rt = runtime or build_runtime(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.getLogger("atp.gateway").info(
            "gateway ready: policy_set=%s ttl=%ss db=%s",
            rt.trust_plane.policy_sets.default_version,
            rt.trust_plane.grant_ttl_seconds,
            settings.database_path,
        )
        try:
            yield
        finally:
            if owns_runtime:
                rt.close()

    app = FastAPI(
        title="Agent Trust Plane Gateway",
        version="0.3.2",
        description=(
            "Models propose actions. Independent infrastructure decides whether they execute."
        ),
        lifespan=lifespan,
    )
    app.state.runtime = rt
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ATPError)
    async def _atp_error(_: Request, exc: ATPError) -> JSONResponse:
        status = status_for(exc)
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return JSONResponse(
            status_code=status,
            content={"reason_code": exc.reason_code.value, "message": exc.message},
            headers=headers,
        )

    app.include_router(router)
    return app

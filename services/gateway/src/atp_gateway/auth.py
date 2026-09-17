"""Authentication dependencies for the HTTP layer.

Two distinct credential kinds, never interchangeable:

* **Agent credential** — ``Authorization: Bearer atpa_<id>.<secret>``. Proves
  which agent is calling. Required on every agent-facing route.
* **Operator key** — ``X-ATP-Operator-Key``. Proves the caller is the deployment
  operator, who in the MVP is also the trust anchor for human authority.
  Required for credential lifecycle, human-rooted delegations, policy-set
  override, and running evals.

Neither value is ever logged, traced, or echoed in a response.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, Request

from atp_core import ATPError, ReasonCode
from atp_gateway.wiring import Runtime
from atp_identity import AuthenticatedAgent, AuthError


def _runtime(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError(ReasonCode.AGENT_CREDENTIAL_INVALID, "expected 'Authorization: Bearer'")
    return token.strip()


def current_agent(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedAgent:
    rt = _runtime(request)
    return rt.trust_plane.credentials.authenticate(
        _bearer(authorization), now=rt.trust_plane.clock()
    )


def optional_agent(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedAgent | None:
    if not authorization:
        return None
    return current_agent(request, authorization)


def is_operator(request: Request, presented: str | None) -> bool:
    expected = _runtime(request).operator_key
    return presented is not None and hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    )


def require_operator(
    request: Request,
    x_atp_operator_key: Annotated[str | None, Header()] = None,
) -> None:
    if not is_operator(request, x_atp_operator_key):
        raise ATPError(
            ReasonCode.OPERATOR_KEY_REQUIRED,
            "this action requires the operator key (X-ATP-Operator-Key)",
        )


def operator_presented(
    request: Request,
    x_atp_operator_key: Annotated[str | None, Header()] = None,
) -> bool:
    return is_operator(request, x_atp_operator_key)


Agent = Annotated[AuthenticatedAgent, Depends(current_agent)]
MaybeAgent = Annotated[AuthenticatedAgent | None, Depends(optional_agent)]
Operator = Annotated[None, Depends(require_operator)]
IsOperator = Annotated[bool, Depends(operator_presented)]

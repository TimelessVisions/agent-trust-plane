"""The identity-provider boundary.

The gateway authenticates the caller of every agent-facing route through
one ``IdentityProvider``. The provider answers exactly one question from
the request's credentials: *which agent is this, and under which credential
id?* Everything after that (binding the envelope's ``agent`` to the answer,
re-checking liveness under the lock, auditing) is the kernel's job and does
not depend on the provider.

Today's implementation is the bearer-credential store in this package. A
workload-identity provider (SPIFFE SVID over mTLS, OIDC client credentials,
DPoP-bound tokens) implements the same protocol; see
docs/security/identity-providers.md. The envelope is never consulted for
identity: a provider that returned what the caller *claims* would defeat
the binding, so ``AuthenticatedAgent`` must come from a verified credential.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from atp_core import ReasonCode
from atp_identity.credentials import AuthenticatedAgent, AuthError, CredentialService


class IdentityProvider(Protocol):
    """Authenticate one HTTP request's credentials."""

    name: str

    def authenticate(self, headers: Mapping[str, str], *, now: datetime) -> AuthenticatedAgent:
        """Return the verified agent or raise ``AuthError`` with one of the
        ``AGENT_CREDENTIAL_*`` reason codes. Never trust request bodies."""
        ...

    def is_live(self, credential_id: str, *, now: datetime) -> bool:
        """Re-check that the credential behind an earlier authentication is
        still valid (revocation, expiry). Called under the service lock."""
        ...


class BearerCredentialProvider:
    """``Authorization: Bearer atpa_<credential_id>.<secret>`` against the
    credential store (SHA-256 at rest, constant-time comparison)."""

    name = "bearer-credential"

    def __init__(self, credentials: CredentialService) -> None:
        self.credentials = credentials

    @staticmethod
    def _token(headers: Mapping[str, str]) -> str | None:
        authorization = next((v for k, v in headers.items() if k.lower() == "authorization"), None)
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthError(ReasonCode.AGENT_CREDENTIAL_INVALID, "expected 'Authorization: Bearer'")
        return token.strip()

    def authenticate(self, headers: Mapping[str, str], *, now: datetime) -> AuthenticatedAgent:
        return self.credentials.authenticate(self._token(headers), now=now)

    def is_live(self, credential_id: str, *, now: datetime) -> bool:
        cred = self.credentials.store.get(credential_id)
        return cred is not None and not cred.is_revoked() and not cred.is_expired(now)

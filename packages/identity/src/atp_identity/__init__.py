"""Agent identity and delegated authority."""

from atp_identity.budgets import (
    BudgetLine,
    BudgetUsage,
    InMemoryReservationStore,
    ReservationResult,
    ReservationStore,
    SqliteReservationStore,
    budget_key,
    budget_lines,
)
from atp_identity.credentials import (
    AgentCredential,
    AuthenticatedAgent,
    AuthError,
    CredentialService,
    CredentialStore,
    InMemoryCredentialStore,
    SqliteCredentialStore,
)
from atp_identity.grants import DelegationGrant, DelegationRequest
from atp_identity.keys import kid_for
from atp_identity.principal_keys import (
    EphemeralPrincipalKeys,
    FilePrincipalKeys,
    InMemoryPrincipalKeys,
    PrincipalKeys,
    root_signing_bytes,
    sign_root,
    sign_root_request,
    verify_root,
)
from atp_identity.provider import BearerCredentialProvider, IdentityProvider
from atp_identity.scope import covers, matches, scope_covers, scope_matches
from atp_identity.service import MAX_CHAIN_DEPTH, DelegationService, ResolvedChain
from atp_identity.store import DelegationStore, InMemoryDelegationStore, SqliteDelegationStore

__all__ = [
    "MAX_CHAIN_DEPTH",
    "AgentCredential",
    "AuthError",
    "AuthenticatedAgent",
    "BearerCredentialProvider",
    "BudgetLine",
    "BudgetUsage",
    "CredentialService",
    "CredentialStore",
    "DelegationGrant",
    "DelegationRequest",
    "DelegationService",
    "DelegationStore",
    "EphemeralPrincipalKeys",
    "FilePrincipalKeys",
    "IdentityProvider",
    "InMemoryCredentialStore",
    "InMemoryDelegationStore",
    "InMemoryPrincipalKeys",
    "InMemoryReservationStore",
    "PrincipalKeys",
    "ReservationResult",
    "ReservationStore",
    "ResolvedChain",
    "SqliteCredentialStore",
    "SqliteDelegationStore",
    "SqliteReservationStore",
    "budget_key",
    "budget_lines",
    "covers",
    "kid_for",
    "matches",
    "root_signing_bytes",
    "scope_covers",
    "scope_matches",
    "sign_root",
    "sign_root_request",
    "verify_root",
]

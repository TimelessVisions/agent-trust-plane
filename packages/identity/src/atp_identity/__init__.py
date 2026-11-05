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
    "IdentityProvider",
    "InMemoryCredentialStore",
    "InMemoryDelegationStore",
    "InMemoryReservationStore",
    "ReservationResult",
    "ReservationStore",
    "ResolvedChain",
    "SqliteCredentialStore",
    "SqliteDelegationStore",
    "SqliteReservationStore",
    "budget_key",
    "budget_lines",
    "covers",
    "matches",
    "scope_covers",
    "scope_matches",
]

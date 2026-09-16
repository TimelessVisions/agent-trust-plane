"""Agent identity and delegated authority."""

from atp_identity.grants import DelegationGrant, DelegationRequest
from atp_identity.scope import covers, matches, scope_covers, scope_matches
from atp_identity.service import MAX_CHAIN_DEPTH, DelegationService, ResolvedChain
from atp_identity.store import DelegationStore, InMemoryDelegationStore, SqliteDelegationStore

__all__ = [
    "MAX_CHAIN_DEPTH",
    "DelegationGrant",
    "DelegationRequest",
    "DelegationService",
    "DelegationStore",
    "InMemoryDelegationStore",
    "ResolvedChain",
    "SqliteDelegationStore",
    "covers",
    "matches",
    "scope_covers",
    "scope_matches",
]

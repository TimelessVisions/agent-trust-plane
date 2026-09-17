"""Shared domain contracts for Agent Trust Plane.

Everything here is a plain, strongly validated data model. No I/O, no policy
logic. Other packages import from here so that identity, policy, and audit do
not depend on one another.
"""

from atp_core.authority import AuthorityConstraints, EffectiveAuthority
from atp_core.canonical import canonical_hash, canonical_json, sha256_hex
from atp_core.decision import (
    ApprovalRequirement,
    ConstraintEvaluation,
    Decision,
    DecisionOutcome,
    EnforcementMode,
    PolicyEvaluation,
    PolicyRef,
)
from atp_core.envelope import ActionEnvelope, ContentSource, ContentTrust, Provenance
from atp_core.errors import ATPError, DelegationError, EnvelopeError, GrantError, ToolError
from atp_core.ids import new_id, new_trace_id
from atp_core.money import Money
from atp_core.principals import PrincipalKind, PrincipalRef
from atp_core.reasons import ReasonCode
from atp_core.resources import RESOURCE_PATTERN, SCOPE_PATTERN
from atp_core.timeutil import ensure_aware, in_seconds, utcnow

__all__ = [
    "RESOURCE_PATTERN",
    "SCOPE_PATTERN",
    "ATPError",
    "ActionEnvelope",
    "ApprovalRequirement",
    "AuthorityConstraints",
    "ConstraintEvaluation",
    "ContentSource",
    "ContentTrust",
    "Decision",
    "DecisionOutcome",
    "DelegationError",
    "EffectiveAuthority",
    "EnforcementMode",
    "EnvelopeError",
    "GrantError",
    "Money",
    "PolicyEvaluation",
    "PolicyRef",
    "PrincipalKind",
    "PrincipalRef",
    "Provenance",
    "ReasonCode",
    "ToolError",
    "canonical_hash",
    "canonical_json",
    "ensure_aware",
    "in_seconds",
    "new_id",
    "new_trace_id",
    "sha256_hex",
    "utcnow",
]

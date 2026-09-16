"""Authority shapes shared by identity (which computes them) and policy (which
checks against them)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from atp_core.money import Money
from atp_core.principals import PrincipalRef


class AuthorityConstraints(BaseModel):
    """Quantitative limits attached to a grant.

    ``None`` means "no limit of this kind was expressed". When a chain is
    resolved, limits are intersected: the tightest wins, and a limit expressed
    anywhere in the chain applies to everything below it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_amount: Money | None = Field(
        default=None,
        description="Maximum single-action monetary value this authority permits.",
    )
    currencies: frozenset[str] | None = Field(
        default=None,
        description="Currencies this authority may transact in. None = inherit.",
    )


class EffectiveAuthority(BaseModel):
    """The authority an agent actually holds after intersecting every grant on
    its delegation chain. This is what policies evaluate against; the agent's
    own claims about its authority are never consulted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root_principal: PrincipalRef = Field(description="The human at the top of the chain.")
    holder: PrincipalRef = Field(description="The principal exercising this authority.")
    grant_chain: tuple[str, ...] = Field(
        description="Grant ids from root to leaf, in order of delegation."
    )
    capabilities: frozenset[str]
    resource_scope: tuple[str, ...] = Field(
        description="Resource patterns the holder may act on (leaf grant, already "
        "checked to be covered by every ancestor)."
    )
    constraints: AuthorityConstraints
    expires_at: datetime = Field(description="Earliest expiry across the chain.")

    @property
    def depth(self) -> int:
        return len(self.grant_chain)

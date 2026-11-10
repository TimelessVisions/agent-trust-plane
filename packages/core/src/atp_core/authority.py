"""Authority shapes shared by identity (which computes them) and policy (which
checks against them)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from atp_core.money import Money
from atp_core.principals import PrincipalRef

BudgetPeriod = Literal["day", "week", "month"]


class Budget(BaseModel):
    """Cumulative spend allowed per calendar period, in one currency.

    Periods are anchored to UTC calendar boundaries: a ``day`` starts at
    00:00 UTC, a ``week`` at 00:00 UTC on Monday (ISO 8601), a ``month`` at
    00:00 UTC on its first day. Spend counts in the period in which it was
    authorized.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: Money = Field(description="Total allowed per period, in the budget's currency.")
    period: BudgetPeriod

    def period_start(self, at: datetime) -> datetime:
        t = at.astimezone(UTC)
        day = datetime(t.year, t.month, t.day, tzinfo=UTC)
        if self.period == "day":
            return day
        if self.period == "week":
            return day - timedelta(days=t.weekday())  # Monday is weekday() == 0
        return datetime(t.year, t.month, 1, tzinfo=UTC)

    def period_end(self, at: datetime) -> datetime:
        start = self.period_start(at)
        if self.period == "day":
            return start + timedelta(days=1)
        if self.period == "week":
            return start + timedelta(days=7)
        if start.month == 12:
            return datetime(start.year + 1, 1, 1, tzinfo=UTC)
        return datetime(start.year, start.month + 1, 1, tzinfo=UTC)


class ChainBudget(BaseModel):
    """A budget as it sits on one grant of a resolved chain. Spend is counted
    per (root principal, grantee of that grant), so every action below the
    grant counts against it, across sessions and sibling grants."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    grant_id: str
    grantee: PrincipalRef
    budget: Budget


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
    budget: Budget | None = Field(
        default=None,
        description="Cumulative spend per UTC calendar period for everything done under "
        "this grant. Every budget on a chain applies; the tightest binds.",
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
    budgets: tuple[ChainBudget, ...] = Field(
        default=(),
        description="Every budget on the chain, root first. Each applies independently.",
    )

    @property
    def depth(self) -> int:
        return len(self.grant_chain)

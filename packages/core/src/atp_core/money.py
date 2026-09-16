from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

_TWO_PLACES = Decimal("0.01")


class Money(BaseModel):
    """An amount in a single ISO-4217 currency, carried with exactly 2 decimal places.

    Amounts are Decimals internally and strings on the wire so no float ever
    touches a monetary comparison.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: Decimal = Field(description="Non-negative amount in major units, e.g. 12500.00")
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, value: Any) -> Decimal:
        if isinstance(value, float):
            # Floats arrive from JSON; normalise through str() so 12500.0 becomes
            # exactly 12500.00 rather than a binary approximation.
            value = str(value)
        try:
            dec = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"invalid monetary amount: {value!r}") from exc
        if dec.is_nan() or dec.is_infinite():
            raise ValueError("monetary amount must be finite")
        if dec < 0:
            raise ValueError("monetary amount must be non-negative")
        # Reject, never round: "1000.004" must not become 1000.00 and slip under a limit.
        if dec != dec.quantize(_TWO_PLACES):
            raise ValueError("monetary amount must have at most 2 decimal places")
        return dec.quantize(_TWO_PLACES)

    @field_serializer("amount")
    def _serialise_amount(self, value: Decimal) -> str:
        return format(value, "f")

    def __str__(self) -> str:
        return f"{self.currency} {self.amount:,.2f}"

    def exceeds(self, other: Money) -> bool:
        self._same_currency(other)
        return self.amount > other.amount

    def min(self, other: Money) -> Money:
        self._same_currency(other)
        return self if self.amount <= other.amount else other

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

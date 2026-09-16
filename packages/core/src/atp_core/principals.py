from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PrincipalKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SERVICE = "service"


class PrincipalRef(BaseModel):
    """A reference to an identity that can hold or exercise authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    kind: PrincipalKind

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.id}"

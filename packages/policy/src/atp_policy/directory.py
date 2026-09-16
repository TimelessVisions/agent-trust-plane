"""Approved-vendor directory: the trusted source of truth for where money may go.

The destination policy compares what the agent asked for against this, which
is exactly the check an injected instruction ("send it to this other account
instead") is trying to bypass.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class Vendor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    vendor_id: str = Field(description="Bare id; the resource string is 'vendor:<vendor_id>'.")
    name: str
    account_ref: str = Field(description="Bank account reference on file, e.g. 'acct-nw-4471'.")
    approved: bool = True

    @property
    def resource(self) -> str:
        return f"vendor:{self.vendor_id}"


class VendorDirectory(Protocol):
    def lookup(self, vendor_id: str) -> Vendor | None: ...

    def all(self) -> list[Vendor]: ...


class InMemoryVendorDirectory:
    def __init__(self, vendors: list[Vendor] | None = None) -> None:
        self._vendors: dict[str, Vendor] = {v.vendor_id: v for v in (vendors or [])}

    def add(self, vendor: Vendor) -> None:
        self._vendors[vendor.vendor_id] = vendor

    def lookup(self, vendor_id: str) -> Vendor | None:
        return self._vendors.get(vendor_id)

    def all(self) -> list[Vendor]:
        return list(self._vendors.values())

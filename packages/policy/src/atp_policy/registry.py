"""Built-in, versioned policy sets.

Two versions ship so the replay story is real:

* ``payments-v1`` is the baseline: it enforces delegation, capability, scope
  and monetary limits, but says nothing about *where* the money goes.
* ``payments-v2`` adds the approved-destination and currency policies.

A payment that stays under the limit but redirects funds to an attacker's
account is ALLOWED under v1 and DENIED under v2. Replaying a v1 trace against
v2 is how you prove the fix.
"""

from __future__ import annotations

from decimal import Decimal

from atp_core import Money, ReasonCode
from atp_core.errors import ATPError
from atp_policy.base import PolicySet
from atp_policy.policies import (
    CapabilityRequiredPolicy,
    DelegationValidPolicy,
    PaymentApprovalThresholdPolicy,
    PaymentArgumentsPolicy,
    PaymentCurrencyPolicy,
    PaymentDestinationPolicy,
    PaymentMaxAmountPolicy,
    ResourceScopePolicy,
)

DEFAULT_APPROVAL_THRESHOLD = Money(amount=Decimal("750"), currency="USD")


def payments_v1(threshold: Money = DEFAULT_APPROVAL_THRESHOLD) -> PolicySet:
    return PolicySet(
        version="payments-v1",
        description="Baseline: delegation, capability, scope, monetary limit, approval threshold.",
        policies=(
            DelegationValidPolicy(),
            CapabilityRequiredPolicy(),
            ResourceScopePolicy(),
            PaymentArgumentsPolicy(),
            PaymentMaxAmountPolicy(),
            PaymentApprovalThresholdPolicy(threshold),
        ),
    )


def payments_v2(threshold: Money = DEFAULT_APPROVAL_THRESHOLD) -> PolicySet:
    return PolicySet(
        version="payments-v2",
        description="Hardened: v1 plus approved-destination and currency allowlist checks.",
        policies=(
            DelegationValidPolicy(),
            CapabilityRequiredPolicy(),
            ResourceScopePolicy(),
            PaymentArgumentsPolicy(),
            PaymentMaxAmountPolicy(),
            PaymentCurrencyPolicy(),
            PaymentDestinationPolicy(),
            PaymentApprovalThresholdPolicy(threshold),
        ),
    )


class PolicySetNotFoundError(ATPError):
    pass


class PolicySetRegistry:
    def __init__(self, sets: list[PolicySet], default_version: str) -> None:
        self._sets = {s.version: s for s in sets}
        if default_version not in self._sets:
            raise ValueError(f"default policy set {default_version!r} not registered")
        self._default = default_version

    @classmethod
    def builtin(cls) -> PolicySetRegistry:
        return cls([payments_v1(), payments_v2()], default_version="payments-v2")

    @property
    def default_version(self) -> str:
        return self._default

    def get(self, version: str | None = None) -> PolicySet:
        key = version or self._default
        try:
            return self._sets[key]
        except KeyError:
            raise PolicySetNotFoundError(
                ReasonCode.POLICY_SET_NOT_FOUND,
                f"policy set {key!r} is not registered; known: {sorted(self._sets)}",
            ) from None

    def versions(self) -> list[PolicySet]:
        return list(self._sets.values())

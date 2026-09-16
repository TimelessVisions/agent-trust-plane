"""Policies for the ``payments.send_payment`` action."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from atp_core import ConstraintEvaluation, Money, PolicyEvaluation, ReasonCode
from atp_policy.base import Policy, PolicyContext

PAYMENT_TOOL = "payments"
PAYMENT_ACTION = "send_payment"


class PaymentArguments(BaseModel):
    """The validated shape of ``envelope.arguments`` for a vendor payment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    destination_account: str | None = Field(
        default=None,
        max_length=128,
        description="If omitted, the vendor's account on file is used.",
    )
    memo: str | None = Field(default=None, max_length=500)

    @property
    def money(self) -> Money:
        return Money(amount=self.amount, currency=self.currency)


def is_payment(ctx: PolicyContext) -> bool:
    return ctx.envelope.tool == PAYMENT_TOOL and ctx.envelope.action == PAYMENT_ACTION


def parse_payment(ctx: PolicyContext) -> PaymentArguments | None:
    try:
        args = PaymentArguments.model_validate(ctx.envelope.arguments)
    except ValidationError:
        return None
    try:
        Money(amount=args.amount, currency=args.currency)  # non-negative, finite
    except ValidationError:
        return None
    return args


def _invalid(policy: Policy) -> PolicyEvaluation:
    return policy.deny(
        ReasonCode.PAYMENT_ARGUMENTS_INVALID,
        "payment arguments must be {amount, currency[, destination_account, memo]} "
        "with a non-negative amount",
    )


class PaymentArgumentsPolicy(Policy):
    id = "payments.arguments"
    version = "v1"
    description = "Payment arguments must be well-formed before any other check runs."

    def applies_to(self, ctx: PolicyContext) -> bool:
        return is_payment(ctx)

    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation:
        args = parse_payment(ctx)
        if args is None:
            return _invalid(self)
        return self.allow(f"payment of {args.money} is well-formed")


class PaymentMaxAmountPolicy(Policy):
    id = "payments.vendor.max_amount"
    version = "v1"
    description = "A vendor payment may not exceed the delegated monetary limit."

    def applies_to(self, ctx: PolicyContext) -> bool:
        return is_payment(ctx) and ctx.authority is not None

    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation:
        assert ctx.authority is not None
        args = parse_payment(ctx)
        if args is None:
            return _invalid(self)
        limit = ctx.authority.constraints.max_amount
        requested = args.money
        if limit is None:
            return self.deny(
                ReasonCode.PAYMENT_EXCEEDS_DELEGATED_AUTHORITY,
                "no monetary limit is expressed anywhere in the delegation chain; "
                "payments require an explicit limit",
                (
                    ConstraintEvaluation(
                        name="max_amount", requested=str(requested), limit=None, satisfied=False
                    ),
                ),
            )
        if limit.currency != requested.currency:
            return self.deny(
                ReasonCode.PAYMENT_CURRENCY_NOT_PERMITTED,
                f"delegated limit is in {limit.currency}; payment is in {requested.currency}",
                (
                    ConstraintEvaluation(
                        name="max_amount",
                        requested=str(requested),
                        limit=str(limit),
                        satisfied=False,
                    ),
                ),
            )
        ok = not requested.exceeds(limit)
        constraint = ConstraintEvaluation(
            name="max_amount",
            requested=format(requested.amount, "f"),
            limit=format(limit.amount, "f"),
            satisfied=ok,
            detail=requested.currency,
        )
        if not ok:
            return self.deny(
                ReasonCode.PAYMENT_EXCEEDS_DELEGATED_AUTHORITY,
                f"requested {requested} exceeds delegated maximum {limit}",
                (constraint,),
            )
        return self.allow(
            f"requested {requested} is within delegated maximum {limit}", (constraint,)
        )


class PaymentCurrencyPolicy(Policy):
    id = "payments.currency"
    version = "v1"
    description = "Payment currency must be in the delegated currency allowlist."

    def applies_to(self, ctx: PolicyContext) -> bool:
        return is_payment(ctx) and ctx.authority is not None

    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation:
        assert ctx.authority is not None
        args = parse_payment(ctx)
        if args is None:
            return _invalid(self)
        allowed = ctx.authority.constraints.currencies
        if allowed is None:
            return self.allow("no currency allowlist expressed; inherits limit currency")
        ok = args.currency in allowed
        constraint = ConstraintEvaluation(
            name="currency", requested=args.currency, limit=sorted(allowed), satisfied=ok
        )
        if not ok:
            return self.deny(
                ReasonCode.PAYMENT_CURRENCY_NOT_PERMITTED,
                f"currency {args.currency} not in allowlist {sorted(allowed)}",
                (constraint,),
            )
        return self.allow(f"currency {args.currency} permitted", (constraint,))


class PaymentDestinationPolicy(Policy):
    id = "payments.vendor.approved_destination"
    version = "v1"
    description = (
        "Money may only go to an approved vendor, and only to the account the "
        "directory has on file for that vendor."
    )

    def applies_to(self, ctx: PolicyContext) -> bool:
        return is_payment(ctx)

    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation:
        args = parse_payment(ctx)
        if args is None:
            return _invalid(self)
        resource = ctx.envelope.resource
        if not resource.startswith("vendor:"):
            return self.deny(
                ReasonCode.PAYMENT_DESTINATION_NOT_APPROVED,
                f"payments must target a 'vendor:<id>' resource, got '{resource}'",
            )
        vendor_id = resource.split(":", 1)[1]
        vendor = ctx.vendors.lookup(vendor_id)
        if vendor is None or not vendor.approved:
            return self.deny(
                ReasonCode.PAYMENT_DESTINATION_NOT_APPROVED,
                f"vendor '{vendor_id}' is not an approved vendor",
                (
                    ConstraintEvaluation(
                        name="approved_vendor", requested=vendor_id, limit=None, satisfied=False
                    ),
                ),
            )
        if args.destination_account is not None and args.destination_account != vendor.account_ref:
            return self.deny(
                ReasonCode.PAYMENT_DESTINATION_RESOURCE_MISMATCH,
                f"destination account '{args.destination_account}' does not match the account "
                f"on file for {vendor.name} ('{vendor.account_ref}')",
                (
                    ConstraintEvaluation(
                        name="destination_account",
                        requested=args.destination_account,
                        limit=vendor.account_ref,
                        satisfied=False,
                    ),
                ),
            )
        return self.allow(
            f"destination is approved vendor {vendor.name} ({vendor.account_ref})",
            (
                ConstraintEvaluation(
                    name="destination_account",
                    requested=args.destination_account or vendor.account_ref,
                    limit=vendor.account_ref,
                    satisfied=True,
                ),
            ),
        )


class PaymentApprovalThresholdPolicy(Policy):
    id = "payments.approval_threshold"
    version = "v1"
    description = "Payments above a threshold, even when within authority, need a human approver."

    def __init__(self, threshold: Money, approver_role: str = "finance-manager") -> None:
        self.threshold = threshold
        self.approver_role = approver_role

    def applies_to(self, ctx: PolicyContext) -> bool:
        return is_payment(ctx) and ctx.authority is not None

    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation:
        args = parse_payment(ctx)
        if args is None:
            return _invalid(self)
        requested = args.money
        if requested.currency != self.threshold.currency:
            return self.allow("threshold not expressed in this currency; not applied")
        over = requested.exceeds(self.threshold)
        constraint = ConstraintEvaluation(
            name="approval_threshold",
            requested=format(requested.amount, "f"),
            limit=format(self.threshold.amount, "f"),
            satisfied=not over,
            detail=requested.currency,
        )
        if over:
            return self.require_approval(
                ReasonCode.APPROVAL_REQUIRED_AMOUNT_THRESHOLD,
                f"{requested} exceeds the {self.threshold} auto-approval threshold; "
                f"requires {self.approver_role} approval",
                (constraint,),
            )
        return self.allow(f"{requested} is under the auto-approval threshold", (constraint,))

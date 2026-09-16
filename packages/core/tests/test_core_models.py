from decimal import Decimal

import pytest
from pydantic import ValidationError

from atp_core import (
    ActionEnvelope,
    ContentSource,
    ContentTrust,
    Money,
    PrincipalKind,
    PrincipalRef,
    Provenance,
    canonical_hash,
    canonical_json,
    sha256_hex,
)


def _envelope(**overrides: object) -> ActionEnvelope:
    base: dict[str, object] = {
        "principal": PrincipalRef(id="company-user-42", kind=PrincipalKind.HUMAN),
        "agent": PrincipalRef(id="accounts-payable-agent", kind=PrincipalKind.AGENT),
        "delegation_grant_id": "grt_abc",
        "capability": "pay:vendor",
        "tool": "payments",
        "action": "send_payment",
        "resource": "vendor:128",
        "arguments": {"amount": "480.00", "currency": "USD"},
    }
    base.update(overrides)
    return ActionEnvelope(**base)  # type: ignore[arg-type]


class TestMoney:
    def test_quantises_to_two_places(self) -> None:
        assert Money(amount=Decimal("1"), currency="USD").amount == Decimal("1.00")

    def test_float_is_normalised_not_approximated(self) -> None:
        assert Money(amount=12500.0, currency="USD").amount == Decimal("12500.00")

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=-1, currency="USD")

    def test_rejects_bad_currency(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=1, currency="usd")

    def test_exceeds_and_min(self) -> None:
        a = Money(amount=12500, currency="USD")
        b = Money(amount=1000, currency="USD")
        assert a.exceeds(b)
        assert not b.exceeds(a)
        assert a.min(b) == b

    def test_cross_currency_comparison_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            Money(amount=1, currency="USD").exceeds(Money(amount=1, currency="EUR"))

    def test_serialises_as_string(self) -> None:
        assert Money(amount=1000, currency="USD").model_dump(mode="json") == {
            "amount": "1000.00",
            "currency": "USD",
        }


class TestCanonical:
    def test_key_order_does_not_change_hash(self) -> None:
        assert canonical_hash({"b": 1, "a": 2}) == canonical_hash({"a": 2, "b": 1})

    def test_decimal_and_enum_rendering(self) -> None:
        out = canonical_json({"m": Decimal("1.50"), "k": PrincipalKind.HUMAN})
        assert out == b'{"k":"human","m":"1.50"}'

    def test_sha256_hex(self) -> None:
        assert sha256_hex(b"") == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )


class TestActionEnvelope:
    def test_defaults_generate_ids(self) -> None:
        env = _envelope()
        assert env.envelope_id.startswith("env_")
        assert len(env.trace_id) == 12

    def test_extra_fields_are_rejected(self) -> None:
        """An agent cannot smuggle an ``authorized`` flag into the envelope."""
        with pytest.raises(ValidationError) as exc:
            _envelope(authorized=True)
        assert "authorized" in str(exc.value)

    def test_action_hash_changes_when_arguments_change(self) -> None:
        env = _envelope()
        modified = env.model_copy(update={"arguments": {"amount": "12500.00", "currency": "USD"}})
        assert env.action_hash != modified.action_hash

    def test_action_hash_ignores_provenance(self) -> None:
        env = _envelope()
        src = ContentSource(
            source_id="inv-1",
            kind="invoice_pdf",
            origin="mail://ap@example.com",
            trust=ContentTrust.UNTRUSTED,
            content_hash="a" * 64,
        )
        with_prov = env.model_copy(update={"provenance": Provenance(content_sources=(src,))})
        assert env.action_hash == with_prov.action_hash

    def test_action_hash_is_deterministic_across_instances(self) -> None:
        env = _envelope()
        again = ActionEnvelope.model_validate(env.model_dump(mode="json"))
        assert env.action_hash == again.action_hash

    def test_identifier_patterns_enforced(self) -> None:
        with pytest.raises(ValidationError):
            _envelope(resource="vendor 128; DROP TABLE")

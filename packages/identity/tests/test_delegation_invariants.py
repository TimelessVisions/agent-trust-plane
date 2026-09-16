"""Invariants of delegated authority.

Every test here is a claim from the design: a child can never receive more
authority than its parent, delegation expires, escalation is denied, and
ancestry is auditable.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from atp_core import AuthorityConstraints, DelegationError, PrincipalKind, PrincipalRef, ReasonCode
from atp_identity import DelegationGrant, DelegationRequest, DelegationService

from identity_fixtures import AP_AGENT, DOC_AGENT, HUMAN, NOW, ORCHESTRATOR, usd


def _request(**overrides: object) -> DelegationRequest:
    base: dict[str, object] = {
        "label": "test",
        "grantor": ORCHESTRATOR,
        "grantee": AP_AGENT,
        "capabilities": frozenset({"pay:vendor"}),
        "resource_scope": ("vendor:*",),
        "constraints": AuthorityConstraints(max_amount=usd(500)),
        "expires_at": NOW + timedelta(hours=1),
    }
    base.update(overrides)
    return DelegationRequest(**base)  # type: ignore[arg-type]


class TestRootGrants:
    def test_root_must_be_human(self, service: DelegationService) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(_request(grantor=ORCHESTRATOR, grantee=ORCHESTRATOR), now=NOW)
        assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_NOT_HUMAN

    def test_root_must_be_self_issued(self, service: DelegationService) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(_request(grantor=HUMAN, grantee=ORCHESTRATOR), now=NOW)
        assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_NOT_HUMAN

    def test_cannot_issue_already_expired(self, service: DelegationService) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(grantor=HUMAN, grantee=HUMAN, expires_at=NOW - timedelta(seconds=1)),
                now=NOW,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_EXPIRED


class TestChildCannotExceedParent:
    def test_capability_escalation_denied(
        self, service: DelegationService, orchestrator_grant: DelegationGrant
    ) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(
                    parent_grant_id=orchestrator_grant.grant_id,
                    capabilities=frozenset({"pay:vendor", "admin:vendors"}),
                ),
                now=NOW,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_EXCEEDS_PARENT_CAPABILITIES

    def test_monetary_escalation_denied(
        self, service: DelegationService, orchestrator_grant: DelegationGrant
    ) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(
                    parent_grant_id=orchestrator_grant.grant_id,
                    constraints=AuthorityConstraints(max_amount=usd(50_000)),
                ),
                now=NOW,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_EXCEEDS_PARENT_AMOUNT

    def test_child_must_state_limit_when_parent_has_one(
        self, service: DelegationService, orchestrator_grant: DelegationGrant
    ) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(
                    parent_grant_id=orchestrator_grant.grant_id,
                    constraints=AuthorityConstraints(),
                ),
                now=NOW,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_EXCEEDS_PARENT_AMOUNT

    def test_equal_limit_is_permitted(
        self, service: DelegationService, orchestrator_grant: DelegationGrant
    ) -> None:
        grant = service.issue(
            _request(
                parent_grant_id=orchestrator_grant.grant_id,
                constraints=AuthorityConstraints(max_amount=usd(10_000)),
            ),
            now=NOW,
        )
        assert grant.constraints.max_amount == usd(10_000)

    def test_resource_scope_escalation_denied(
        self, service: DelegationService, ap_grant: DelegationGrant
    ) -> None:
        """AP agent has vendor:* and invoice:*; a child asking for '*' is wider."""
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(
                    grantor=AP_AGENT,
                    grantee=DOC_AGENT,
                    parent_grant_id=ap_grant.grant_id,
                    capabilities=frozenset({"read:invoice"}),
                    resource_scope=("*",),
                    constraints=AuthorityConstraints(max_amount=usd(0)),
                ),
                now=NOW,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_EXCEEDS_PARENT_RESOURCE_SCOPE

    def test_resource_type_escalation_denied(
        self, service: DelegationService, ap_grant: DelegationGrant
    ) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(
                    grantor=AP_AGENT,
                    grantee=DOC_AGENT,
                    parent_grant_id=ap_grant.grant_id,
                    capabilities=frozenset({"read:invoice"}),
                    resource_scope=("payroll:*",),
                    constraints=AuthorityConstraints(max_amount=usd(0)),
                ),
                now=NOW,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_EXCEEDS_PARENT_RESOURCE_SCOPE

    def test_expiry_escalation_denied(
        self, service: DelegationService, ap_grant: DelegationGrant
    ) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(
                    grantor=AP_AGENT,
                    grantee=DOC_AGENT,
                    parent_grant_id=ap_grant.grant_id,
                    capabilities=frozenset({"read:invoice"}),
                    resource_scope=("invoice:*",),
                    constraints=AuthorityConstraints(max_amount=usd(0)),
                    expires_at=NOW + timedelta(days=365),
                ),
                now=NOW,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_EXCEEDS_PARENT_EXPIRY

    def test_currency_escalation_denied(
        self, service: DelegationService, orchestrator_grant: DelegationGrant
    ) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(
                    parent_grant_id=orchestrator_grant.grant_id,
                    constraints=AuthorityConstraints(
                        max_amount=usd(100), currencies=frozenset({"USD", "EUR"})
                    ),
                ),
                now=NOW,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_EXCEEDS_PARENT_CURRENCIES

    def test_escalation_checked_against_whole_chain_not_just_parent(
        self, service: DelegationService, ap_grant: DelegationGrant
    ) -> None:
        """The orchestrator holds admin:vendors nowhere in its chain, so a
        grandchild cannot obtain it even if the direct parent were lax."""
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(
                    grantor=AP_AGENT,
                    grantee=DOC_AGENT,
                    parent_grant_id=ap_grant.grant_id,
                    capabilities=frozenset({"admin:vendors"}),
                    resource_scope=("vendor:*",),
                    constraints=AuthorityConstraints(max_amount=usd(0)),
                ),
                now=NOW,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_EXCEEDS_PARENT_CAPABILITIES


class TestChainIntegrity:
    def test_grantor_must_be_grantee_of_parent(
        self, service: DelegationService, orchestrator_grant: DelegationGrant
    ) -> None:
        """A rogue agent cannot delegate from a grant it does not hold."""
        rogue = PrincipalRef(id="rogue-agent", kind=PrincipalKind.AGENT)
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(grantor=rogue, parent_grant_id=orchestrator_grant.grant_id), now=NOW
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_GRANTOR_NOT_GRANTEE_OF_PARENT

    def test_self_delegation_denied(
        self, service: DelegationService, orchestrator_grant: DelegationGrant
    ) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(grantee=ORCHESTRATOR, parent_grant_id=orchestrator_grant.grant_id),
                now=NOW,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_SELF_GRANT

    def test_unknown_parent(self, service: DelegationService) -> None:
        with pytest.raises(DelegationError) as exc:
            service.issue(_request(parent_grant_id="grt_nope"), now=NOW)
        assert exc.value.reason_code is ReasonCode.DELEGATION_PARENT_INVALID

    def test_cannot_delegate_from_expired_parent(
        self, service: DelegationService, ap_grant: DelegationGrant
    ) -> None:
        later = NOW + timedelta(days=2)  # ap_grant expired after 1 day
        with pytest.raises(DelegationError) as exc:
            service.issue(
                _request(
                    grantor=AP_AGENT,
                    grantee=DOC_AGENT,
                    parent_grant_id=ap_grant.grant_id,
                    capabilities=frozenset({"read:invoice"}),
                    resource_scope=("invoice:*",),
                    constraints=AuthorityConstraints(max_amount=usd(0)),
                    expires_at=later + timedelta(minutes=1),
                ),
                now=later,
            )
        assert exc.value.reason_code is ReasonCode.DELEGATION_PARENT_INVALID


class TestResolution:
    def test_effective_authority_is_chain_intersection(
        self, service: DelegationService, doc_grant: DelegationGrant
    ) -> None:
        chain = service.resolve(doc_grant.grant_id, agent=DOC_AGENT, principal=HUMAN, now=NOW)
        auth = chain.authority
        assert [g.grantee.id for g in chain.grants] == [
            HUMAN.id,
            ORCHESTRATOR.id,
            AP_AGENT.id,
            DOC_AGENT.id,
        ]
        assert auth.capabilities == frozenset({"read:invoice"})
        assert auth.resource_scope == ("invoice:*",)
        assert auth.constraints.max_amount is not None
        assert auth.constraints.max_amount.amount == Decimal("0.00")
        assert auth.constraints.currencies == frozenset({"USD"})
        assert auth.expires_at == doc_grant.expires_at
        assert auth.root_principal == HUMAN
        assert auth.holder == DOC_AGENT
        assert auth.depth == 4

    def test_ap_agent_authority(
        self, service: DelegationService, ap_grant: DelegationGrant
    ) -> None:
        auth = service.resolve(ap_grant.grant_id, agent=AP_AGENT, now=NOW).authority
        assert auth.constraints.max_amount == usd(1_000)
        assert auth.capabilities == frozenset({"read:invoice", "pay:vendor"})

    def test_expired_leaf_fails(
        self, service: DelegationService, ap_grant: DelegationGrant
    ) -> None:
        with pytest.raises(DelegationError) as exc:
            service.resolve(ap_grant.grant_id, now=NOW + timedelta(days=2))
        assert exc.value.reason_code is ReasonCode.DELEGATION_EXPIRED

    def test_expired_ancestor_fails_even_if_leaf_is_valid(
        self, service: DelegationService, doc_grant: DelegationGrant
    ) -> None:
        """Simulate the AP grant being revoked; the document agent's still-valid
        leaf grant must stop working because its ancestor is gone."""
        service.revoke(doc_grant.parent_grant_id or "", now=NOW)
        with pytest.raises(DelegationError) as exc:
            service.resolve(doc_grant.grant_id, now=NOW)
        assert exc.value.reason_code is ReasonCode.DELEGATION_REVOKED

    def test_grantee_mismatch(self, service: DelegationService, ap_grant: DelegationGrant) -> None:
        """A compromised child presenting its parent's grant id is rejected."""
        with pytest.raises(DelegationError) as exc:
            service.resolve(ap_grant.grant_id, agent=DOC_AGENT, now=NOW)
        assert exc.value.reason_code is ReasonCode.DELEGATION_GRANTEE_MISMATCH

    def test_principal_mismatch(
        self, service: DelegationService, ap_grant: DelegationGrant
    ) -> None:
        other_human = PrincipalRef(id="someone-else", kind=PrincipalKind.HUMAN)
        with pytest.raises(DelegationError) as exc:
            service.resolve(ap_grant.grant_id, principal=other_human, now=NOW)
        assert exc.value.reason_code is ReasonCode.DELEGATION_PRINCIPAL_MISMATCH

    def test_unknown_grant(self, service: DelegationService) -> None:
        with pytest.raises(DelegationError) as exc:
            service.resolve("grt_missing", now=NOW)
        assert exc.value.reason_code is ReasonCode.DELEGATION_NOT_FOUND

    def test_tampered_store_cannot_widen_authority(
        self, service: DelegationService, ap_grant: DelegationGrant
    ) -> None:
        """Even if a wider grant is written directly to the store (bypassing
        ``issue``), resolution intersects and the parent's limit still applies."""
        smuggled = DelegationGrant(
            label="smuggled",
            grantor=AP_AGENT,
            grantee=DOC_AGENT,
            parent_grant_id=ap_grant.grant_id,
            capabilities=frozenset({"pay:vendor", "admin:vendors"}),
            resource_scope=("vendor:*", "payroll:*"),
            constraints=AuthorityConstraints(max_amount=usd(999_999)),
            expires_at=NOW + timedelta(days=365),
        )
        service.store.put(smuggled)
        auth = service.resolve(smuggled.grant_id, agent=DOC_AGENT, now=NOW).authority
        assert auth.constraints.max_amount == usd(1_000)
        assert auth.capabilities == frozenset({"pay:vendor"})
        assert auth.resource_scope == ("vendor:*",)
        assert auth.expires_at == ap_grant.expires_at

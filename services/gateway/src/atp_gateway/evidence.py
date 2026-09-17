"""Evidence bundles: one portable JSON file per trace.

A bundle carries the recorded envelope (with content excerpts and the agent's
rationale removed unless asked for), the decision with every evaluation, the
delegation chain snapshot, the execution outcome, replays, the full event
list and the chain integrity report, plus a deterministic ``bundle_hash``
over the canonical JSON of everything else. It never carries credentials,
grant tokens or keys: none of those are in traces to begin with.

Anyone holding a bundle can re-verify the event hash chain offline with
``verify_bundle``; that proves internal consistency, not that the bundle
came from a particular gateway (see docs/security/trace-integrity.md).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atp_audit import TraceEvent, verify_events
from atp_core import canonical_hash, utcnow
from atp_gateway.service import TraceView

BUNDLE_VERSION = 1


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_version: int = BUNDLE_VERSION
    exported_at: str
    trace_id: str
    envelope: dict[str, Any] | None
    decision: dict[str, Any] | None
    delegation_chain: list[dict[str, Any]]
    execution: dict[str, Any] | None
    replays: list[dict[str, Any]]
    events: list[dict[str, Any]]
    integrity: dict[str, Any]
    redactions: list[str] = Field(default_factory=list)
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def _redact_envelope(
    envelope: dict[str, Any], include_excerpts: bool
) -> tuple[dict[str, Any], list[str]]:
    redactions: list[str] = []
    if include_excerpts:
        return envelope, redactions
    prov = dict(envelope.get("provenance") or {})
    sources = []
    for src in prov.get("content_sources") or []:
        src = dict(src)
        if src.get("excerpt") is not None:
            src["excerpt"] = None
            redactions.append(f"provenance.content_sources[{src.get('source_id')}].excerpt")
        sources.append(src)
    prov["content_sources"] = sources
    if prov.get("agent_rationale") is not None:
        prov["agent_rationale"] = None
        redactions.append("provenance.agent_rationale")
    return {**envelope, "provenance": prov}, redactions


def _redact_events(events: list[dict[str, Any]], redactions: list[str]) -> list[dict[str, Any]]:
    """Events are hashed; they cannot be redacted without breaking the chain.
    If the envelope was redacted, the ``action_proposed`` event still holds
    the original. We keep events intact so the chain verifies and say so."""
    if redactions:
        redactions.append("note: events are kept verbatim so the hash chain verifies")
    return events


def build_bundle(view: TraceView, *, include_excerpts: bool = False) -> EvidenceBundle:
    envelope: dict[str, Any] | None = None
    redactions: list[str] = []
    if view.envelope is not None:
        envelope, redactions = _redact_envelope(
            view.envelope.model_dump(mode="json"), include_excerpts
        )
    events = _redact_events([e.model_dump(mode="json") for e in view.events], redactions)
    body: dict[str, Any] = {
        "bundle_version": BUNDLE_VERSION,
        "exported_at": utcnow().isoformat(),
        "trace_id": view.trace_id,
        "envelope": envelope,
        "decision": view.decision.model_dump(mode="json") if view.decision else None,
        "delegation_chain": view.delegation_chain,
        "execution": view.execution,
        "replays": view.replays,
        "events": events,
        "integrity": view.integrity.model_dump(mode="json"),
        "redactions": redactions,
    }
    return EvidenceBundle(**body, bundle_hash=canonical_hash(body))


def verify_bundle(data: dict[str, Any]) -> tuple[bool, str]:
    """Offline check: the bundle hash matches, and the event chain inside it
    verifies. Returns (ok, detail)."""
    try:
        bundle = EvidenceBundle.model_validate(data)
    except ValueError as exc:
        return False, f"malformed bundle: {exc}"
    body = bundle.model_dump(mode="json", exclude={"bundle_hash"})
    if canonical_hash(body) != bundle.bundle_hash:
        return False, "bundle_hash does not match the bundle contents"
    events = [TraceEvent.model_validate(e) for e in bundle.events]
    report = verify_events(bundle.trace_id, events)
    if not report.valid:
        return False, f"event chain invalid: {report.detail}"
    if report.head_hash != bundle.integrity.get("head_hash"):
        return False, "integrity.head_hash does not match the recomputed chain head"
    return True, f"bundle and {len(events)}-event chain verify; head {report.head_hash[:16]}"

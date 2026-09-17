"""The ActionEnvelope: the single contract an agent uses to ask for anything.

Design notes
------------
* The envelope names *who* is asking (agent), *on whose behalf* (principal),
  *under which grant* (delegation_grant_id), *what* (tool/action/resource/
  arguments) and *why* (provenance). It does **not** carry any authorization
  claims. Authority is resolved server-side from the grant id.
* ``extra="forbid"`` is deliberate: a client that adds ``"authorized": true``
  gets a validation error, not a silently ignored field.
* ``action_hash`` is the value an execution grant is bound to. It covers every
  field that defines what will happen, and nothing descriptive.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atp_core.canonical import canonical_hash, canonical_json
from atp_core.ids import new_id, new_trace_id
from atp_core.principals import PrincipalRef
from atp_core.resources import RESOURCE_PATTERN
from atp_core.timeutil import utcnow

_IDENT = r"^[A-Za-z0-9._:-]+$"
MAX_ARGUMENTS_BYTES = 16 * 1024


class ContentTrust(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class ContentSource(BaseModel):
    """A piece of content that entered the agent's context before it acted.

    Recording this is what lets an auditor answer "what influenced this
    attempt?". Anything retrieved from outside the trust boundary (documents,
    email bodies, web pages, tool output) is ``untrusted``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(
        min_length=1,
        max_length=64,
        description="e.g. invoice_pdf, email_body, web_page, tool_output",
    )
    origin: str = Field(
        min_length=1,
        max_length=256,
        description="Where it came from: a URL, mailbox, file path, tool name.",
    )
    trust: ContentTrust
    content_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of the raw content so the trace can prove what was seen.",
    )
    excerpt: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional short excerpt for human review. Never authoritative.",
    )


class Provenance(BaseModel):
    """Descriptive metadata about how the proposal came to be."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str | None = Field(default=None, max_length=128)
    task_description: str | None = Field(default=None, max_length=2000)
    content_sources: tuple[ContentSource, ...] = ()
    model: str | None = Field(
        default=None,
        max_length=128,
        description="Model identifier that produced the proposal, if any.",
    )
    agent_rationale: str | None = Field(
        default=None,
        max_length=4000,
        description="The agent's stated reason. Recorded for audit, never trusted.",
    )


class ActionEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope_id: str = Field(default_factory=lambda: new_id("env"))
    trace_id: str = Field(default_factory=new_trace_id, pattern=r"^[0-9a-f]{12}$")
    issued_at: datetime = Field(default_factory=utcnow)

    principal: PrincipalRef = Field(description="Human authority source (acting_for).")
    agent: PrincipalRef = Field(description="The agent proposing the action.")
    delegation_grant_id: str = Field(
        min_length=1,
        max_length=128,
        description="Grant the agent claims to act under. Resolved server-side.",
    )

    capability: str = Field(pattern=_IDENT, max_length=128, description="e.g. pay:vendor")
    tool: str = Field(pattern=_IDENT, max_length=64)
    action: str = Field(pattern=_IDENT, max_length=64)
    resource: str = Field(
        pattern=RESOURCE_PATTERN, max_length=320, description="e.g. vendor:128 or path:/work/a.txt"
    )
    arguments: dict[str, Any] = Field(default_factory=dict)

    provenance: Provenance = Field(default_factory=Provenance)

    @field_validator("arguments")
    @classmethod
    def _bounded_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        size = len(canonical_json(value))
        if size > MAX_ARGUMENTS_BYTES:
            raise ValueError(f"arguments exceed {MAX_ARGUMENTS_BYTES} bytes ({size})")
        return value

    def action_fields(self) -> dict[str, Any]:
        """The fields that define *what will happen*. Hashed into execution grants."""
        return {
            "envelope_id": self.envelope_id,
            "trace_id": self.trace_id,
            "principal": self.principal.model_dump(mode="json"),
            "agent": self.agent.model_dump(mode="json"),
            "delegation_grant_id": self.delegation_grant_id,
            "capability": self.capability,
            "tool": self.tool,
            "action": self.action,
            "resource": self.resource,
            "arguments": self.arguments,
        }

    @property
    def action_hash(self) -> str:
        return canonical_hash(self.action_fields())

    @property
    def qualified_action(self) -> str:
        return f"{self.tool}.{self.action}"

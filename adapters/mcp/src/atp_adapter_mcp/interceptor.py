"""Intercept MCP ``tools/call`` requests and route them through the trust plane.

The Model Context Protocol gives agents a uniform way to call tools. It does
not give anyone a way to say *whether this agent may call this tool with
these arguments*. This adapter sits between an MCP client (the model host)
and the real tool: every call becomes an ``ActionEnvelope``, is authorized,
and only executes through the gateway.

Design choices:

* **Unmapped tools are denied.** A tool with no ``ToolMapping`` never reaches
  the gateway and never executes. Default-deny is the only safe default for
  an interceptor.
* **The resource is derived from arguments by template**, e.g.
  ``vendor:{vendor_id}``. The mapping decides which argument names the
  resource so that a policy can scope it.
* **The result is an MCP-shaped tool result.** A denial is returned as an
  ``is_error`` result whose text is the decision block, so the model sees a
  clear, structured refusal rather than a stack trace.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atp_adapter_http import TrustPlaneClient
from atp_core import ActionEnvelope, PrincipalRef, Provenance, new_trace_id


class McpToolCall(BaseModel):
    """The shape of an MCP ``tools/call`` request's params."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class McpToolResult(BaseModel):
    """The shape of an MCP ``tools/call`` result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: list[dict[str, Any]]
    is_error: bool = Field(default=False, serialization_alias="isError")
    structured_content: dict[str, Any] | None = Field(
        default=None, serialization_alias="structuredContent"
    )


class ToolMapping(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mcp_tool: str = Field(description="MCP tool name, e.g. 'send_payment'")
    tool: str = Field(description="Trust-plane tool, e.g. 'payments'")
    action: str = Field(description="Trust-plane action, e.g. 'send_payment'")
    capability: str = Field(description="Capability required, e.g. 'pay:vendor'")
    resource_template: str = Field(
        description="Resource string with argument placeholders, e.g. 'vendor:{vendor_id}'"
    )
    resource_arguments: tuple[str, ...] = Field(
        default=(),
        description="Argument names consumed by the template and removed from the envelope "
        "arguments (they are part of the resource, not the payload).",
    )

    def resource_for(self, arguments: dict[str, Any]) -> str:
        try:
            return self.resource_template.format(**arguments)
        except KeyError as exc:
            raise ValueError(f"argument {exc} required to identify the resource") from exc


class AgentContext(BaseModel):
    """Who is calling, on whose behalf, under which grant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal: PrincipalRef
    agent: PrincipalRef
    delegation_grant_id: str
    model: str | None = None
    task_id: str | None = None


class McpInterceptor:
    def __init__(self, client: TrustPlaneClient, mappings: list[ToolMapping]) -> None:
        self._client = client
        self._mappings = {m.mcp_tool: m for m in mappings}

    def mapped_tools(self) -> list[str]:
        return sorted(self._mappings)

    def to_envelope(
        self, call: McpToolCall, ctx: AgentContext, *, trace_id: str | None = None
    ) -> ActionEnvelope:
        mapping = self._mappings.get(call.name)
        if mapping is None:
            raise LookupError(
                f"MCP tool '{call.name}' has no trust-plane mapping; denied by default"
            )
        resource = mapping.resource_for(call.arguments)
        arguments = {k: v for k, v in call.arguments.items() if k not in mapping.resource_arguments}
        return ActionEnvelope(
            trace_id=trace_id or new_trace_id(),
            principal=ctx.principal,
            agent=ctx.agent,
            delegation_grant_id=ctx.delegation_grant_id,
            capability=mapping.capability,
            tool=mapping.tool,
            action=mapping.action,
            resource=resource,
            arguments=arguments,
            provenance=Provenance(task_id=ctx.task_id, model=ctx.model),
        )

    def intercept(
        self, call: McpToolCall, ctx: AgentContext, *, trace_id: str | None = None
    ) -> McpToolResult:
        try:
            envelope = self.to_envelope(call, ctx, trace_id=trace_id)
        except (LookupError, ValueError) as exc:
            return _error({"reason_code": "TOOL_NOT_MAPPED", "message": str(exc)})

        auth = self._client.authorize(envelope)
        decision = auth.decision
        if auth.execution_grant is None:
            return _error(
                {
                    "reason_code": decision.reason_code.value,
                    "outcome": decision.outcome.value,
                    "message": decision.explanation,
                    "matched_policy": (
                        decision.matched_policy.qualified if decision.matched_policy else None
                    ),
                    "trace_id": envelope.trace_id,
                }
            )
        execution = self._client.execute(envelope, auth.execution_grant)
        payload = {
            "status": execution.status,
            "reason_code": execution.reason_code.value,
            "trace_id": envelope.trace_id,
            "result": execution.result,
        }
        return McpToolResult(
            content=[{"type": "text", "text": json.dumps(payload)}],
            is_error=not execution.executed,
            structured_content=payload,
        )


def _error(payload: dict[str, Any]) -> McpToolResult:
    return McpToolResult(
        content=[{"type": "text", "text": json.dumps(payload)}],
        is_error=True,
        structured_content=payload,
    )


DEFAULT_MAPPINGS: list[ToolMapping] = [
    ToolMapping(
        mcp_tool="send_payment",
        tool="payments",
        action="send_payment",
        capability="pay:vendor",
        resource_template="vendor:{vendor_id}",
        resource_arguments=("vendor_id",),
    ),
]

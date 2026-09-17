"""How an MCP tool call becomes a trust-plane action.

A ``ToolMapping`` names the capability a call needs and derives the
resource it acts on from the call's arguments. The resource string is what
delegation scopes are matched against, so for path-like arguments the
mapping can normalise the value first (``..`` segments, separators, case)
so that ``path:/work/*`` cannot be escaped with ``/work/../etc``.

Unmapped tools are denied by default: the proxy sends them to the gateway
under the never-delegated capability ``mcp:unmapped`` so the denial is on
the record, and hides them from ``tools/list``.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from atp_core.resources import RESOURCE_PATTERN

UNMAPPED_CAPABILITY = "mcp:unmapped"
_RESOURCE_RE = re.compile(RESOURCE_PATTERN)
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class PathNormalization(BaseModel):
    """Normalise a path argument before it is placed in the resource string.

    * backslashes become ``/``; repeated separators collapse; ``.`` and ``..``
      segments are resolved textually (``posixpath.normpath``);
    * a relative path is resolved against ``base_dir`` if given, otherwise
      refused (the proxy cannot know what the upstream would resolve it
      against);
    * ``casefold`` lower-cases the result for case-insensitive filesystems
      (Windows, default macOS); set it when the upstream runs on one;
    * a Windows drive (``C:``) is kept as ``c:`` when casefolded.

    What this does not do: resolve symlinks or junctions. Two paths that are
    the same file through a link are different strings here; scope the link
    target too, or forbid links in the upstream's root.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_dir: str | None = Field(
        default=None, description="Absolute directory relative paths resolve against."
    )
    casefold: bool = False

    def apply(self, value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("path argument must be a non-empty string")
        if "\x00" in value:
            raise ValueError("path contains NUL")
        text = value.replace("\\", "/")
        drive = ""
        m = re.match(r"^([A-Za-z]):(/.*)?$", text)
        if m:
            drive = m.group(1) + ":"
            text = m.group(2) or "/"
        if not text.startswith("/"):
            if self.base_dir is None:
                raise ValueError(
                    f"relative path {value!r} cannot be scoped without base_dir; refuse"
                )
            base = self.base_dir.replace("\\", "/")
            bm = re.match(r"^([A-Za-z]):(/.*)?$", base)
            if bm:
                drive = bm.group(1) + ":"
                base = bm.group(2) or "/"
            text = posixpath.join(base, text)
        norm = posixpath.normpath(text)
        if norm.startswith("//"):
            norm = "/" + norm.lstrip("/")
        if norm.startswith("/.."):
            raise ValueError("path escapes the root")
        out = drive + norm
        return out.casefold() if self.casefold else out


class ToolMapping(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mcp_tool: str = Field(
        pattern=r"^[A-Za-z0-9._-]{1,128}$", description="MCP tool name, e.g. 'write_file'"
    )
    tool: str = Field(
        pattern=r"^[A-Za-z0-9._:-]{1,64}$",
        description="Trust-plane tool, e.g. 'mcp.filesystem'",
    )
    action: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,64}$", description="e.g. 'write_file'")
    capability: str = Field(
        pattern=r"^[A-Za-z0-9._:-]{1,128}$", description="Capability required, e.g. 'fs:write'"
    )
    resource_template: str = Field(
        max_length=320,
        description="Resource string with argument placeholders, e.g. 'path:{path}'. "
        "'tool:<name>' when the tool acts on nothing in particular.",
    )
    path_normalization: PathNormalization | None = Field(
        default=None,
        description="Apply path normalisation to every placeholder argument before formatting.",
    )
    description: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _template_shape(self) -> ToolMapping:
        if ":" not in self.resource_template:
            raise ValueError(f"resource_template {self.resource_template!r} needs '<type>:'")
        if "*" in self.resource_template:
            raise ValueError("resource_template may not contain '*'")
        return self

    @property
    def resource_arguments(self) -> tuple[str, ...]:
        return tuple(_PLACEHOLDER.findall(self.resource_template))

    def resource_for(self, arguments: dict[str, Any]) -> str:
        """Build the concrete resource. Raises ``ValueError`` when an argument is
        missing, not a scalar, or produces an invalid resource (fail closed)."""
        values: dict[str, str] = {}
        for name in self.resource_arguments:
            if name not in arguments:
                raise ValueError(f"argument {name!r} required to identify the resource")
            raw = arguments[name]
            if self.path_normalization is not None:
                values[name] = self.path_normalization.apply(raw)
            elif isinstance(raw, str | int):
                values[name] = str(raw)
            else:
                raise ValueError(f"argument {name!r} must be a string or integer")
        resource = self.resource_template.format(**values)
        if not _RESOURCE_RE.fullmatch(resource):
            raise ValueError(f"derived resource {resource!r} is not a valid resource")
        return resource

"""Resource scope patterns.

A concrete resource is ``<type>:<id>``. A pattern is one of:

* ``<type>:<id>``      exactly that resource;
* ``<type>:<prefix>*`` any resource of that type whose id starts with
  ``<prefix>`` (string prefix; scope a directory as ``path:/work/*``);
* ``<type>:*``         any id of that type;
* ``*``                anything.

``*`` is reserved: it may only appear as the whole pattern, as the whole
id, or as the last character of a prefix pattern, and never in a concrete
resource. Subsumption (``covers``) is decidable by inspection, which is what
makes "a child scope must be covered by its parent scope" checkable when a
delegation is issued, and evaluation is a pure string comparison: no
globbing, no regular expressions, so no pathological inputs.

Prefix matching is *textual*. Whoever builds the resource string (the MCP
adapter's ``ToolMapping``) is responsible for normalising paths first; see
``atp_adapter_mcp.interceptor.PathNormalization``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from atp_core.resources import RESOURCE_PATTERN, SCOPE_PATTERN

WILDCARD = "*"

_RESOURCE_RE = re.compile(RESOURCE_PATTERN)
_SCOPE_RE = re.compile(SCOPE_PATTERN)


def _split(value: str) -> tuple[str, str]:
    if value == WILDCARD:
        return WILDCARD, WILDCARD
    if ":" not in value:
        raise ValueError(
            f"resource pattern must be '<type>:<id>', '<type>:<prefix>*', '<type>:*' or '*': "
            f"{value!r}"
        )
    typ, ident = value.split(":", 1)
    if not typ or not ident:
        raise ValueError(f"malformed resource pattern: {value!r}")
    return typ, ident


def _is_prefix(ident: str) -> bool:
    return ident != WILDCARD and ident.endswith(WILDCARD)


def validate_pattern(pattern: str) -> str:
    if not _SCOPE_RE.fullmatch(pattern):
        raise ValueError(
            f"invalid resource pattern {pattern!r}: expected '<type>:<id>', "
            "'<type>:<prefix>*', '<type>:*' or '*' (no other '*', no control characters)"
        )
    _split(pattern)
    return pattern


def validate_resource(resource: str) -> str:
    """A concrete resource: ``<type>:<id>`` with no wildcard anywhere."""
    if not _RESOURCE_RE.fullmatch(resource):
        raise ValueError(
            f"invalid resource {resource!r}: expected '<type>:<id>' with no '*' and no "
            "control characters"
        )
    return resource


def matches(pattern: str, resource: str) -> bool:
    """Does ``pattern`` match the concrete ``resource``?"""
    p_type, p_id = _split(pattern)
    r_type, r_id = _split(resource)
    if WILDCARD in r_id:
        # A concrete resource is never a wildcard or a prefix.
        return False
    if p_type == WILDCARD:
        return True
    if p_type != r_type:
        return False
    if p_id == WILDCARD:
        return True
    if _is_prefix(p_id):
        return r_id.startswith(p_id[:-1])
    return p_id == r_id


def covers(parent_pattern: str, child_pattern: str) -> bool:
    """Is every resource matched by ``child_pattern`` also matched by ``parent_pattern``?"""
    p_type, p_id = _split(parent_pattern)
    c_type, c_id = _split(child_pattern)
    if p_type == WILDCARD:
        return True
    if c_type == WILDCARD:
        return False
    if p_type != c_type:
        return False
    if p_id == WILDCARD:
        return True
    if c_id == WILDCARD:
        return False
    if _is_prefix(p_id):
        child_stem = c_id[:-1] if _is_prefix(c_id) else c_id
        return child_stem.startswith(p_id[:-1])
    # An exact parent covers only the identical exact child; a prefix child
    # would match resources the parent does not.
    return not _is_prefix(c_id) and p_id == c_id


def scope_covers(parent_scope: Iterable[str], child_scope: Iterable[str]) -> bool:
    """Every child pattern must be covered by at least one parent pattern."""
    parents = list(parent_scope)
    return all(any(covers(p, c) for p in parents) for c in child_scope)


def scope_matches(scope: Iterable[str], resource: str) -> bool:
    return any(matches(p, resource) for p in scope)

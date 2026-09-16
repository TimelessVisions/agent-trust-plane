"""Resource scope patterns.

Patterns are deliberately simple: a resource is ``<type>:<id>`` and a pattern
is either an exact resource, ``<type>:*`` (any id of that type), or ``*``
(anything). Subsumption is decidable by inspection, which is what makes the
"child scope must be covered by parent scope" invariant checkable at issuance.
"""

from __future__ import annotations

from collections.abc import Iterable

WILDCARD = "*"


def _split(value: str) -> tuple[str, str]:
    if value == WILDCARD:
        return WILDCARD, WILDCARD
    if ":" not in value:
        raise ValueError(f"resource pattern must be '<type>:<id>', '<type>:*' or '*': {value!r}")
    typ, ident = value.split(":", 1)
    if not typ or not ident:
        raise ValueError(f"malformed resource pattern: {value!r}")
    return typ, ident


def validate_pattern(pattern: str) -> str:
    _split(pattern)
    return pattern


def matches(pattern: str, resource: str) -> bool:
    """Does ``pattern`` match the concrete ``resource``?"""
    p_type, p_id = _split(pattern)
    r_type, r_id = _split(resource)
    if r_id == WILDCARD:
        # A concrete resource is never a wildcard.
        return False
    if p_type == WILDCARD:
        return True
    if p_type != r_type:
        return False
    return p_id in (WILDCARD, r_id)


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
    return p_id in (WILDCARD, c_id)


def scope_covers(parent_scope: Iterable[str], child_scope: Iterable[str]) -> bool:
    """Every child pattern must be covered by at least one parent pattern."""
    parents = list(parent_scope)
    return all(any(covers(p, c) for p in parents) for c in child_scope)


def scope_matches(scope: Iterable[str], resource: str) -> bool:
    return any(matches(p, resource) for p in scope)

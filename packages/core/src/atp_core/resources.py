"""Resource and scope pattern grammar, shared by the envelope (concrete
resources), the identity layer (scope patterns) and the regression format.

A concrete resource is ``<type>:<id>``. A scope pattern additionally allows
``<type>:*``, ``<type>:<prefix>*`` and ``*``. ``*`` is reserved and may not
appear anywhere else; control characters are never allowed. ``/`` is allowed
in ids so paths and URIs can be resources. Matching semantics live in
``atp_identity.scope``.
"""

from __future__ import annotations

RESOURCE_PATTERN = r"^[A-Za-z0-9._-]{1,64}:[^*\x00-\x1f\x7f]{1,255}$"
SCOPE_PATTERN = r"^(\*|[A-Za-z0-9._-]{1,64}:(\*|[^*\x00-\x1f\x7f]{1,254}\*?))$"

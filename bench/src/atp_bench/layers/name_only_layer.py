"""A deliberately minimal, explicitly labeled name-only reference gateway.

This is NOT a third-party product. It filters tool calls only by the annotation's
capability names, forwarding the original arguments unchanged. Its limitations
are intentional and disclosed in bench/competitors/name-only.md.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from atp_bench.annotations import Annotation
from atp_bench.dojo import Call, DojoSuite
from atp_bench.layers.base import CallOutcome, DroppedConstraint, Session
from atp_bench.layers.open_layer import OpenLayer

DOC = (
    "https://github.com/TimelessVisions/agent-trust-plane/blob/"
    "release/v1/B12-atp-1.0/bench/competitors/name-only.md"
)


class _NameOnlySession:
    def __init__(self, upstream: Session, allowed: frozenset[str]) -> None:
        self._upstream = upstream
        self._allowed = allowed

    def call(self, call: Call) -> CallOutcome:
        if call.function not in self._allowed:
            return CallOutcome("DENIED", f"name-only reference: {call.function} not granted")
        # This intentionally does not inspect, modify, or validate the arguments.
        return self._upstream.call(call)


class NameOnlyLayer:
    name = "name-only"

    def __init__(self, timeout_s: float = 30.0) -> None:
        self.timeout_s = timeout_s

    def dropped_constraints(
        self, suite: DojoSuite, annotation: Annotation
    ) -> list[DroppedConstraint]:
        items = [
            DroppedConstraint(
                source=f"resource_scope:{tool}",
                reason="name-only reference does not enforce per-resource scope",
                doc_url=DOC,
            )
            for tool in annotation.resource_args
        ]
        items.extend(
            DroppedConstraint(
                source=str(rule["id"]),
                reason="name-only reference ignores all argument and deny/approval rules",
                doc_url=DOC,
            )
            for rule in annotation.rules
        )
        return items

    @contextmanager
    def open(
        self,
        suite: DojoSuite,
        annotation: Annotation,
        injection_task: str | None,
        journal: Path,
        workdir: Path,
    ) -> Iterator[Session]:
        with OpenLayer(timeout_s=self.timeout_s).open(
            suite, annotation, injection_task, journal, workdir
        ) as upstream:
            yield _NameOnlySession(upstream, frozenset(annotation.capabilities))

"""Bounded file reads for untrusted YAML/JSON inputs (policy files, suites,
proxy configs, evidence bundles). PyYAML's ``safe_load`` still expands
anchors and aliases, so a small file can describe a large document; capping
the *file* keeps the expansion bounded too."""

from __future__ import annotations

from pathlib import Path

MAX_INPUT_BYTES = 1 * 1024 * 1024


def read_bounded_text(path: str | Path, *, limit: int = MAX_INPUT_BYTES) -> str:
    p = Path(path)
    size = p.stat().st_size
    if size > limit:
        raise ValueError(f"{p}: {size} bytes exceeds the {limit}-byte input limit")
    return p.read_text(encoding="utf-8")

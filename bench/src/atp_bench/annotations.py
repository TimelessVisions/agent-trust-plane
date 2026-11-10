"""Per-task delegation annotations, written before any run and pre-registered by git tag.

See ``bench/ANNOTATION_RULE.md`` for how an annotation is derived. Annotations name suite
TOOL NAMES; a later step renders them into ATP capability strings and configs.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from atp_bench.dojo import load_suite
from atp_core import SCOPE_PATTERN
from atp_policy.declarative import RuleSpec

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "annotations"
DEFAULT_TAG = "bench-annotations-v1"

_FORBIDDEN = re.compile(r"injection[_ ]?task", re.IGNORECASE)


def _check_rule(rule: dict[str, Any]) -> None:
    if not isinstance(rule, dict):
        raise ValueError("rule must be a mapping")
    try:
        RuleSpec.model_validate(rule)
    except ValidationError as exc:
        raise ValueError(f"invalid rule {rule.get('id')!r}: {exc}") from exc


class Annotation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_task: str
    status: Literal["ok", "not_applicable"]
    reason: str = ""
    capabilities: tuple[str, ...] = ()
    resource_scope: tuple[str, ...] = ()
    resource_args: dict[str, str] = Field(default_factory=dict)
    rules: tuple[dict, ...] = ()
    rationale: str = Field(min_length=20)

    @model_validator(mode="after")
    def _check(self) -> Annotation:
        if self.status == "not_applicable":
            if not self.reason.strip():
                raise ValueError("not_applicable requires a reason")
            if self.capabilities or self.resource_scope or self.rules or self.resource_args:
                raise ValueError("not_applicable must not carry capabilities, scope or rules")
        elif not self.capabilities:
            raise ValueError("status ok requires at least one capability")
        for pat in self.resource_scope:
            if not re.fullmatch(SCOPE_PATTERN, pat):
                raise ValueError(f"resource_scope {pat!r} does not match ATP SCOPE_PATTERN")
        for tool in self.resource_args:
            if tool not in self.capabilities:
                raise ValueError(f"resource_args names {tool!r}, which is not in capabilities")
        for rule in self.rules:
            _check_rule(rule)
        blob = json.dumps(
            [self.rationale, self.reason, self.resource_scope, self.rules], default=str
        )
        if _FORBIDDEN.search(blob):
            raise ValueError("annotation must not reference injection tasks")
        return self


def load_annotations(root: Path, suite: str) -> dict[str, Annotation]:
    """Load and validate ``<root>/<suite>.yaml`` against the real suite."""
    raw = yaml.safe_load((Path(root) / f"{suite}.yaml").read_text(encoding="utf-8"))
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError(f"{suite}.yaml must be a list of annotations")
    dojo = load_suite(suite)
    tools, tasks = set(dojo.tool_names), set(dojo.user_task_ids())
    out: dict[str, Annotation] = {}
    for item in raw:
        ann = Annotation.model_validate(item)
        if ann.user_task not in tasks:
            raise ValueError(f"{suite}: unknown user task {ann.user_task!r}")
        if ann.user_task in out:
            raise ValueError(f"{suite}: duplicate annotation for {ann.user_task!r}")
        unknown = sorted(set(ann.capabilities) - tools)
        if unknown:
            raise ValueError(f"{suite}/{ann.user_task}: unknown tool(s) in capabilities: {unknown}")
        out[ann.user_task] = ann
    return out


def ok_annotations(suites: list[str], root: Path = DEFAULT_ROOT) -> list[tuple[str, str]]:
    """(suite, user_task) pairs whose annotation status is ``ok``."""
    return [
        (s, t)
        for s in suites
        for t, a in sorted(load_annotations(root, s).items())
        if a.status == "ok"
    ]


class NotPreregistered(Exception):  # noqa: N818 - public name, kept
    """Annotations differ from the pre-registration tag, or the tag is missing."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def assert_preregistered(repo: Path, tag: str = DEFAULT_TAG) -> None:
    """Raise unless ``bench/annotations`` is byte-identical to the tagged commit."""
    if _git(repo, "rev-parse", "--verify", f"{tag}^{{commit}}").returncode != 0:
        raise NotPreregistered(f"pre-registration tag {tag!r} not found in {repo}")
    diff = _git(repo, "diff", "--name-only", tag, "--", "bench/annotations")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard", "bench/annotations")
    for p in (diff, untracked):
        if p.returncode != 0:
            raise NotPreregistered(f"git failed: {p.stderr.strip()}")
    changed = sorted({*diff.stdout.split(), *untracked.stdout.split()})
    if changed:
        raise NotPreregistered(f"annotations changed since tag {tag!r}: {', '.join(changed)}")

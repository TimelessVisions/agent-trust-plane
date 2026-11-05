"""Replay documented MCP incident calls against a fixture's real layer session.

This is a deterministic, model-free harness. A fixture owns actual server
startup/definition mutation and returns a Session for the selected Layer.
No outcome is credited without a conclusive call; failures are never silently
converted into DENIED or PASS. See bench/incidents/README.md.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atp_bench.dojo import Call
from atp_bench.layers.base import EnvBlocked, Layer

_INCIDENT_ROOT = Path(__file__).resolve().parents[2] / "incidents"

Expected = Literal["ALLOWED", "DENIED"]
ResultStatus = Literal["PASS", "FAIL", "INCONCLUSIVE", "ENV_BLOCKED"]


class IncidentStep(BaseModel):
    """Exactly one tool call or an instrumented server-definition mutation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    function: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    definition_change: str | None = None

    @model_validator(mode="after")
    def _one_action(self) -> IncidentStep:
        if (self.function is None) == (self.definition_change is None):
            raise ValueError("incident step needs exactly one function or definition_change")
        if self.definition_change is not None and self.args:
            raise ValueError("a definition change cannot carry tool-call arguments")
        return self


class IncidentCase(BaseModel):
    """Pinned input: source, fixture, replay script, expected results and regression."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,80}$")
    title: str = Field(min_length=8)
    source_urls: tuple[str, ...] = Field(min_length=1)
    server: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,80}/server\.py$")
    calls: tuple[IncidentStep, ...] = Field(min_length=1)
    expect: dict[str, Expected]
    atp_regression: str = Field(
        pattern=r"^[a-z0-9][a-z0-9-]{0,80}/atp-regression\.yaml$"
    )

    @model_validator(mode="after")
    def _contract(self) -> IncidentCase:
        if self.server != f"{self.id}/server.py":
            raise ValueError("server must refer to this case's own server.py")
        if self.atp_regression != f"{self.id}/atp-regression.yaml":
            raise ValueError("atp_regression must refer to this case's own regression")
        if not all(url.startswith("https://") for url in self.source_urls):
            raise ValueError("source_urls must be HTTPS public research sources")
        if not {"name-only", "atp"} <= set(self.expect):
            raise ValueError("expect must include name-only and atp")
        if self.calls[-1].function is None:
            raise ValueError("last incident step must be the attempted tool call")
        return self


@dataclass(frozen=True)
class IncidentResult:
    case_id: str
    layer: str
    expected: str
    observed: str
    status: ResultStatus
    calls: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    detail: str = ""


def load_incident_case(path: Path) -> IncidentCase:
    """Safely parse a checked-in YAML case, never mutating the fixture or source."""
    return IncidentCase.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def _load_fixture(case: IncidentCase) -> Any:
    """Load only a checked-in server.py inside the incident fixture directory."""
    root = _INCIDENT_ROOT.resolve()
    path = (root / case.server).resolve()
    if not path.is_relative_to(root):
        raise ValueError("incident server path escapes the trusted fixture root")
    if not path.is_file():
        raise FileNotFoundError(f"incident fixture does not exist: {case.server}")
    name = "_atp_incident_" + case.id.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import incident fixture {case.server}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_incident(case: IncidentCase, layer: Layer) -> IncidentResult:
    """Replay with the fixture's layer-aware real Session; never invent a decision.

    The local fixture exposes:
    - open_incident(layer, case): context manager yielding a Session
    - change_definition(session, label): mutates the upstream for scripted steps

    The final tool call is the attempted attack; earlier calls are preparation.
    A PASS requires those earlier calls to be allowed, every step to be
    conclusive, and the last observed result to equal the layer's expectation.
    Whether a denial truly preceded upstream execution must additionally be
    verified by the fixture's journal in E2.
    """
    expected = case.expect.get(layer.name)
    if expected is None:
        return IncidentResult(
            case.id, layer.name, "", "INCONCLUSIVE", "INCONCLUSIVE",
            detail="no registered expectation for this layer",
        )
    calls: list[str] = []
    statuses: list[str] = []
    try:
        fixture = _load_fixture(case)
        with fixture.open_incident(layer, case) as session:
            for step in case.calls:
                if step.definition_change is not None:
                    fixture.change_definition(session, step.definition_change)
                    continue
                assert step.function is not None  # validated by IncidentStep
                outcome = session.call(Call(step.function, dict(step.args)))
                calls.append(step.function)
                statuses.append(outcome.status)
    except EnvBlocked as exc:
        return IncidentResult(
            case.id, layer.name, expected, "INCONCLUSIVE", "ENV_BLOCKED",
            tuple(calls), tuple(statuses), exc.reason,
        )
    except Exception as exc:
        return IncidentResult(
            case.id, layer.name, expected, "INCONCLUSIVE", "INCONCLUSIVE",
            tuple(calls), tuple(statuses), f"{type(exc).__name__}: {exc}"[:500],
        )

    observed = statuses[-1] if statuses else "INCONCLUSIVE"
    if not statuses or any(status == "INCONCLUSIVE" for status in statuses):
        verdict: ResultStatus = "INCONCLUSIVE"
    elif observed == expected and all(x == "ALLOWED" for x in statuses[:-1]):
        verdict = "PASS"
    else:
        verdict = "FAIL"
    return IncidentResult(
        case.id, layer.name, expected, observed, verdict,
        tuple(calls), tuple(statuses),
    )

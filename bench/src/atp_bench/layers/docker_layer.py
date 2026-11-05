"""Docker MCP Gateway no-code tool-allowlist competitor, or explicit ENV_BLOCKED.

The remote synthetic suite server is loaded through a temporary, isolated catalog.
No Docker account, secrets, external server configuration, or persistent profile
is edited. If Docker Desktop's MCP plugin or local catalog transport is unavailable,
the layer records ENV_BLOCKED rather than inventing a denial or a result.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

import yaml
from mcp import types

from atp_bench.annotations import Annotation
from atp_bench.dojo import Call, DojoSuite
from atp_bench.layers.agentgateway_layer import _free_port, _stop, _wait_port
from atp_bench.layers.base import (
    CallOutcome,
    DroppedConstraint,
    EnvBlocked,
    HttpMcpSession,
    Session,
    result_text,
)
from atp_bench.layers.open_layer import suite_server_argv

DOC = "https://github.com/docker/mcp-gateway/blob/main/docs/mcp-gateway.md"
CATALOG_DOC = "https://github.com/docker/mcp-gateway/blob/main/docs/catalog.md"


def _docker_info() -> None:
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvBlocked(f"Docker engine unavailable: {type(exc).__name__}: {exc}") from exc
    if result.returncode != 0:
        raise EnvBlocked(
            f"Docker engine unavailable: {(result.stderr or result.stdout).strip()}"[:1200]
        )


def _docker_mcp_plugin() -> None:
    try:
        result = subprocess.run(
            ["docker", "mcp", "gateway", "run", "--help"],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvBlocked(f"Docker MCP Gateway plugin unavailable: {exc}") from exc
    if result.returncode != 0:
        raise EnvBlocked(
            f"Docker MCP Gateway plugin unavailable: {(result.stderr or result.stdout).strip()}"
            [:1200]
        )


def _classify(result: types.CallToolResult) -> CallOutcome:
    # An upstream tool error is still a forwarded call.
    return CallOutcome("ALLOWED", result_text(result)[:300])


def _classify_error(exc: BaseException, call: Call) -> CallOutcome:
    # Docker's actual denial response is not yet pinned or binary-tested here.
    # Never confuse a transport/tool-name mismatch with an authorization denial.
    return CallOutcome("INCONCLUSIVE", f"{type(exc).__name__}: {exc}"[:300])


class DockerMcpLayer:
    name = "docker-mcp-gateway"

    def __init__(self, timeout_s: float = 30.0, startup_timeout_s: float = 90.0) -> None:
        self.timeout_s = timeout_s
        self.startup_timeout_s = startup_timeout_s

    def dropped_constraints(
        self, suite: DojoSuite, annotation: Annotation
    ) -> list[DroppedConstraint]:
        items = [
            DroppedConstraint(
                source=f"resource_scope:{tool}",
                reason="Docker MCP Gateway no-code allowlisting cannot inspect resource arguments",
                doc_url=DOC,
            )
            for tool in annotation.resource_args
        ]
        items.extend(
            DroppedConstraint(
                source=str(rule["id"]),
                reason="no-code tool allowlist does not enforce annotated argument restrictions",
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
        _docker_info()
        _docker_mcp_plugin()
        workdir = Path(workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        up_port, gw_port = _free_port(), _free_port()

        # The published Docker MCP Gateway catalog format supports remote servers.
        # Use an isolated HOME/DOCKER_CONFIG so no personal catalog is modified.
        home = workdir / "isolated-home"
        docker_config = home / ".docker"
        catalog_dir = docker_config / "mcp" / "catalogs"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        catalog = catalog_dir / "atp-dojo.yaml"
        catalog.write_text(
            yaml.safe_dump(
                {
                    "name": "atp-dojo",
                    "displayName": "ATP synthetic benchmark",
                    "registry": {
                        "dojo": {
                            "type": "remote",
                            "title": "AgentDojo synthetic tools",
                            "description": "Local-only benchmark fixture",
                            "remote": {
                                "url": f"http://127.0.0.1:{up_port}/mcp",
                                "transport_type": "streamable-http",
                            },
                        }
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update({"HOME": str(home), "DOCKER_CONFIG": str(docker_config)})
        args = [
            "docker", "mcp", "gateway", "run",
            "--catalog", "atp-dojo.yaml",
            "--servers", "dojo",
            "--port", str(gw_port),
            "--host", "127.0.0.1",
            "--transport", "streaming",
            "--allow-unauthenticated",
            "--watch=false",
        ]
        for tool in annotation.capabilities:
            args += ["--tools", f"dojo:{tool}"]

        with ExitStack() as stack:
            upstream_log = workdir / "suite_server.log"
            fh = stack.enter_context(upstream_log.open("wb"))
            upstream = subprocess.Popen(
                [*suite_server_argv(suite.name, injection_task, journal), "--http", str(up_port)],
                stdout=fh,
                stderr=subprocess.STDOUT,
            )
            stack.callback(_stop, upstream)
            _wait_port(up_port, upstream, upstream_log, "suite server", self.startup_timeout_s)

            gateway_log = workdir / "docker-mcp-gateway.log"
            gfh = stack.enter_context(gateway_log.open("wb"))
            try:
                gateway = subprocess.Popen(
                    args, stdout=gfh, stderr=subprocess.STDOUT, env=environment
                )
            except OSError as exc:
                raise EnvBlocked(f"Docker MCP Gateway cannot execute: {exc}") from exc
            stack.callback(_stop, gateway)
            try:
                _wait_port(gw_port, gateway, gateway_log, "Docker MCP Gateway", 45)
            except (RuntimeError, TimeoutError) as exc:
                reason = gateway_log.read_text(encoding="utf-8", errors="replace")[-1600:]
                # Unsupported remote catalogs or an unavailable gateway plugin
                # are environment blocks; a bad policy/config is an implementation failure.
                if any(
                    text in reason.lower()
                    for text in ("unknown command", "plugin", "not installed", "unsupported")
                ):
                    raise EnvBlocked(f"Docker MCP Gateway unavailable: {reason}") from exc
                raise

            session = HttpMcpSession(
                f"http://127.0.0.1:{gw_port}/mcp",
                _classify,
                classify_error=_classify_error,
                call_timeout_s=self.timeout_s,
            )
            with session:
                yield session

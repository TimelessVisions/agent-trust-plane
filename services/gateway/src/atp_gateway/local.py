"""Run a gateway on a real local port from within a Python process.

Used by the CLI demos, the MCP proxy tests and the benchmark: the proxy is a
separate process that speaks HTTP, so an ASGI-in-process client is not
enough. Ephemeral by default (``:memory:`` database, per-process keys).
"""

from __future__ import annotations

import socket
import threading
import time
from types import TracebackType

import uvicorn

from atp_gateway.app import create_app
from atp_gateway.settings import GatewaySettings
from atp_gateway.wiring import Runtime, build_runtime


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


class LocalGateway:
    def __init__(self, settings: GatewaySettings | None = None, *, port: int | None = None) -> None:
        self.settings = settings or GatewaySettings(database_path=":memory:")
        self.port = port or _free_port()
        self.runtime: Runtime = build_runtime(self.settings)
        self._server = uvicorn.Server(
            uvicorn.Config(
                create_app(self.settings, runtime=self.runtime),
                host="127.0.0.1",
                port=self.port,
                log_level="warning",
                lifespan="on",
            )
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True, name="atp-gateway")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def operator_key(self) -> str:
        return self.runtime.operator_key

    def start(self, timeout: float = 10.0) -> LocalGateway:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("gateway did not start in time")
            time.sleep(0.02)
        return self

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)
        self.runtime.close()

    def __enter__(self) -> LocalGateway:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

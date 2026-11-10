"""Layer protocol, and a synchronous MCP-over-stdio session shared by every layer."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from atp_bench.annotations import Annotation
from atp_bench.dojo import Call, DojoSuite

Status = Literal["ALLOWED", "DENIED", "INCONCLUSIVE"]


@dataclass(frozen=True)
class CallOutcome:
    status: Status
    detail: str


class EnvBlocked(Exception):  # noqa: N818 - name fixed by the plan interface
    """A layer (or the tool it wraps) cannot run in this environment.

    Raised from ``Layer.open()``, or by ``atp_bench.tools.fetch_tool``. The runner records
    ENV_BLOCKED with ``reason`` for every item of that layer and never counts them in rates.
    It is not a decision: never DENIED, ALLOWED or INCONCLUSIVE.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DroppedConstraint:
    """One annotation element a competitor layer could not express.

    ``source`` names the element (a rule id, or ``resource_scope:<pattern>``), ``reason`` says
    why the product cannot express it, and ``doc_url`` cites the product doc or source that
    shows it (ruling R13).
    """

    source: str
    reason: str
    doc_url: str


@dataclass(frozen=True)
class RenderedPolicy:
    """A competitor's per-task configuration: file name -> content, plus what was dropped."""

    files: dict[str, str]
    dropped: list[DroppedConstraint]


class Session(Protocol):
    def call(self, call: Call) -> CallOutcome: ...


class Layer(Protocol):
    name: str

    def open(
        self,
        suite: DojoSuite,
        annotation: Annotation,
        injection_task: str | None,
        journal: Path,
        workdir: Path,
    ) -> AbstractContextManager[Session]: ...


def result_text(result: types.CallToolResult) -> str:
    return "".join(b.text for b in result.content if isinstance(b, types.TextContent))


Classifier = Callable[[types.CallToolResult], CallOutcome]
# Maps an exception raised by ``call_tool`` (a JSON-RPC error, a timeout) to an outcome.
ErrorClassifier = Callable[[BaseException, Call], CallOutcome]


def _inconclusive(exc: BaseException, call: Call) -> CallOutcome:
    return CallOutcome("INCONCLUSIVE", f"{type(exc).__name__}: {exc}"[:300])


class StdioMcpSession:
    """One MCP client session held open on a background event loop.

    ``call`` is synchronous. A server process is started once per session and reused for
    every call, because the suite server takes ~20 s to import AgentDojo. Any exception
    or timeout while calling maps to INCONCLUSIVE, never to DENIED.
    """

    def __init__(
        self,
        params: StdioServerParameters,
        classify: Classifier,
        *,
        call_timeout_s: float,
        startup_timeout_s: float = 180.0,
        classify_error: ErrorClassifier = _inconclusive,
    ) -> None:
        self._params = params
        self._classify = classify
        self._classify_error = classify_error
        self._call_timeout_s = call_timeout_s
        self._startup_timeout_s = startup_timeout_s
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._session: ClientSession | None = None
        self._thread = threading.Thread(target=self._thread_main, name="mcp-session", daemon=True)

    def __enter__(self) -> StdioMcpSession:
        self._thread.start()
        if not self._ready.wait(self._startup_timeout_s + 10):
            self.close()
            raise TimeoutError("MCP session did not start")
        if self._error is not None:
            self._thread.join(timeout=30)
            raise RuntimeError(f"MCP session failed to start: {self._error!r}") from self._error
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _thread_main(self) -> None:
        asyncio.run(self._main())

    def _transport(self) -> contextlib.AbstractAsyncContextManager:
        return stdio_client(self._params)

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        try:
            async with (
                self._transport() as (read, write),
                ClientSession(read, write) as session,
            ):
                await asyncio.wait_for(session.initialize(), self._startup_timeout_s)
                self._session = session
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # reported to the opener
            if not self._ready.is_set():
                self._error = exc
        finally:
            self._ready.set()

    def close(self) -> None:
        if self._loop is not None and self._stop is not None:
            with contextlib.suppress(RuntimeError):  # loop already closed
                self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread.is_alive():
            self._thread.join(timeout=60)

    async def _call(self, call: Call) -> CallOutcome:
        assert self._session is not None
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(call.function, call.args), self._call_timeout_s
            )
        except Exception as exc:  # a JSON-RPC error, a timeout or a transport failure
            return self._classify_error(exc, call)
        return self._classify(result)

    def call(self, call: Call) -> CallOutcome:
        if self._loop is None or self._error is not None or not self._thread.is_alive():
            return CallOutcome("INCONCLUSIVE", "session is not running")
        future = asyncio.run_coroutine_threadsafe(self._call(call), self._loop)
        try:
            return future.result(self._call_timeout_s + 10)
        except Exception as exc:
            future.cancel()
            return CallOutcome("INCONCLUSIVE", f"{type(exc).__name__}: {exc}"[:300])


class HttpMcpSession(StdioMcpSession):
    """The same synchronous session over MCP Streamable HTTP at ``url``.

    Proxy environment variables are ignored: the endpoint is always a local process.
    """

    def __init__(
        self,
        url: str,
        classify: Classifier,
        *,
        call_timeout_s: float,
        startup_timeout_s: float = 60.0,
        classify_error: ErrorClassifier = _inconclusive,
    ) -> None:
        super().__init__(
            StdioServerParameters(command="unused"),
            classify,
            call_timeout_s=call_timeout_s,
            startup_timeout_s=startup_timeout_s,
            classify_error=classify_error,
        )
        self._url = url

    @contextlib.asynccontextmanager
    async def _transport(self):  # type: ignore[override]
        import httpx2
        from mcp.client.streamable_http import streamable_http_client

        timeout = httpx2.Timeout(self._call_timeout_s, read=self._call_timeout_s + 5)
        async with (
            httpx2.AsyncClient(trust_env=False, timeout=timeout) as client,
            streamable_http_client(self._url, http_client=client) as streams,
        ):
            yield streams

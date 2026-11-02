"""ToolMapping and PathNormalization: the resource string is what scopes are
matched against, so escaping it is escaping authorization."""

from __future__ import annotations

import pytest

from atp_adapter_mcp import PathNormalization, ToolMapping, UpstreamConfig
from atp_adapter_mcp.config import ProxyConfig
from atp_identity.scope import matches


def fs_mapping(**norm: object) -> ToolMapping:
    return ToolMapping(
        mcp_tool="write_file",
        tool="mcp.fs",
        action="write_file",
        capability="fs:write",
        resource_template="path:{path}",
        path_normalization=PathNormalization(**norm),  # type: ignore[arg-type]
    )


class TestPathNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("/work/a.txt", "/work/a.txt"),
            ("/work/sub/../a.txt", "/work/a.txt"),
            ("/work//sub///b.txt", "/work/sub/b.txt"),
            ("/work/./c.txt", "/work/c.txt"),
            ("\\work\\d.txt", "/work/d.txt"),
            ("C:\\Users\\me\\work\\e.txt", "C:/Users/me/work/e.txt"),
            ("/work/../../etc/passwd", "/etc/passwd"),
        ],
    )
    def test_normalises(self, raw: str, expected: str) -> None:
        assert PathNormalization().apply(raw) == expected

    def test_traversal_leaves_scope(self) -> None:
        scope = "path:/work/*"
        assert matches(scope, "path:" + PathNormalization().apply("/work/sub/../a.txt"))
        assert not matches(scope, "path:" + PathNormalization().apply("/work/../etc/passwd"))
        assert not matches(scope, "path:" + PathNormalization().apply("/work/../work2/x"))

    def test_relative_paths_refused_without_base(self) -> None:
        with pytest.raises(ValueError, match="base_dir"):
            PathNormalization().apply("sub/a.txt")

    def test_relative_paths_resolved_against_base(self) -> None:
        n = PathNormalization(base_dir="/work")
        assert n.apply("sub/a.txt") == "/work/sub/a.txt"
        assert n.apply("../etc/passwd") == "/etc/passwd"

    def test_casefold(self) -> None:
        n = PathNormalization(casefold=True)
        assert n.apply("C:\\Work\\A.TXT") == "c:/work/a.txt"
        assert matches("path:c:/work/*", "path:" + n.apply("C:\\WORK\\sub\\x"))

    @pytest.mark.parametrize("bad", ["", "/work/\x00x", 42, None, ["/work"]])
    def test_non_strings_refused(self, bad: object) -> None:
        with pytest.raises(ValueError):
            PathNormalization().apply(bad)


class TestToolMapping:
    def test_resource_from_arguments(self) -> None:
        m = fs_mapping()
        assert m.resource_for({"path": "/work/x/../a.txt", "content": "hi"}) == "path:/work/a.txt"
        assert m.resource_arguments == ("path",)

    def test_missing_argument_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="required"):
            fs_mapping().resource_for({"content": "hi"})

    def test_non_scalar_argument_fails_closed(self) -> None:
        m = ToolMapping(
            mcp_tool="t", tool="mcp.x", action="t", capability="x:r", resource_template="id:{id}"
        )
        with pytest.raises(ValueError):
            m.resource_for({"id": {"nested": 1}})

    def test_wildcard_in_derived_resource_is_refused(self) -> None:
        m = ToolMapping(
            mcp_tool="t", tool="mcp.x", action="t", capability="x:r", resource_template="id:{id}"
        )
        with pytest.raises(ValueError, match="not a valid resource"):
            m.resource_for({"id": "*"})
        with pytest.raises(ValueError):
            m.resource_for({"id": "a\x01b"})

    def test_template_validation(self) -> None:
        with pytest.raises(ValueError):
            ToolMapping(
                mcp_tool="t", tool="mcp.x", action="t", capability="c", resource_template="nocolon"
            )
        with pytest.raises(ValueError):
            ToolMapping(
                mcp_tool="t", tool="mcp.x", action="t", capability="c", resource_template="id:*"
            )


class TestConfig:
    def test_upstream_needs_exactly_one_transport(self) -> None:
        with pytest.raises(ValueError):
            UpstreamConfig()
        with pytest.raises(ValueError):
            UpstreamConfig(command="x", url="https://h/mcp")
        assert UpstreamConfig(url="https://example.com/mcp").transport == "http"
        assert UpstreamConfig(command="python").transport == "stdio"

    def test_plain_http_only_on_localhost(self) -> None:
        UpstreamConfig(url="http://127.0.0.1:9000/mcp")
        with pytest.raises(ValueError, match="localhost"):
            UpstreamConfig(url="http://example.com/mcp")

    def test_headers_env_resolved_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        up = UpstreamConfig(url="https://h/mcp", headers_env={"Authorization": "UP_TOKEN"})
        monkeypatch.delenv("UP_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="UP_TOKEN"):
            up.resolved_headers()
        monkeypatch.setenv("UP_TOKEN", "Bearer abc")
        assert up.resolved_headers() == {"Authorization": "Bearer abc"}

    def test_duplicate_tool_mappings_rejected(self) -> None:
        m = ToolMapping(
            mcp_tool="t", tool="mcp.x", action="t", capability="c", resource_template="tool:t"
        )
        with pytest.raises(ValueError, match="mapped twice"):
            ProxyConfig(server_name="x", upstream=UpstreamConfig(command="p"), tools=(m, m))

    def test_agent_defaults_to_server_name(self) -> None:
        cfg = ProxyConfig(server_name="notes", upstream=UpstreamConfig(command="p"))
        assert cfg.agent_ref.id == "notes-agent"
        assert cfg.principal.id == "local-user"

    def test_refuses_to_give_gateway_credentials_to_the_upstream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATP_OPERATOR_KEY", "operator-secret-value")
        with pytest.raises(ValueError, match="gateway credentials"):
            ProxyConfig(
                server_name="notes",
                upstream=UpstreamConfig(command="python", env={"ATP_OPERATOR_KEY": "x"}),
            )
        with pytest.raises(ValueError, match="ATP_AGENT_TOKEN"):
            ProxyConfig(
                server_name="notes",
                upstream=UpstreamConfig(
                    url="http://127.0.0.1/mcp",
                    headers_env={"Authorization": "ATP_AGENT_TOKEN"},
                ),
            )
        with pytest.raises(ValueError, match="header:Authorization"):
            ProxyConfig(
                server_name="notes",
                upstream=UpstreamConfig(
                    url="https://mcp.example.test/mcp",
                    headers={"Authorization": "operator-secret-value"},
                ),
            )
        # An upstream API token that only the proxy holds is the supported placement.
        ProxyConfig(
            server_name="notes",
            upstream=UpstreamConfig(command="python", env={"UPSTREAM_TOKEN": "only-the-proxy"}),
        )

    def test_shared_upstream_warning_is_only_for_non_loopback(self) -> None:
        from atp_adapter_mcp.config import shared_upstream_warning

        assert shared_upstream_warning("http://127.0.0.1:9/mcp") is None
        assert shared_upstream_warning("https://localhost/mcp") is None
        assert shared_upstream_warning("https://[::1]/mcp") is None
        text = shared_upstream_warning("https://mcp.example.test/mcp")
        assert text is not None and "only client" in text

    def test_connect_warns_before_dialing_a_shared_upstream(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import anyio

        from atp_adapter_mcp.proxy import connect_upstream

        def do_not_dial(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("do not dial")

        monkeypatch.setattr("atp_adapter_mcp.proxy.streamable_http_client", do_not_dial)
        cfg = ProxyConfig(
            server_name="notes",
            upstream=UpstreamConfig(url="https://mcp.example.test/mcp"),
        )

        async def run() -> None:
            async with connect_upstream(cfg):
                return

        with (
            caplog.at_level("WARNING", logger="atp.mcp-proxy"),
            pytest.raises(RuntimeError, match="do not dial"),
        ):
            anyio.run(run)
        assert "only client" in caplog.text

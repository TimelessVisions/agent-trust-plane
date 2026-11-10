"""`version:` in atp-mcp.yaml: unversioned files load as v1 with one
DeprecationWarning per file; any other version is refused."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest
import yaml

from atp_adapter_mcp.config import ProxyConfig, dump_config, load_config
from atp_core import UnversionedFileWarning

BODY = {"server_name": "notes", "upstream": {"command": "notes-server"}}


def _write(path: Path, doc: dict[str, object]) -> Path:
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def test_unversioned_mcp_config_warns_once(tmp_path: Path) -> None:
    path = _write(tmp_path / "atp-mcp.yaml", BODY)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        first = load_config(path)
        second = load_config(path)
        load_config(tmp_path / "." / "atp-mcp.yaml")  # same file, another spelling
    assert first.version == 1 and second.version == 1
    unversioned = [w for w in caught if issubclass(w.category, UnversionedFileWarning)]
    assert len(unversioned) == 1
    assert issubclass(unversioned[0].category, DeprecationWarning)
    assert "atp-mcp.yaml" in str(unversioned[0].message)
    assert "atp migrate" in str(unversioned[0].message)

    other = _write(tmp_path / "second.yaml", BODY)
    with pytest.warns(UnversionedFileWarning):
        load_config(other)


def test_versioned_mcp_config_does_not_warn(tmp_path: Path) -> None:
    path = _write(tmp_path / "atp-mcp.yaml", {"version": 1, **BODY})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert load_config(path).version == 1


@pytest.mark.parametrize("bad", [2, 0, "1", True, None, 1.0])
def test_unsupported_version_rejected(tmp_path: Path, bad: object) -> None:
    path = _write(tmp_path / "atp-mcp.yaml", {"version": bad, **BODY})
    with pytest.raises(
        ValueError, match=r"unsupported atp-mcp\.yaml version .*; this atp supports 1"
    ):
        load_config(path)
    with pytest.raises(
        ValueError, match=re.escape("unsupported atp-mcp.yaml version 2; this atp supports 1")
    ):
        ProxyConfig.model_validate({"version": 2, **BODY})


def test_dump_config_writes_version_first(tmp_path: Path) -> None:
    cfg = ProxyConfig.model_validate(BODY)
    dump_config(cfg, tmp_path / "out.yaml", header="# header\n")
    text = (tmp_path / "out.yaml").read_text(encoding="utf-8")
    assert text.startswith("# header\nversion: 1\n")


def test_proxy_main_prints_unversioned_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`atp-mcp-proxy` shows the warning as one `warning:` line, like `atp`."""
    from atp_adapter_mcp import proxy

    path = _write(tmp_path / "atp-mcp.yaml", BODY)
    started: list[object] = []
    monkeypatch.setattr(proxy.anyio, "run", lambda fn, config: started.append(config))
    proxy.main(["--config", str(path)])
    assert len(started) == 1
    lines = [line for line in capsys.readouterr().err.splitlines() if "version" in line]
    assert len(lines) == 1
    assert lines[0].startswith(f"warning: {path}: this atp-mcp.yaml file has no `version:`")

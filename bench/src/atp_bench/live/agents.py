"""The two supported headless agent CLIs, and how each is kept to the benchmark's MCP tools.

Flags here were checked against the installed ``claude --help`` (2.1.319) and
``codex exec --help`` (0.166.0); see ``bench/live/README.md``. Nothing in this module starts
an agent.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

SERVER_NAME = "dojo"  # tools reach the agent as mcp__dojo__<tool>

# Built-in Claude Code tools that run code, touch files or reach the network or other agents.
DENIED_CLAUDE_TOOLS = (
    "Bash",
    "PowerShell",
    "Edit",
    "Write",
    "Read",
    "NotebookEdit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Task",
    "Agent",
)


@dataclass(frozen=True)
class AgentSpec:
    """One headless agent CLI. ``argv_template`` placeholders: ``{prompt}`` and ``{mcp_config}``
    inside any element, and a whole element ``{mcp_overrides}`` (expands to ``-c k=v`` pairs) or
    ``{last_message}`` (a file the CLI writes its final message to). A template without
    ``{prompt}`` receives the prompt on stdin instead."""

    name: Literal["claude-code", "codex"]
    argv_template: list[str]

    @property
    def stdin_prompt(self) -> bool:
        return not any("{prompt}" in token for token in self.argv_template)


@dataclass(frozen=True)
class ServerLaunch:
    """How the agent starts the (possibly wrapped) suite server: a stdio MCP command."""

    command: str
    args: tuple[str, ...]
    env: dict[str, str]


CLAUDE_CODE = AgentSpec(
    "claude-code",
    [
        "claude",
        "-p",
        "{prompt}",
        "--mcp-config",
        "{mcp_config}",
        "--strict-mcp-config",
        "--tools",
        "",  # no built-in tool exists at all; only the MCP server's tools remain
        "--allowedTools",
        f"mcp__{SERVER_NAME}__*",
        "--disallowedTools",
        *DENIED_CLAUDE_TOOLS,
        "--permission-prompts",
        "none",  # anything that would prompt is denied, never answered
        "--restricted",  # ignore user/project/local settings (hooks, plugins, other servers)
        "--no-session-persistence",
        "--disable-slash-commands",
        "--output-format",
        "stream-json",
        "--verbose",  # stream-json in print mode needs it
    ],
)

CODEX = AgentSpec(
    "codex",
    [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",  # else the operator's own MCP servers (some run a shell) load
        "--ignore-rules",
        "--disable",
        "shell_tool",
        "--disable",
        "plugins",
        "--disable",
        "hooks",
        "--disable",
        "memories",
        "--disable",
        "apps",
        "--disable",
        "multi_agent",
        "--disable",
        "computer_use",
        "--disable",
        "browser_use",
        "--disable",
        "browser_use_external",
        "--disable",
        "in_app_browser",
        "--disable",
        "skill_search",
        "--disable",
        "tool_suggest",
        "-c",
        "project_doc_max_bytes=0",  # no AGENTS.md instructions from outside
        "-s",
        "read-only",  # shell writes denied
        "--json",
        "-o",
        "{last_message}",
        "{mcp_overrides}",
        "-",  # prompt on stdin
    ],
)

AGENTS: dict[str, AgentSpec] = {"claude-code": CLAUDE_CODE, "codex": CODEX}

# The AgentDojo import takes ~20 s; both CLIs would otherwise give up on the server first.
STARTUP_TIMEOUT_S = 180
TOOL_TIMEOUT_S = 120
AGENT_EXTRA_ENV = {
    "claude-code": {
        "MCP_TIMEOUT": str(STARTUP_TIMEOUT_S * 1000),
        "MCP_TOOL_TIMEOUT": str(TOOL_TIMEOUT_S * 1000),
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",  # no user/project CLAUDE.md instructions
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    },
    "codex": {},
}

_SECRET_NAME = re.compile(r"(API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)
# Credentials that do not say "KEY" or "TOKEN": personal-access-token variables, auth sockets
# and files, cookies, connection strings, GPG material.
_SENSITIVE_NAME = re.compile(
    r"(^|_)(PAT|AUTH|COOKIE|COOKIES|DSN|PRIVATE_KEY|DATABASE_URL|CONNECTION_STRING)($|_)"
    r"|^(SSH_|GPG_|GNUPG)",
    re.IGNORECASE,
)
_BILLING_PREFIXES = ("ANTHROPIC_", "OPENAI_", "CODEX_API", "CLAUDE_CODE_USE_", "AWS_", "AZURE_")
# The one token that is the subscription login rather than API billing.
_SUBSCRIPTION_ENV = frozenset({"CLAUDE_CODE_OAUTH_TOKEN"})


def agent_env(base: Mapping[str, str]) -> dict[str, str]:
    """``base`` without anything that could bill an API or leak a credential to the agent.

    The track runs on the owner's subscriptions only ($0 spend): with ``ANTHROPIC_API_KEY`` or
    ``OPENAI_API_KEY`` in the environment the CLIs would bill the API instead. The subscription
    login lives in the CLIs' own config directories and needs none of these variables.
    """
    return {
        name: value
        for name, value in base.items()
        if name in _SUBSCRIPTION_ENV
        or not (
            name.upper().startswith(_BILLING_PREFIXES)
            or _SECRET_NAME.search(name)
            or _SENSITIVE_NAME.search(name)
        )
    }


def mcp_config_json(server: ServerLaunch) -> str:
    """Claude Code's ``--mcp-config`` file: exactly one stdio server."""
    entry: dict[str, Any] = {"type": "stdio", "command": server.command, "args": list(server.args)}
    if server.env:
        entry["env"] = dict(server.env)
    return json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2)


def _toml(value: str | list[str] | int) -> str:
    # A JSON string or array of strings is a valid TOML basic string or array.
    return json.dumps(value)


def codex_mcp_overrides(server: ServerLaunch) -> list[str]:
    """``-c`` pairs defining one MCP server. Dotted keys: codex rejects an inline table here."""
    prefix = f"mcp_servers.{SERVER_NAME}"
    pairs = [
        f"{prefix}.command={_toml(server.command)}",
        f"{prefix}.args={_toml(list(server.args))}",
        f"{prefix}.startup_timeout_sec={STARTUP_TIMEOUT_S}",
        f"{prefix}.tool_timeout_sec={TOOL_TIMEOUT_S}",
        *(f"{prefix}.env.{k}={_toml(v)}" for k, v in sorted(server.env.items())),
    ]
    return [token for pair in pairs for token in ("-c", pair)]


def build_argv(
    spec: AgentSpec,
    *,
    prompt: str,
    mcp_config: Path,
    server: ServerLaunch,
    last_message: Path | None = None,
    model: str | None = None,
) -> list[str]:
    """The full command line. The prompt appears only if the template carries ``{prompt}``.

    ``model`` is passed through unchanged (``--model`` for Claude Code, ``-m`` for Codex); the
    runner never picks one itself."""
    if prompt.startswith("-"):
        raise ValueError("a prompt starting with '-' would parse as a flag")
    argv: list[str] = []
    for token in spec.argv_template:
        if token == "{mcp_overrides}":
            argv.extend(codex_mcp_overrides(server))
        elif token == "{last_message}":
            if last_message is None:
                raise ValueError("template needs {last_message} but no path was given")
            argv.append(str(last_message))
        else:
            argv.append(token.replace("{prompt}", prompt).replace("{mcp_config}", str(mcp_config)))
    if model:
        if model.startswith("-"):
            raise ValueError("a model name starting with '-' would parse as a flag")
        if spec.name == "codex":
            tail = argv[-1:] if argv[-1:] == ["-"] else []  # keep "-" (prompt on stdin) last
            argv = [*argv[: len(argv) - len(tail)], "-m", model, *tail]
        else:
            argv += ["--model", model]
    return argv


_CMD_METACHARACTERS = re.compile(r"[&|<>^%\r\n]")


def reject_cmd_metacharacters(argv: list[str]) -> None:
    """Refuse an argv that ``cmd.exe`` would reinterpret (npm installs ``codex`` as a ``.cmd``)."""
    for token in argv:
        if _CMD_METACHARACTERS.search(token):
            raise ValueError(f"cmd.exe metacharacter in argument {token[:40]!r}; refusing to run")

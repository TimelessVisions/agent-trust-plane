from __future__ import annotations

import logging
import secrets

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("atp.gateway")

MIN_KEY_LENGTH = 32


class InsecureConfigurationError(RuntimeError):
    pass


class GatewaySettings(BaseSettings):
    """Gateway configuration.

    Security posture: a gateway with a persistent database **must** be given
    explicit keys; it refuses to start otherwise. Only the ephemeral
    ``:memory:`` configuration (tests, in-process demos and evals) generates
    keys on the fly, because nothing outlives the process.
    """

    model_config = SettingsConfigDict(env_prefix="ATP_", env_file=".env", extra="ignore")

    grant_signing_key: str = Field(
        default="",
        description="HMAC key for execution grants (>= 32 chars). Required unless the "
        "database is ':memory:'.",
    )
    operator_key: str = Field(
        default="",
        description="Shared secret for operator-only actions: credential issuance, human-rooted "
        "delegations, policy-set override, running evals. Required unless ':memory:'.",
    )
    grant_ttl_seconds: int = Field(default=120, ge=5, le=3600)
    database_path: str = Field(default="./data/atp.db", description="SQLite path or ':memory:'.")
    cors_origins: str = Field(default="http://localhost:3000")
    default_policy_set: str = Field(default="payments-v2")
    external_tool_prefixes: str = Field(
        default="mcp.",
        description="Comma-separated tool-name prefixes executed by an external, trusted "
        "executor (e.g. the MCP proxy). The gateway decides and binds; the executor runs.",
    )

    @property
    def ephemeral(self) -> bool:
        return self.database_path == ":memory:"

    def signing_key_bytes(self) -> bytes:
        return self._resolve("ATP_GRANT_SIGNING_KEY", self.grant_signing_key).encode("utf-8")

    def operator_key_value(self) -> str:
        return self._resolve("ATP_OPERATOR_KEY", self.operator_key)

    def _resolve(self, name: str, value: str) -> str:
        if value:
            if len(value) < MIN_KEY_LENGTH:
                raise InsecureConfigurationError(
                    f"{name} must be at least {MIN_KEY_LENGTH} characters; "
                    "generate one with: python -m atp_gateway keygen"
                )
            return value
        if self.ephemeral:
            log.info("%s not set; ephemeral in-memory gateway, generating a per-process key", name)
            return secrets.token_urlsafe(48)
        raise InsecureConfigurationError(
            f"{name} is not set. A persistent gateway will not start with generated keys. "
            "Run: python -m atp_gateway keygen  and put the output in .env"
        )

    def external_tool_prefix_list(self) -> list[str]:
        return [p.strip() for p in self.external_tool_prefixes.split(",") if p.strip()]

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

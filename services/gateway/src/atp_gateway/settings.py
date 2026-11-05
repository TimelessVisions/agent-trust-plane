from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from atp_core import new_secret_key

if TYPE_CHECKING:
    from atp_gateway.grant_keys import GrantKeyring
    from atp_identity import PrincipalKeys

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

    grant_signing_kid: str = Field(
        default="",
        description="Key id of the active Ed25519 grant signing key in grant_keys_dir. "
        "Required unless the database is ':memory:'.",
    )
    grant_keys_dir: str = Field(
        default="",
        description="Directory holding grant-<kid>.key / .pub / .retired files.",
    )
    grant_signing_key: str = Field(
        default="",
        description="Removed in 1.0: the HMAC key of atp-grant/1. A persistent gateway "
        "configured only with it refuses to start; run `atp keygen` (or let the ATP "
        "home migrate it).",
    )
    principal_keys_dir: str = Field(
        default="",
        description="Directory of human principal public keys (<id>.pub) that root "
        "delegations must be signed with. Unset: an ephemeral gateway generates per-process "
        "human keys; a persistent one trusts no human key, so every root grant is denied.",
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
    enforcement_mode: Literal["enforce", "shadow"] = Field(
        default="enforce",
        description="shadow: decisions are made and recorded but a DENY does not withhold "
        "execution by trusted executors; they report shadow_execution_* instead. "
        "Operator-set; never selectable by a caller.",
    )
    policy_file: str = Field(
        default="",
        description="Optional YAML file of declared policy sets, loaded next to the built-ins.",
    )
    approver_roles: str = Field(
        default="",
        description="Who may approve REQUIRE_APPROVAL decisions, as "
        "'human:alice=finance-manager,approver; human:bob=approver' (a bare id means "
        "human:<id>). An approver must hold the decision's approver_role. Operator-set.",
    )
    external_tool_prefixes: str = Field(
        default="mcp.",
        description="Comma-separated tool-name prefixes executed by an external, trusted "
        "executor (e.g. the MCP proxy). The gateway decides and binds; the executor runs.",
    )

    @property
    def ephemeral(self) -> bool:
        return self.database_path == ":memory:"

    def grant_keyring(self, now: datetime | None = None) -> GrantKeyring:
        """The active Ed25519 signer and every public key that still verifies."""
        from atp_gateway.grant_keys import ephemeral_keyring, load_grant_keys

        if self.grant_signing_kid:
            if not self.grant_keys_dir:
                raise InsecureConfigurationError(
                    "ATP_GRANT_SIGNING_KID is set but ATP_GRANT_KEYS_DIR is not"
                )
            if self.grant_signing_key:
                log.warning("ATP_GRANT_SIGNING_KEY (HMAC, atp-grant/1) is ignored; remove it")
            try:
                return load_grant_keys(
                    Path(self.grant_keys_dir),
                    self.grant_signing_kid,
                    grant_ttl_seconds=self.grant_ttl_seconds,
                    now=now,
                )
            except (OSError, ValueError) as exc:
                raise InsecureConfigurationError(
                    f"cannot load grant signing key {self.grant_signing_kid} from "
                    f"{self.grant_keys_dir}: {exc}"
                ) from exc
        if self.ephemeral:
            if self.grant_signing_key:
                log.warning("ATP_GRANT_SIGNING_KEY (HMAC, atp-grant/1) is ignored; remove it")
            log.info("grant key not set; ephemeral in-memory gateway, generating a per-process key")
            return ephemeral_keyring()
        if self.grant_signing_key:
            raise InsecureConfigurationError(
                "ATP_GRANT_SIGNING_KEY (an HMAC key for atp-grant/1) is no longer supported. "
                "Execution grants are Ed25519 now: run `atp keygen --write .env.new` and use "
                "its ATP_GRANT_KEYS_DIR and ATP_GRANT_SIGNING_KID (an ATP home migrates itself)"
            )
        raise InsecureConfigurationError(
            "ATP_GRANT_SIGNING_KID is not set. A persistent gateway will not start with "
            "generated keys. Run: atp keygen --write .env"
        )

    def principal_keys(self) -> PrincipalKeys:
        """Whose root signatures this gateway trusts (see ``principal_keys_dir``)."""
        from atp_identity import EphemeralPrincipalKeys, FilePrincipalKeys, InMemoryPrincipalKeys

        if self.principal_keys_dir:
            return FilePrincipalKeys(self.principal_keys_dir)
        if self.ephemeral:
            return EphemeralPrincipalKeys()
        log.warning(
            "ATP_PRINCIPAL_KEYS_DIR is not set: no human key is trusted, so every root "
            "delegation is denied (DELEGATION_ROOT_SIGNATURE_INVALID). Create keys with "
            "`atp principal keygen HUMAN_ID --dir DIR`."
        )
        return InMemoryPrincipalKeys()  # empty: trusts nobody

    def operator_key_value(self) -> str:
        return self._resolve("ATP_OPERATOR_KEY", self.operator_key)

    def _resolve(self, name: str, value: str) -> str:
        if value:
            if len(value) < MIN_KEY_LENGTH:
                raise InsecureConfigurationError(
                    f"{name} must be at least {MIN_KEY_LENGTH} characters; "
                    "generate one with: atp keygen"
                )
            return value
        if self.ephemeral:
            log.info("%s not set; ephemeral in-memory gateway, generating a per-process key", name)
            return new_secret_key()
        raise InsecureConfigurationError(
            f"{name} is not set. A persistent gateway will not start with generated keys. "
            "Run: atp keygen --write .env"
        )

    def external_tool_prefix_list(self) -> list[str]:
        return [p.strip() for p in self.external_tool_prefixes.split(",") if p.strip()]

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

"""Configuration loading, validation, and environment overrides."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class ModelSettings(BaseModel):
    provider_model: str


class ProviderSettings(BaseModel):
    enabled: bool = True
    command: str
    max_concurrent: int = Field(default=1, ge=1, le=32)
    timeout_seconds: float = Field(default=300.0, gt=0, le=3600)
    advertise_unavailable: bool = False
    working_directory: Path = Field(default_factory=Path.home)
    models: dict[str, ModelSettings]

    @field_validator("working_directory", mode="before")
    @classmethod
    def expand_working_directory(cls, value: str | Path) -> Path:
        return Path(value).expanduser()


class CodexSettings(ProviderSettings):
    command: str = "codex"
    max_concurrent: int = Field(default=2, ge=1, le=32)
    models: dict[str, ModelSettings] = Field(
        default_factory=lambda: {"codex/gpt-5.6-sol": ModelSettings(provider_model="gpt-5.6-sol")}
    )


class ClaudeSettings(ProviderSettings):
    command: str = "claude"
    models: dict[str, ModelSettings] = Field(
        default_factory=lambda: {"claude-code/opus-5": ModelSettings(provider_model="opus")}
    )


class ProvidersSettings(BaseModel):
    codex: CodexSettings = Field(default_factory=CodexSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)


class ServerSettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    host: str = "127.0.0.1"
    port: int = Field(default=11435, ge=1, le=65535)
    api_key: SecretStr | None = Field(default=None, repr=False)
    allow_remote: bool = False

    @model_validator(mode="after")
    def validate_remote_binding(self) -> ServerSettings:
        loopback_hosts = {"127.0.0.1", "::1", "localhost"}
        if self.host not in loopback_hosts:
            if not self.allow_remote:
                raise ValueError(
                    "non-loopback binding requires server.allow_remote=true; "
                    "localhost is the default"
                )
            if self.api_key is None or not self.api_key.get_secret_value():
                raise ValueError("non-loopback binding requires a local gateway API key")
        return self


class RoutingSettings(BaseModel):
    fallback: bool = True
    order: list[str] = Field(default_factory=lambda: ["codex", "claude"])

    @field_validator("order")
    @classmethod
    def validate_order(cls, value: list[str]) -> list[str]:
        valid = {"codex", "claude"}
        unknown = set(value) - valid
        if unknown:
            raise ValueError(f"unknown providers in routing.order: {sorted(unknown)}")
        if len(set(value)) != len(value):
            raise ValueError("routing.order may not contain duplicates")
        return value


class AgentSettings(BaseModel):
    allowed_directories: list[Path] = Field(default_factory=lambda: [Path.home() / "workspace"])
    allow_outside_directories: bool = False
    allow_write_fallback: bool = False

    @field_validator("allowed_directories", mode="before")
    @classmethod
    def expand_allowed_directories(cls, value: list[str | Path]) -> list[Path]:
        return [Path(item).expanduser() for item in value]


class StorageSettings(BaseModel):
    sqlite_path: Path = Field(
        default_factory=lambda: (
            Path.home() / ".local" / "share" / "subscription-llm-gateway" / "gateway.db"
        )
    )

    @field_validator("sqlite_path", mode="before")
    @classmethod
    def expand_sqlite_path(cls, value: str | Path) -> Path:
        if str(value) == ":memory:":
            return Path(":memory:")
        return Path(value).expanduser()


class LoggingSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    level: str = "INFO"
    json_output: bool = Field(default=False, alias="json")
    debug_prompts: bool = False

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError(f"invalid logging level: {value}")
        return normalized


class GatewayConfig(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    providers: ProvidersSettings = Field(default_factory=ProvidersSettings)
    routing: RoutingSettings = Field(default_factory=RoutingSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "GATEWAY_HOST": ("server", "host"),
    "GATEWAY_PORT": ("server", "port"),
    "GATEWAY_API_KEY": ("server", "api_key"),
    "GATEWAY_ALLOW_REMOTE": ("server", "allow_remote"),
    "GATEWAY_SQLITE_PATH": ("storage", "sqlite_path"),
    "GATEWAY_LOG_LEVEL": ("logging", "level"),
    "GATEWAY_DEBUG_PROMPTS": ("logging", "debug_prompts"),
    "GATEWAY_CODEX_COMMAND": ("providers", "codex", "command"),
    "GATEWAY_CLAUDE_COMMAND": ("providers", "claude", "command"),
}


def _set_nested(target: dict[str, Any], path: tuple[str, ...], value: str) -> None:
    current = target
    for part in path[:-1]:
        current = current.setdefault(part, {})
    current[path[-1]] = value


def load_config(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> GatewayConfig:
    """Load YAML when present, then apply explicit environment overrides."""

    env = os.environ if environ is None else environ
    configured_path = path or env.get("SUBSCRIPTION_GATEWAY_CONFIG")
    raw: dict[str, Any] = {}
    if configured_path is not None:
        config_path = Path(configured_path).expanduser()
        if not config_path.is_file():
            raise ValueError(f"configuration file does not exist: {config_path}")
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if loaded is not None and not isinstance(loaded, dict):
            raise ValueError("configuration root must be a YAML mapping")
        raw = loaded or {}

    for env_name, field_path in ENV_OVERRIDES.items():
        if env_name in env:
            _set_nested(raw, field_path, env[env_name])
    return GatewayConfig.model_validate(raw)


def secret_value(value: SecretStr | None) -> str | None:
    return None if value is None else value.get_secret_value()

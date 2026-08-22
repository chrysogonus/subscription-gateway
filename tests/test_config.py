from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from subscription_gateway.config import ClaudeSettings, CodexSettings, GatewayConfig, load_config

REPO_ROOT = Path(__file__).parents[1]


def _provider_config(models: dict[str, Any]) -> dict[str, Any]:
    return {"providers": {"codex": {"models": models}}}


def test_yaml_and_environment_overrides(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"server": {"port": 12000}, "storage": {"sqlite_path": "~/x.db"}}),
        encoding="utf-8",
    )
    config = load_config(
        path,
        environ={"GATEWAY_PORT": "13000", "GATEWAY_LOG_LEVEL": "debug"},
    )
    assert config.server.port == 13000
    assert config.logging.level == "DEBUG"
    assert config.storage.sqlite_path == Path.home() / "x.db"


def test_remote_bind_requires_explicit_flag_and_key() -> None:
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate({"server": {"host": "0.0.0.0"}})
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate({"server": {"host": "0.0.0.0", "allow_remote": True}})
    config = GatewayConfig.model_validate(
        {
            "server": {
                "host": "0.0.0.0",
                "allow_remote": True,
                "api_key": "local",
            }
        }
    )
    assert config.server.host == "0.0.0.0"


def test_default_catalog_aliases() -> None:
    codex = CodexSettings()
    claude = ClaudeSettings()

    assert {alias: model.provider_model for alias, model in codex.models.items()} == {
        "codex/gpt-5.6-sol": "gpt-5.6-sol"
    }
    assert {alias: model.provider_model for alias, model in claude.models.items()} == {
        "claude-code/opus": "opus",
        "claude-code/sonnet": "sonnet",
        "claude-code/haiku": "haiku",
        "claude-code/fable": "fable",
    }
    assert codex.default_alias == "codex/gpt-5.6-sol"
    assert claude.default_alias == "claude-code/opus"


def test_config_example_matches_built_in_defaults() -> None:
    """The Compose deployment mounts config.example.yaml by default, so drift
    between it and the built-in catalog would silently change that deployment."""

    example = load_config(REPO_ROOT / "config.example.yaml", environ={})
    defaults = GatewayConfig()

    assert example.providers.codex.models == defaults.providers.codex.models
    assert example.providers.claude.models == defaults.providers.claude.models
    assert example.providers.codex.default_alias == defaults.providers.codex.default_alias
    assert example.providers.claude.default_alias == defaults.providers.claude.default_alias


def test_more_than_one_default_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at most one model may set default"):
        GatewayConfig.model_validate(
            _provider_config(
                {
                    "codex/a": {"provider_model": "a", "default": True},
                    "codex/b": {"provider_model": "b", "default": True},
                }
            )
        )


def test_zero_defaults_falls_back_to_first_key() -> None:
    config = GatewayConfig.model_validate(
        _provider_config(
            {
                "codex/first": {"provider_model": "first"},
                "codex/second": {"provider_model": "second"},
            }
        )
    )
    assert config.providers.codex.default_alias is None


def test_reserved_auto_alias_is_rejected() -> None:
    with pytest.raises(ValidationError, match="reserved"):
        GatewayConfig.model_validate(
            _provider_config({"subscription/auto": {"provider_model": "x"}})
        )


def test_cross_provider_prefix_alias_is_rejected() -> None:
    with pytest.raises(ValidationError, match="another provider"):
        GatewayConfig.model_validate(
            _provider_config({"claude-code/opus": {"provider_model": "opus"}})
        )


@pytest.mark.parametrize(
    "provider_model",
    ["", " ", "-x", "--model", "a b", "a/b", ".x", "a;b", "a\nb", "a" * 200],
)
def test_invalid_provider_model_is_rejected(provider_model: str) -> None:
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(
            _provider_config({"codex/x": {"provider_model": provider_model}})
        )


def test_unknown_model_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(
            _provider_config({"codex/x": {"provider_model": "x", "temperature": 0.5}})
        )

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from subscription_gateway.config import GatewayConfig, load_config


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

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).parents[1]
WEBUI_PROFILE = "webui"


def _compose() -> dict[str, Any]:
    compose_path = REPO_ROOT / "docker-compose.yml"
    loaded: dict[str, Any] = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    return loaded


def test_open_webui_is_wired_to_gateway() -> None:
    webui = _compose()["services"]["open-webui"]

    assert webui["environment"]["OPENAI_API_BASE_URL"] == "http://gateway:11435/v1"
    assert webui["environment"]["ENABLE_OLLAMA_API"] == "false"
    # Every other OpenWebUI account would use the owner's subscription.
    assert webui["environment"]["DEFAULT_USER_ROLE"] == "pending"
    assert json.loads(webui["environment"]["DEFAULT_MODEL_PARAMS"]) == {
        "function_calling": "legacy"
    }
    assert webui["depends_on"]["gateway"]["condition"] == "service_healthy"
    assert webui["ports"] == ["127.0.0.1:${OPEN_WEBUI_PORT:-3001}:8080"]
    assert "open-webui-data:/app/backend/data" in webui["volumes"]
    assert "http://127.0.0.1:8080/health" in webui["healthcheck"]["test"]


def test_open_webui_is_opt_in_and_the_gateway_is_not() -> None:
    services = _compose()["services"]

    assert services["open-webui"]["profiles"] == [WEBUI_PROFILE]
    assert "profiles" not in services["gateway"]


def test_gateway_mounts_a_read_only_config() -> None:
    gateway = _compose()["services"]["gateway"]
    mount = "${GATEWAY_CONFIG_FILE:-./config.example.yaml}:/etc/subscription-gateway/config.yaml:ro"

    assert mount in gateway["volumes"]
    assert (
        gateway["environment"]["SUBSCRIPTION_GATEWAY_CONFIG"]
        == "/etc/subscription-gateway/config.yaml"
    )


def test_gateway_forwards_an_optional_anthropic_api_key() -> None:
    gateway = _compose()["services"]["gateway"]
    assert gateway["environment"]["ANTHROPIC_API_KEY"] == "${ANTHROPIC_API_KEY:-}"


def test_makefile_selects_the_declared_profile() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    selections = set(re.findall(r"--profile (\S+)", makefile))

    assert selections == {WEBUI_PROFILE}


def test_docker_package_includes_its_declared_license() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY pyproject.toml uv.lock README.md LICENSE ./" in dockerfile


def test_compose_cli_versions_match_the_dockerfile_defaults() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for variable in ("CODEX_VERSION", "CLAUDE_CODE_VERSION"):
        version = re.search(rf"^ARG {variable}=([^\s]+)$", dockerfile, re.MULTILINE)
        assert version is not None
        assert f"${{{variable}:-{version.group(1)}}}" in compose

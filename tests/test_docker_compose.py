from __future__ import annotations

from pathlib import Path

import yaml


def test_open_webui_is_wired_to_gateway() -> None:
    compose_path = Path(__file__).parents[1] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose["services"]
    webui = services["open-webui"]

    assert webui["environment"]["OPENAI_API_BASE_URL"] == "http://gateway:11435/v1"
    assert webui["environment"]["ENABLE_OLLAMA_API"] == "false"
    assert webui["depends_on"]["gateway"]["condition"] == "service_healthy"
    assert webui["ports"] == ["127.0.0.1:${OPEN_WEBUI_PORT:-3001}:8080"]
    assert "open-webui-data:/app/backend/data" in webui["volumes"]
    assert "http://127.0.0.1:8080/health" in webui["healthcheck"]["test"]

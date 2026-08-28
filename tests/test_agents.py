from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeProvider
from fastapi.testclient import TestClient

from subscription_gateway.api.agents import validate_agent_cwd
from subscription_gateway.config import GatewayConfig
from subscription_gateway.errors import GatewayError
from subscription_gateway.main import create_app
from subscription_gateway.providers.base import ProviderCapabilities

API_KEY = "agent-test-key"


def agent_config(config: GatewayConfig) -> GatewayConfig:
    data = config.model_dump(mode="python")
    data["server"]["api_key"] = API_KEY
    return GatewayConfig.model_validate(data)


def auth_headers(**extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}", **extra}


def test_agent_path_validation(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    project = allowed / "project"
    project.mkdir(parents=True)
    assert validate_agent_cwd(project, [allowed], False) == project.resolve()


def test_agent_path_outside_allowed_is_rejected(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    with pytest.raises(GatewayError) as caught:
        validate_agent_cwd(outside, [allowed], False)
    assert caught.value.error_type == "agent_permission_error"


def test_agent_endpoint_defaults_to_read_only(
    gateway_config: GatewayConfig, tmp_path: Path
) -> None:
    fake_claude = FakeProvider("claude")
    with TestClient(
        create_app(agent_config(gateway_config), providers={"claude": fake_claude})
    ) as client:
        response = client.post(
            "/v1/agents/run",
            headers=auth_headers(),
            json={
                "model": "claude-code/sonnet",
                "prompt": "Inspect tests",
                "cwd": str(tmp_path),
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert fake_claude.calls[0]["options"]["permissions"] == "read-only"


def test_agent_endpoint_requires_configured_api_key(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/v1/agents/run",
        json={
            "model": "codex/gpt-5.6-sol",
            "prompt": "Inspect tests",
            "cwd": str(tmp_path),
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "agent_permission_error"


def test_auto_agent_route_skips_chat_only_providers(
    gateway_config: GatewayConfig, tmp_path: Path
) -> None:
    class ChatOnlyProvider(FakeProvider):
        capabilities = ProviderCapabilities(
            chat=True,
            streaming=True,
            persistent_sessions=True,
            filesystem_agent=False,
            tools=True,
        )

    codex = ChatOnlyProvider("codex")
    claude = FakeProvider("claude")
    with TestClient(
        create_app(
            agent_config(gateway_config),
            providers={"codex": codex, "claude": claude},
        )
    ) as client:
        response = client.post(
            "/v1/agents/run",
            headers=auth_headers(),
            json={
                "model": "subscription/auto",
                "prompt": "Inspect tests",
                "cwd": str(tmp_path),
            },
        )
    assert response.status_code == 200
    assert response.json()["provider"] == "claude"
    assert not codex.calls


def test_explicit_chat_only_provider_is_rejected_for_agent_tasks(
    gateway_config: GatewayConfig, tmp_path: Path
) -> None:
    class ChatOnlyProvider(FakeProvider):
        capabilities = ProviderCapabilities(filesystem_agent=False)

    codex = ChatOnlyProvider("codex")
    with TestClient(create_app(agent_config(gateway_config), providers={"codex": codex})) as client:
        response = client.post(
            "/v1/agents/run",
            headers=auth_headers(),
            json={
                "model": "codex/gpt-5.6-sol",
                "prompt": "Inspect tests",
                "cwd": str(tmp_path),
            },
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_provider_capability"
    assert not codex.calls


def test_agent_session_cannot_resume_as_chat(gateway_config: GatewayConfig, tmp_path: Path) -> None:
    fake_claude = FakeProvider("claude")
    with TestClient(
        create_app(agent_config(gateway_config), providers={"claude": fake_claude})
    ) as client:
        first = client.post(
            "/v1/agents/run",
            headers=auth_headers(),
            json={
                "model": "claude-code/sonnet",
                "prompt": "Inspect tests",
                "cwd": str(tmp_path),
            },
        )
        second = client.post(
            "/v1/chat/completions",
            headers=auth_headers(**{"X-Gateway-Session": first.json()["session_id"]}),
            json={
                "model": "claude-code/sonnet",
                "messages": [{"role": "user", "content": "continue"}],
            },
        )
    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "session_context_mismatch"
    assert len(fake_claude.calls) == 1


@pytest.mark.parametrize("change", ["permissions", "cwd"])
def test_agent_session_context_cannot_change(
    gateway_config: GatewayConfig, tmp_path: Path, change: str
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    fake_claude = FakeProvider("claude")
    with TestClient(
        create_app(agent_config(gateway_config), providers={"claude": fake_claude})
    ) as client:
        first = client.post(
            "/v1/agents/run",
            headers=auth_headers(),
            json={
                "model": "claude-code/sonnet",
                "prompt": "Inspect tests",
                "cwd": str(tmp_path),
            },
        )
        body = {
            "model": "claude-code/sonnet",
            "prompt": "continue",
            "cwd": str(other if change == "cwd" else tmp_path),
            "permissions": "workspace-write" if change == "permissions" else "read-only",
            "gateway_session_id": first.json()["session_id"],
        }
        second = client.post("/v1/agents/run", headers=auth_headers(), json=body)
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "session_context_mismatch"
    assert len(fake_claude.calls) == 1

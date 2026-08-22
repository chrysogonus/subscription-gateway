from __future__ import annotations

from pathlib import Path

from conftest import FakeProvider
from fastapi.testclient import TestClient

from subscription_gateway.config import GatewayConfig
from subscription_gateway.errors import ProviderError
from subscription_gateway.main import create_app


def temporary_error(provider: str) -> ProviderError:
    return ProviderError(
        "temporary",
        error_type="provider_unavailable",
        code="provider_temporary_error",
        status_code=503,
        provider=provider,
        retryable=True,
    )


def test_auto_prefers_codex(gateway_config: GatewayConfig) -> None:
    codex = FakeProvider("codex", text="codex")
    claude = FakeProvider("claude", text="claude")
    with TestClient(
        create_app(gateway_config, providers={"codex": codex, "claude": claude})
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "subscription/auto",
                "messages": [{"role": "user", "content": "x"}],
            },
        )
    assert response.json()["choices"][0]["message"]["content"] == "codex"
    assert len(codex.calls) == 1
    assert not claude.calls


def test_retryable_failure_falls_back(gateway_config: GatewayConfig) -> None:
    codex = FakeProvider("codex", error=temporary_error("codex"))
    claude = FakeProvider("claude", text="fallback")
    with TestClient(
        create_app(gateway_config, providers={"codex": codex, "claude": claude})
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "codex/gpt-5.6-sol",
                "messages": [{"role": "user", "content": "x"}],
            },
        )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "fallback"
    assert len(codex.calls) == len(claude.calls) == 1


def test_fallback_can_be_disabled(gateway_config: GatewayConfig) -> None:
    data = gateway_config.model_dump(mode="python")
    data["routing"]["fallback"] = False
    config = GatewayConfig.model_validate(data)
    codex = FakeProvider("codex", error=temporary_error("codex"))
    claude = FakeProvider("claude", text="fallback")
    with TestClient(create_app(config, providers={"codex": codex, "claude": claude})) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "codex/gpt-5.6-sol",
                "messages": [{"role": "user", "content": "x"}],
            },
        )
    assert response.status_code == 503
    assert not claude.calls


def test_write_agent_does_not_fallback_without_double_opt_in(
    gateway_config: GatewayConfig, tmp_path: Path
) -> None:
    codex = FakeProvider("codex", error=temporary_error("codex"))
    claude = FakeProvider("claude", text="fallback")
    with TestClient(
        create_app(gateway_config, providers={"codex": codex, "claude": claude})
    ) as client:
        response = client.post(
            "/v1/agents/run",
            json={
                "model": "codex/gpt-5.6-sol",
                "prompt": "edit a file",
                "cwd": str(tmp_path),
                "permissions": "workspace-write",
                "fallback": True,
            },
        )
    assert response.status_code == 503
    assert not claude.calls

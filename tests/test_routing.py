from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
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


def model_rejected_error(provider: str) -> ProviderError:
    """What process.classify_provider_failure builds when a CLI rejects a model."""

    return ProviderError(
        "The requested model is not available.",
        error_type="model_not_available",
        code="model_not_available",
        status_code=404,
        provider=provider,
        retryable=True,
    )


def chat(client: TestClient, model: str) -> Any:
    return client.post(
        "/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "x"}]},
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


def test_passthrough_forwards_suffix_to_codex(gateway_config: GatewayConfig) -> None:
    codex = FakeProvider("codex", text="passthrough")
    with TestClient(create_app(gateway_config, providers={"codex": codex})) as client:
        response = chat(client, "codex/gpt-5.6-experimental")

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "passthrough"
    assert codex.calls[0]["model"] == "gpt-5.6-experimental"


def test_passthrough_forwards_suffix_to_claude(gateway_config: GatewayConfig) -> None:
    claude = FakeProvider("claude", text="passthrough")
    with TestClient(create_app(gateway_config, providers={"claude": claude})) as client:
        response = chat(client, "claude-code/claude-fable-5")

    assert response.status_code == 200
    assert claude.calls[0]["model"] == "claude-fable-5"


def test_catalog_alias_wins_over_passthrough(gateway_config: GatewayConfig) -> None:
    """Precedence guard: reversing catalog-before-passthrough in registry.resolve
    would send the suffix ('x') instead of the configured provider_model."""

    claude = FakeProvider("claude", models={"claude-code/x": "mapped-model"})
    with TestClient(create_app(gateway_config, providers={"claude": claude})) as client:
        response = chat(client, "claude-code/x")

    assert response.status_code == 200
    assert claude.calls[0]["model"] == "mapped-model"


def test_legacy_alias_resolves_but_is_not_advertised(gateway_config: GatewayConfig) -> None:
    claude = FakeProvider("claude")
    with TestClient(create_app(gateway_config, providers={"claude": claude})) as client:
        response = chat(client, "claude-code/opus-5")
        listed = [item["id"] for item in client.get("/v1/models").json()["data"]]

    assert response.status_code == 200
    assert claude.calls[0]["model"] == "opus"
    assert "claude-code/opus-5" not in listed


@pytest.mark.parametrize(
    "model",
    ["codex/", "codex/-rf", "codex/--sandbox", "codex/a b", "codex/a/b", "raw/fake", "Codex/x"],
)
def test_rejected_model_names_never_reach_the_provider(
    gateway_config: GatewayConfig, model: str
) -> None:
    codex = FakeProvider("codex")
    with TestClient(create_app(gateway_config, providers={"codex": codex})) as client:
        response = chat(client, model)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_available"
    assert codex.calls == []


def test_named_model_rejected_by_cli_does_not_fall_back(gateway_config: GatewayConfig) -> None:
    codex = FakeProvider("codex", error=model_rejected_error("codex"))
    claude = FakeProvider("claude", text="claude")
    with TestClient(
        create_app(gateway_config, providers={"codex": codex, "claude": claude})
    ) as client:
        response = chat(client, "codex/definitely-not-a-model")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_available"
    assert claude.calls == []


def test_auto_still_falls_back_on_model_not_available(gateway_config: GatewayConfig) -> None:
    """The caller named no model, so recovering on another provider is legitimate."""

    codex = FakeProvider("codex", error=model_rejected_error("codex"))
    claude = FakeProvider("claude", text="claude")
    with TestClient(
        create_app(gateway_config, providers={"codex": codex, "claude": claude})
    ) as client:
        response = chat(client, "subscription/auto")

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "claude"
    assert len(claude.calls) == 1


def test_streaming_named_model_rejection_does_not_fall_back(
    gateway_config: GatewayConfig,
) -> None:
    codex = FakeProvider("codex", error=model_rejected_error("codex"))
    claude = FakeProvider("claude", text="claude")
    with TestClient(
        create_app(gateway_config, providers={"codex": codex, "claude": claude})
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "codex/definitely-not-a-model",
                "stream": True,
                "messages": [{"role": "user", "content": "x"}],
            },
        )

    body = response.text
    assert response.status_code == 200  # headers were already committed
    assert body.count('"code":"model_not_available"') == 1
    assert body.rstrip().endswith("data: [DONE]")
    assert claude.calls == []


def test_explicit_default_selects_the_auto_target(gateway_config: GatewayConfig) -> None:
    data = gateway_config.model_dump(mode="python")
    data["providers"]["claude"]["models"] = {
        "claude-code/opus": {"provider_model": "opus"},
        "claude-code/sonnet": {"provider_model": "sonnet", "default": True},
    }
    data["routing"]["order"] = ["claude"]
    config = GatewayConfig.model_validate(data)

    claude = FakeProvider(
        "claude",
        models={"claude-code/opus": "opus", "claude-code/sonnet": "sonnet"},
    )
    claude.default_alias = config.providers.claude.default_alias
    with TestClient(create_app(config, providers={"claude": claude})) as client:
        response = chat(client, "subscription/auto")

    assert response.status_code == 200
    assert claude.calls[0]["model"] == "sonnet"


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

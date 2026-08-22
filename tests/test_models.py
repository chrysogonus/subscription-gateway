from __future__ import annotations

from conftest import FakeProvider
from fastapi.testclient import TestClient

from subscription_gateway.config import GatewayConfig
from subscription_gateway.main import create_app


def test_models_lists_only_usable_providers(client: TestClient) -> None:
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [
        "codex/gpt-5.6-sol",
        "subscription/auto",
    ]


def test_models_empty_when_provider_unavailable(
    gateway_config: GatewayConfig,
) -> None:
    provider = FakeProvider(available=False)
    with TestClient(create_app(gateway_config, providers={"codex": provider})) as test_client:
        assert test_client.get("/health").status_code == 200
        assert test_client.get("/ready").status_code == 503
        assert test_client.get("/v1/models").json() == {"object": "list", "data": []}


def test_model_listing_shape(client: TestClient) -> None:
    item = client.get("/v1/models").json()["data"][0]
    assert item == {
        "id": "codex/gpt-5.6-sol",
        "object": "model",
        "owned_by": "local-gateway",
    }


def test_models_lists_the_full_default_catalog(gateway_config: GatewayConfig) -> None:
    codex = FakeProvider("codex")
    claude = FakeProvider("claude")
    with TestClient(
        create_app(gateway_config, providers={"codex": codex, "claude": claude})
    ) as test_client:
        listed = [item["id"] for item in test_client.get("/v1/models").json()["data"]]

    assert listed == [
        "codex/gpt-5.6-sol",
        "claude-code/opus",
        "claude-code/sonnet",
        "claude-code/haiku",
        "claude-code/fable",
        "subscription/auto",
    ]

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from conftest import FakeProvider
from fastapi.testclient import TestClient

from subscription_gateway.config import GatewayConfig
from subscription_gateway.main import create_app
from subscription_gateway.providers import registry as registry_module
from subscription_gateway.providers.registry import ProviderRegistry


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


class CountingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__("codex")
        self.login_checks = 0

    async def is_authenticated(self) -> bool:
        self.login_checks += 1
        await asyncio.sleep(0.01)  # long enough for concurrent calls to overlap
        return True


@pytest.mark.asyncio
async def test_readiness_checks_are_cached_and_shared(gateway_config: GatewayConfig) -> None:
    provider = CountingProvider()
    registry = ProviderRegistry(gateway_config, {"codex": provider})

    first, *_ = await asyncio.gather(*(registry.statuses() for _ in range(5)))
    assert await registry.statuses() == first
    assert provider.login_checks == 1


def test_ready_does_not_rerun_login_checks_per_request(gateway_config: GatewayConfig) -> None:
    provider = CountingProvider()
    with TestClient(create_app(gateway_config, providers={"codex": provider})) as test_client:
        responses = [test_client.get("/ready") for _ in range(3)]

    assert all(response.status_code == 200 for response in responses)
    assert provider.login_checks == 1


@pytest.mark.asyncio
async def test_a_slow_refresh_is_still_shared_and_cached(
    gateway_config: GatewayConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(registry_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    class SlowProvider(CountingProvider):
        async def is_authenticated(self) -> bool:
            clock[0] += 10.1  # a login check that takes longer than the cache lifetime
            return await super().is_authenticated()

    provider = SlowProvider()
    registry = ProviderRegistry(gateway_config, {"codex": provider})

    await asyncio.gather(*(registry.statuses() for _ in range(5)))
    assert provider.login_checks == 1

    clock[0] += 9.9  # still fresh: the lifetime counts from when the refresh finished
    await registry.statuses()
    assert provider.login_checks == 1

    clock[0] += 0.2
    await registry.statuses()
    assert provider.login_checks == 2

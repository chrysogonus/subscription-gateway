from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from subscription_gateway.config import ClaudeSettings, CodexSettings, GatewayConfig
from subscription_gateway.errors import ProviderError
from subscription_gateway.main import create_app
from subscription_gateway.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderEvent,
    ProviderResponse,
    ProviderUsage,
    configured_models,
)


class FakeProvider(Provider):
    capabilities = ProviderCapabilities(
        chat=True,
        streaming=True,
        persistent_sessions=True,
        filesystem_agent=True,
        tools=True,
    )

    def __init__(
        self,
        name: str = "codex",
        *,
        models: dict[str, str] | None = None,
        text: str = "mock answer",
        available: bool = True,
        error: ProviderError | None = None,
        delay: float = 0,
    ) -> None:
        # Source the catalog from the real settings so the fake cannot drift.
        settings = CodexSettings() if name == "codex" else ClaudeSettings()
        super().__init__(
            models or configured_models(settings.models),
            settings.default_alias,
        )
        self.name = name
        self.display_name = "Codex" if name == "codex" else "Claude Code"
        self.text = text
        self.available = available
        self.error = error
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0

    def is_installed(self) -> bool:
        return self.available

    async def is_authenticated(self) -> bool:
        return self.available

    async def is_available(self) -> bool:
        return self.available

    async def list_models(self) -> list[str]:
        return list(self.models) if self.available else []

    async def send(
        self,
        session_id: str | None,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> ProviderResponse:
        self.calls.append(
            {
                "session_id": session_id,
                "model": model,
                "messages": messages,
                "options": options,
            }
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.error:
                raise self.error
            return ProviderResponse(
                text=self.text,
                provider_session_id=session_id or f"{self.name}-thread",
                usage=ProviderUsage(input_tokens=4, output_tokens=2),
            )
        finally:
            self.active -= 1

    async def stream(
        self,
        session_id: str | None,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> AsyncIterator[ProviderEvent]:
        response = await self.send(session_id, model, messages, options)
        yield ProviderEvent(type="session", session_id=response.provider_session_id)
        midpoint = max(1, len(response.text) // 2)
        yield ProviderEvent(type="delta", text=response.text[:midpoint])
        yield ProviderEvent(type="delta", text=response.text[midpoint:])
        yield ProviderEvent(type="completed", response=response)


@pytest.fixture
def gateway_config(tmp_path: Path) -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            "storage": {"sqlite_path": tmp_path / "gateway.db"},
            "agent": {"allowed_directories": [tmp_path]},
        }
    )


@pytest.fixture
def fake_codex() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(gateway_config: GatewayConfig, fake_codex: FakeProvider) -> Iterator[TestClient]:
    with TestClient(create_app(gateway_config, providers={"codex": fake_codex})) as test_client:
        yield test_client

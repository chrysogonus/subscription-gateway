"""Provider construction, lookup, and availability reporting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from subscription_gateway.config import GatewayConfig
from subscription_gateway.providers.base import Provider
from subscription_gateway.providers.claude import ClaudeProvider
from subscription_gateway.providers.codex import CodexProvider


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    name: str
    display_name: str
    enabled: bool
    installed: bool
    authenticated: bool
    available: bool
    models: list[str]


class ProviderRegistry:
    def __init__(self, config: GatewayConfig, providers: dict[str, Provider] | None = None) -> None:
        self.config = config
        self.providers = providers or {
            "codex": CodexProvider(config.providers.codex),
            "claude": ClaudeProvider(config.providers.claude),
        }

    def get(self, name: str) -> Provider | None:
        return self.providers.get(name)

    def owner_of(self, public_model: str) -> Provider | None:
        return next(
            (provider for provider in self.providers.values() if public_model in provider.models),
            None,
        )

    async def available_models(self) -> list[str]:
        listed = await asyncio.gather(
            *(provider.list_models() for provider in self.providers.values())
        )
        models = [model for provider_models in listed for model in provider_models]
        if models:
            models.append("subscription/auto")
        return models

    async def statuses(self) -> list[ProviderStatus]:
        async def inspect(name: str, provider: Provider) -> ProviderStatus:
            installed = provider.is_installed()
            authenticated = await provider.is_authenticated() if installed else False
            enabled = self._enabled(name)
            return ProviderStatus(
                name=name,
                display_name=provider.display_name,
                enabled=enabled,
                installed=installed,
                authenticated=authenticated,
                available=enabled and installed and authenticated,
                models=list(provider.models),
            )

        return await asyncio.gather(
            *(inspect(name, provider) for name, provider in self.providers.items())
        )

    def _enabled(self, name: str) -> bool:
        settings = getattr(self.config.providers, name, None)
        if settings is None and name == "claude":
            settings = self.config.providers.claude
        return bool(getattr(settings, "enabled", True))

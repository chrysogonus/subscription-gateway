"""Provider construction, lookup, and availability reporting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from subscription_gateway.config import GatewayConfig
from subscription_gateway.model_names import (
    AUTO_MODEL,
    LEGACY_ALIASES,
    is_valid_provider_model,
    split_prefixed,
)
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
    subscription_auth: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    provider: Provider
    provider_model: str
    catalogued: bool


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

    def resolve(self, public_model: str) -> ResolvedModel | None:
        """Configured aliases win; unlisted `codex/<x>` and `claude-code/<x>` pass through.

        Catalog-before-passthrough precedence is load-bearing: it is what keeps a
        legacy or re-pointed alias from being reinterpreted as its own suffix.
        """

        owner = self.owner_of(public_model)
        if owner is not None:
            # owner_of already matched on membership in owner.models, so this
            # lookup cannot miss. Branch rather than assert: an assert is
            # stripped under -O, and falling through to passthrough is a safer
            # degradation than constructing a ResolvedModel from None.
            provider_model = owner.provider_model(public_model)
            if provider_model is not None:
                return ResolvedModel(owner, provider_model, catalogued=True)

        legacy = LEGACY_ALIASES.get(public_model)
        if legacy is not None:
            legacy_provider = self.providers.get(legacy[0])
            if legacy_provider is None:
                return None
            return ResolvedModel(legacy_provider, legacy[1], catalogued=True)

        split = split_prefixed(public_model)
        if split is None:
            return None
        provider_name, suffix = split
        provider = self.providers.get(provider_name)
        if provider is None or not is_valid_provider_model(suffix):
            return None
        return ResolvedModel(provider, suffix, catalogued=False)

    async def available_models(self) -> list[str]:
        listed = await asyncio.gather(
            *(provider.list_models() for provider in self.providers.values())
        )
        models = [model for provider_models in listed for model in provider_models]
        if models:
            models.append(AUTO_MODEL)
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
                subscription_auth=provider.subscription_auth,
            )

        return await asyncio.gather(
            *(inspect(name, provider) for name, provider in self.providers.items())
        )

    def _enabled(self, name: str) -> bool:
        settings = getattr(self.config.providers, name, None)
        if settings is None and name == "claude":
            settings = self.config.providers.claude
        return bool(getattr(settings, "enabled", True))

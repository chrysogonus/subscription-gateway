"""Simple deterministic routing policy."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from subscription_gateway.config import RoutingSettings
from subscription_gateway.errors import model_not_available
from subscription_gateway.model_names import AUTO_MODEL
from subscription_gateway.providers.base import Provider
from subscription_gateway.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Route:
    provider: Provider
    public_model: str
    provider_model: str
    explicit_model: bool = False


class RoutingPolicy:
    def __init__(self, registry: ProviderRegistry, settings: RoutingSettings) -> None:
        self.registry = registry
        self.settings = settings

    def candidates(
        self,
        requested_model: str,
        *,
        allow_fallback: bool,
        side_effects: bool,
    ) -> list[Route]:
        if requested_model == AUTO_MODEL:
            candidates = self._ordered_defaults()
            if not candidates:
                raise model_not_available(requested_model)
            return candidates if allow_fallback and not side_effects else candidates[:1]

        resolved = self.registry.resolve(requested_model)
        if resolved is None:
            raise model_not_available(requested_model)
        if not resolved.catalogued:
            logger.debug(
                "passthrough model provider=%s model=%s",
                resolved.provider.name,
                resolved.provider_model,
            )
        direct = Route(
            resolved.provider,
            requested_model,
            resolved.provider_model,
            explicit_model=True,
        )
        if not allow_fallback or side_effects:
            return [direct]
        alternatives = [
            route
            for route in self._ordered_defaults()
            if route.provider.name != resolved.provider.name
        ]
        return [direct, *alternatives]

    def pinned(self, provider_name: str, public_model: str, provider_model: str) -> Route:
        provider = self.registry.get(provider_name)
        if provider is None:
            raise model_not_available(public_model, provider_name)
        return Route(provider, public_model, provider_model, explicit_model=True)

    def _ordered_defaults(self) -> list[Route]:
        routes: list[Route] = []
        for provider_name in self.settings.order:
            provider = self.registry.get(provider_name)
            default = provider.default_model() if provider else None
            if provider is not None and default is not None:
                public_model, provider_model = default
                routes.append(Route(provider, public_model, provider_model))
        return routes

"""Simple deterministic routing policy."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from subscription_gateway.config import RoutingSettings
from subscription_gateway.errors import invalid_request, model_not_available
from subscription_gateway.model_names import AUTO_MODEL, PROVIDER_PREFIX_BY_NAME
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
        filesystem_agent: bool = False,
    ) -> list[Route]:
        if requested_model == AUTO_MODEL:
            candidates = self._ordered_defaults()
            if filesystem_agent:
                candidates = [
                    route for route in candidates if route.provider.capabilities.filesystem_agent
                ]
                if not candidates:
                    raise invalid_request(
                        "No configured provider supports filesystem agent tasks.",
                        code="unsupported_provider_capability",
                    )
            if not candidates:
                raise model_not_available(requested_model)
            return candidates if allow_fallback and not side_effects else candidates[:1]

        resolved = self.registry.resolve(requested_model)
        if resolved is None:
            raise model_not_available(requested_model)
        if filesystem_agent and not resolved.provider.capabilities.filesystem_agent:
            raise invalid_request(
                f"Provider '{resolved.provider.name}' does not support filesystem agent tasks.",
                code="unsupported_provider_capability",
            )
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
            and (not filesystem_agent or route.provider.capabilities.filesystem_agent)
        ]
        return [direct, *alternatives]

    def pinned(self, provider_name: str, session_model: str, provider_model: str) -> Route:
        provider = self.registry.get(provider_name)
        if provider is None:
            raise model_not_available(session_model, provider_name)
        resolved = self.registry.resolve(session_model)
        if (
            resolved is not None
            and resolved.provider is provider
            and resolved.provider_model == provider_model
        ):
            public_model = session_model
        else:
            # subscription/auto, or a first turn that fell back: name the alias that runs.
            public_model = next(
                (alias for alias, model in provider.models.items() if model == provider_model),
                f"{PROVIDER_PREFIX_BY_NAME.get(provider.name, '')}{provider_model}",
            )
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

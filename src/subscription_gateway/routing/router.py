"""Execution engine combining routes, fallback, sessions, and scheduling."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from subscription_gateway.config import GatewayConfig
from subscription_gateway.errors import (
    GatewayError,
    ProviderError,
    invalid_request,
    provider_not_authenticated,
    provider_unavailable,
)
from subscription_gateway.providers.base import ProviderEvent, ProviderResponse
from subscription_gateway.providers.registry import ProviderRegistry
from subscription_gateway.queue.scheduler import ProviderScheduler
from subscription_gateway.routing.policies import Route, RoutingPolicy
from subscription_gateway.sessions.manager import SessionManager
from subscription_gateway.sessions.models import ProviderSession

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GatewayResult:
    response: ProviderResponse
    gateway_session_id: str
    provider: str
    executed_model: str
    queue_delay: float


class GatewayEngine:
    def __init__(
        self,
        config: GatewayConfig,
        registry: ProviderRegistry,
        sessions: SessionManager,
        scheduler: ProviderScheduler,
    ) -> None:
        self.config = config
        self.registry = registry
        self.sessions = sessions
        self.scheduler = scheduler
        self.policy = RoutingPolicy(registry, config.routing)

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any],
        gateway_session_id: str | None,
        allow_fallback: bool | None = None,
        agent_task: bool = False,
    ) -> GatewayResult:
        existing, routes = await self._routes(
            model=model,
            gateway_session_id=gateway_session_id,
            allow_fallback=allow_fallback,
            side_effects=(
                agent_task
                and options.get("permissions") == "workspace-write"
                and not options.get("allow_write_fallback", False)
            ),
        )
        last_error: GatewayError | None = None
        if self.config.logging.debug_prompts:
            logger.debug("provider prompt messages=%r", messages)
        for route in routes:
            try:
                self._validate_capability(route, agent_task)
                await self._require_available(route)
                started = time.monotonic()
                async with self.scheduler.slot(route.provider.name) as queue_delay:
                    response = await route.provider.send(
                        existing.provider_session_id if existing else None,
                        route.provider_model,
                        messages,
                        {**options, "agent_task": agent_task},
                    )
                session = await self._persist_success(existing, model, route, response)
                duration = time.monotonic() - started
                logger.info(
                    "provider request completed request_id=%s provider=%s model=%s session_id=%s "
                    "queue_delay_ms=%.1f duration_ms=%.1f status=completed",
                    options.get("request_id", "-"),
                    route.provider.name,
                    route.public_model,
                    session.gateway_session_id,
                    queue_delay * 1000,
                    duration * 1000,
                )
                return GatewayResult(
                    response=response,
                    gateway_session_id=session.gateway_session_id,
                    provider=route.provider.name,
                    executed_model=route.public_model,
                    queue_delay=queue_delay,
                )
            except ProviderError as exc:
                last_error = exc
                if existing is not None or not exc.retryable:
                    raise
                logger.warning(
                    "provider attempt failed provider=%s model=%s code=%s",
                    route.provider.name,
                    route.public_model,
                    exc.code,
                )
        if last_error is not None:
            raise last_error
        raise provider_unavailable("subscription")

    async def create_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any],
        gateway_session_id: str | None,
        allow_fallback: bool | None = None,
    ) -> tuple[str, AsyncIterator[ProviderEvent]]:
        existing, routes = await self._routes(
            model=model,
            gateway_session_id=gateway_session_id,
            allow_fallback=allow_fallback,
            side_effects=False,
        )
        created = existing is None
        session = existing or await self.sessions.create(
            provider=routes[0].provider.name,
            model=model,
            provider_model=routes[0].provider_model,
        )

        async def generate() -> AsyncIterator[ProviderEvent]:
            nonlocal session
            emitted = False
            last_error: GatewayError | None = None
            started = time.monotonic()
            try:
                for route in routes:
                    try:
                        self._validate_capability(route, False)
                        await self._require_available(route)
                        if route.provider.name != session.provider:
                            session = await self.sessions.update(
                                session,
                                provider=route.provider.name,
                                provider_model=route.provider_model,
                                clear_provider_session=True,
                            )
                        async with self.scheduler.slot(route.provider.name):
                            async for event in route.provider.stream(
                                session.provider_session_id,
                                route.provider_model,
                                messages,
                                options,
                            ):
                                if event.session_id:
                                    session = await self.sessions.update(
                                        session, provider_session_id=event.session_id
                                    )
                                if event.response is not None:
                                    session = await self.sessions.update(
                                        session,
                                        provider_session_id=event.response.provider_session_id,
                                    )
                                if event.type == "delta" and event.text:
                                    emitted = True
                                yield event
                        logger.info(
                            "provider stream completed request_id=%s provider=%s model=%s "
                            "session_id=%s duration_ms=%.1f status=completed",
                            options.get("request_id", "-"),
                            route.provider.name,
                            route.public_model,
                            session.gateway_session_id,
                            (time.monotonic() - started) * 1000,
                        )
                        return
                    except ProviderError as exc:
                        last_error = exc
                        if emitted or existing is not None or not exc.retryable:
                            raise
                if last_error is not None:
                    raise last_error
            except BaseException:
                if created and not emitted:
                    await self.sessions.storage.delete(session.gateway_session_id)
                raise

        return session.gateway_session_id, generate()

    async def _routes(
        self,
        *,
        model: str,
        gateway_session_id: str | None,
        allow_fallback: bool | None,
        side_effects: bool,
    ) -> tuple[ProviderSession | None, list[Route]]:
        if gateway_session_id:
            session = await self.sessions.require_compatible(gateway_session_id, model)
            return session, [
                self.policy.pinned(session.provider, session.model, session.provider_model)
            ]
        fallback = self.config.routing.fallback if allow_fallback is None else allow_fallback
        return None, self.policy.candidates(
            model,
            allow_fallback=fallback,
            side_effects=side_effects,
        )

    async def _persist_success(
        self,
        existing: ProviderSession | None,
        requested_model: str,
        route: Route,
        response: ProviderResponse,
    ) -> ProviderSession:
        if existing is not None:
            return await self.sessions.update(
                existing, provider_session_id=response.provider_session_id
            )
        return await self.sessions.create(
            provider=route.provider.name,
            model=requested_model,
            provider_model=route.provider_model,
            provider_session_id=response.provider_session_id,
        )

    @staticmethod
    def _validate_capability(route: Route, agent_task: bool) -> None:
        capabilities = route.provider.capabilities
        if agent_task and not capabilities.filesystem_agent:
            raise invalid_request(
                f"Provider '{route.provider.name}' does not support filesystem agent tasks.",
                code="unsupported_provider_capability",
            )
        if not agent_task and not capabilities.chat:
            raise invalid_request(
                f"Provider '{route.provider.name}' does not support chat.",
                code="unsupported_provider_capability",
            )

    @staticmethod
    async def _require_available(route: Route) -> None:
        if await route.provider.is_available():
            return
        if route.provider.is_installed() and not await route.provider.is_authenticated():
            raise provider_not_authenticated(route.provider.name)
        raise provider_unavailable(route.provider.name)

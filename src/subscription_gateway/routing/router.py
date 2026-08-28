"""Execution engine combining routes, fallback, sessions, and scheduling."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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
        if gateway_session_id is not None:
            async with self.sessions.serialized(gateway_session_id):
                return await self._complete(
                    model=model,
                    messages=messages,
                    options=options,
                    gateway_session_id=gateway_session_id,
                    allow_fallback=allow_fallback,
                    agent_task=agent_task,
                )
        return await self._complete(
            model=model,
            messages=messages,
            options=options,
            gateway_session_id=None,
            allow_fallback=allow_fallback,
            agent_task=agent_task,
        )

    async def _complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any],
        gateway_session_id: str | None,
        allow_fallback: bool | None,
        agent_task: bool,
    ) -> GatewayResult:
        session_kind: Literal["chat", "agent"] = "agent" if agent_task else "chat"
        working_directory: str | None = None
        if agent_task:
            raw_cwd = options.get("cwd")
            if not isinstance(raw_cwd, str) or not raw_cwd:
                raise invalid_request(
                    "Agent tasks require an absolute working directory.",
                    code="invalid_agent_working_directory",
                )
            raw_path = Path(raw_cwd)
            if not raw_path.is_absolute():
                raise invalid_request(
                    "Agent tasks require an absolute working directory.",
                    code="invalid_agent_working_directory",
                )
            try:
                cwd = await asyncio.to_thread(raw_path.resolve, strict=True)
            except (OSError, RuntimeError) as exc:
                raise invalid_request(
                    "Agent working directory does not exist or cannot be resolved.",
                    code="invalid_agent_working_directory",
                ) from exc
            if not await asyncio.to_thread(cwd.is_dir):
                raise invalid_request(
                    "Agent tasks require an absolute working directory.",
                    code="invalid_agent_working_directory",
                )
            working_directory = str(cwd)
        permissions: Literal["read-only", "workspace-write"] = (
            "workspace-write"
            if agent_task and options.get("permissions") == "workspace-write"
            else "read-only"
        )
        existing, routes = await self._routes(
            model=model,
            gateway_session_id=gateway_session_id,
            allow_fallback=allow_fallback,
            side_effects=(
                agent_task
                and options.get("permissions") == "workspace-write"
                and not options.get("allow_write_fallback", False)
            ),
            session_kind=session_kind,
            working_directory=working_directory,
            permissions=permissions,
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
                session = await self._persist_success(
                    existing,
                    model,
                    route,
                    response,
                    session_kind=session_kind,
                    working_directory=working_directory,
                    permissions=permissions,
                )
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
                if existing is not None or not self._is_retryable(route, exc):
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
        existing, initial_routes = await self._routes(
            model=model,
            gateway_session_id=gateway_session_id,
            allow_fallback=allow_fallback,
            side_effects=False,
        )
        created = existing is None
        session = existing or await self.sessions.create(
            provider=initial_routes[0].provider.name,
            model=model,
            provider_model=initial_routes[0].provider_model,
        )

        async def generate() -> AsyncIterator[ProviderEvent]:
            nonlocal session
            async with self.sessions.serialized(session.gateway_session_id):
                routes = initial_routes
                if not created:
                    locked_session, routes = await self._routes(
                        model=model,
                        gateway_session_id=session.gateway_session_id,
                        allow_fallback=allow_fallback,
                        side_effects=False,
                    )
                    if locked_session is None:  # pragma: no cover - defensive invariant
                        raise RuntimeError("existing session disappeared while locked")
                    session = locked_session
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
                                            provider_session_id=(
                                                event.response.provider_session_id
                                            ),
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
                            if emitted or not created or not self._is_retryable(route, exc):
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
        session_kind: Literal["chat", "agent"] = "chat",
        working_directory: str | None = None,
        permissions: Literal["read-only", "workspace-write"] = "read-only",
    ) -> tuple[ProviderSession | None, list[Route]]:
        if gateway_session_id:
            session = await self.sessions.require_compatible(
                gateway_session_id,
                model,
                session_kind=session_kind,
                working_directory=working_directory,
                permissions=permissions,
            )
            return session, [
                self.policy.pinned(session.provider, session.model, session.provider_model)
            ]
        fallback = self.config.routing.fallback if allow_fallback is None else allow_fallback
        return None, self.policy.candidates(
            model,
            allow_fallback=fallback,
            side_effects=side_effects,
            filesystem_agent=session_kind == "agent",
        )

    async def _persist_success(
        self,
        existing: ProviderSession | None,
        requested_model: str,
        route: Route,
        response: ProviderResponse,
        *,
        session_kind: Literal["chat", "agent"],
        working_directory: str | None,
        permissions: Literal["read-only", "workspace-write"],
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
            session_kind=session_kind,
            working_directory=working_directory,
            permissions=permissions,
        )

    @staticmethod
    def _is_retryable(route: Route, exc: ProviderError) -> bool:
        """A model the caller named and the runtime rejected is a request error,
        not a transient failure: no other provider can supply that model."""

        if exc.code == "model_not_available" and route.explicit_model:
            return False
        return exc.retryable

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

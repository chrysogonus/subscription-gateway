"""FastAPI application factory."""

from __future__ import annotations

import hmac
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from subscription_gateway import __version__
from subscription_gateway.api import agents, chat, health, models, responses
from subscription_gateway.config import GatewayConfig, load_config, secret_value
from subscription_gateway.errors import GatewayError
from subscription_gateway.logging import configure_logging
from subscription_gateway.providers.base import Provider
from subscription_gateway.providers.registry import ProviderRegistry
from subscription_gateway.queue.scheduler import ProviderScheduler
from subscription_gateway.routing.router import GatewayEngine
from subscription_gateway.sessions.manager import SessionManager
from subscription_gateway.sessions.storage import SQLiteSessionStorage

logger = logging.getLogger(__name__)


def create_app(
    config: GatewayConfig | None = None,
    *,
    providers: dict[str, Provider] | None = None,
) -> FastAPI:
    gateway_config = config or load_config()
    configure_logging(gateway_config.logging)
    storage = SQLiteSessionStorage(gateway_config.storage.sqlite_path)
    sessions = SessionManager(
        storage,
        session_retention_days=gateway_config.storage.session_retention_days,
    )
    registry = ProviderRegistry(gateway_config, providers)
    limits = {
        name: getattr(gateway_config.providers, name).max_concurrent
        if hasattr(gateway_config.providers, name)
        else 1
        for name in registry.providers
    }
    scheduler = ProviderScheduler(limits)
    engine = GatewayEngine(gateway_config, registry, sessions, scheduler)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await storage.initialize()
        await sessions.cleanup_expired(force=True)
        yield
        await storage.close()

    application = FastAPI(
        title="Subscription LLM Gateway",
        version=__version__,
        lifespan=lifespan,
    )
    application.state.config = gateway_config
    application.state.storage = storage
    application.state.sessions = sessions
    application.state.registry = registry
    application.state.scheduler = scheduler
    application.state.engine = engine

    @application.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.monotonic()
        if request.url.path.startswith("/v1"):
            configured_key = secret_value(gateway_config.server.api_key)
            if configured_key:
                authorization = request.headers.get("authorization", "")
                supplied = (
                    authorization[7:]
                    if authorization.lower().startswith("bearer ")
                    else request.headers.get("x-api-key", "")
                )
                if not hmac.compare_digest(supplied, configured_key):
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error": {
                                "message": "Invalid or missing local gateway API key.",
                                "type": "authentication_error",
                                "code": "invalid_api_key",
                            }
                        },
                        headers={"X-Request-ID": request_id},
                    )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "http request method=%s path=%s request_id=%s duration_ms=%.1f status=%d",
            request.method,
            request.url.path,
            request_id,
            (time.monotonic() - started) * 1000,
            response.status_code,
        )
        return response

    @application.exception_handler(GatewayError)
    async def gateway_error_handler(_: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.as_dict())

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": "Invalid request body.",
                    "type": "invalid_request",
                    "code": "request_validation_error",
                    "details": jsonable_encoder(exc.errors()),
                }
            },
        )

    application.include_router(health.router)
    application.include_router(models.router)
    application.include_router(chat.router)
    application.include_router(responses.router)
    application.include_router(agents.router)
    return application


def __getattr__(name: str) -> FastAPI:
    """Build the ASGI app on first access, not on import.

    `uvicorn subscription_gateway.main:app` still resolves. Constructing it
    eagerly meant that merely importing this module loaded and validated the
    configuration, so `subscription-gateway --version` crashed in any
    environment whose config was incomplete -- the container being the one that
    matters, since its ENV asks for a non-loopback bind with no API key yet.
    """

    if name == "app":
        return create_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

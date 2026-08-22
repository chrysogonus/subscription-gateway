"""Liveness and provider readiness endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, Any]:
    statuses = await request.app.state.registry.statuses()
    usable = any(item.available for item in statuses)
    if not usable:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if usable else "not_ready",
        "providers": {
            item.name: {
                "installed": item.installed,
                "authenticated": item.authenticated,
                "available": item.available,
            }
            for item in statuses
        },
    }

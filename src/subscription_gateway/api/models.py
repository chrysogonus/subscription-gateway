"""OpenAI-compatible model discovery."""

from __future__ import annotations

from fastapi import APIRouter, Request

from subscription_gateway.compat.openai_models import model_list

router = APIRouter(prefix="/v1")


@router.get("/models")
async def list_models(request: Request) -> dict[str, object]:
    models = await request.app.state.registry.available_models()
    return model_list(models)

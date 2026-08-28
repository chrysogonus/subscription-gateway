"""Gateway-native filesystem agent endpoint."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from subscription_gateway.api.chat import requested_session
from subscription_gateway.config import secret_value
from subscription_gateway.errors import agent_permission_error

router = APIRouter(prefix="/v1")


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    prompt: str
    cwd: Path
    permissions: Literal["read-only", "workspace-write"] = "read-only"
    gateway_session_id: str | None = None
    fallback: bool = False


def validate_agent_cwd(requested: Path, allowed: list[Path], allow_outside: bool) -> Path:
    try:
        candidate = requested.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise agent_permission_error(
            f"Agent cwd does not exist or cannot be resolved: {requested}"
        ) from exc
    if not candidate.is_dir():
        raise agent_permission_error(f"Agent cwd is not a directory: {candidate}")
    if allow_outside:
        return candidate
    roots = [root.expanduser().resolve(strict=False) for root in allowed]
    if not any(candidate == root or root in candidate.parents for root in roots):
        raise agent_permission_error(
            f"Agent cwd is outside configured allowed_directories: {candidate}"
        )
    return candidate


@router.post("/agents/run")
async def run_agent(
    body: AgentRunRequest,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    config = request.app.state.config
    if not secret_value(config.server.api_key):
        raise agent_permission_error(
            "Filesystem agent requests require a configured local gateway API key."
        )
    cwd = validate_agent_cwd(
        body.cwd,
        config.agent.allowed_directories,
        config.agent.allow_outside_directories,
    )
    allow_write_fallback = (
        body.permissions == "workspace-write"
        and body.fallback
        and config.agent.allow_write_fallback
    )
    result = await request.app.state.engine.complete(
        model=body.model,
        messages=[{"role": "user", "content": body.prompt}],
        options={
            "cwd": str(cwd),
            "permissions": body.permissions,
            "allow_write_fallback": allow_write_fallback,
            "request_id": request.state.request_id,
        },
        gateway_session_id=requested_session(request, body.gateway_session_id),
        allow_fallback=body.fallback,
        agent_task=True,
    )
    response.headers["X-Gateway-Session"] = result.gateway_session_id
    response.headers["X-Gateway-Provider"] = result.provider
    response.headers["X-Gateway-Model"] = result.executed_model
    return {
        "id": f"agent_{uuid.uuid4().hex}",
        "model": body.model,
        "status": "completed",
        "output": result.response.text,
        "session_id": result.gateway_session_id,
        "provider": result.provider,
    }

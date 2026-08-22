"""Responses API text subset."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from subscription_gateway.api.chat import requested_session
from subscription_gateway.compat.openai_responses import ResponsesRequest, responses_response
from subscription_gateway.compat.streaming import sse_done, sse_json
from subscription_gateway.errors import GatewayError

router = APIRouter(prefix="/v1")


@router.post("/responses", response_model=None)
async def create_response(
    body: ResponsesRequest,
    request: Request,
    response: Response,
) -> dict[str, Any] | StreamingResponse:
    body.validate_supported()
    session_id = requested_session(request, body.session_id())
    options = {
        "max_tokens": body.max_output_tokens,
        "temperature": body.temperature,
        "request_id": request.state.request_id,
    }
    if body.stream:
        gateway_session_id, events = await request.app.state.engine.create_stream(
            model=body.model,
            messages=body.messages(),
            options=options,
            gateway_session_id=session_id,
        )
        return StreamingResponse(
            _responses_stream(events, model=body.model),
            media_type="text/event-stream",
            headers={
                "X-Gateway-Session": gateway_session_id,
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    result = await request.app.state.engine.complete(
        model=body.model,
        messages=body.messages(),
        options=options,
        gateway_session_id=session_id,
    )
    response.headers["X-Gateway-Session"] = result.gateway_session_id
    response.headers["X-Gateway-Provider"] = result.provider
    response.headers["X-Gateway-Model"] = result.executed_model
    return responses_response(
        result.response,
        model=body.model,
        gateway_session_id=result.gateway_session_id,
    )


async def _responses_stream(events: AsyncIterator[Any], *, model: str) -> AsyncIterator[bytes]:
    response_id = f"resp_{uuid.uuid4().hex}"
    created_at = int(time.time())
    yield sse_json(
        {
            "type": "response.created",
            "response": {
                "id": response_id,
                "object": "response",
                "created_at": created_at,
                "status": "in_progress",
                "model": model,
            },
        }
    )
    full_text: list[str] = []
    try:
        async for event in events:
            if event.type == "delta" and event.text:
                full_text.append(event.text)
                yield sse_json(
                    {
                        "type": "response.output_text.delta",
                        "response_id": response_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": event.text,
                    }
                )
        yield sse_json(
            {
                "type": "response.completed",
                "response": {
                    "id": response_id,
                    "object": "response",
                    "created_at": created_at,
                    "status": "completed",
                    "model": model,
                    "output_text": "".join(full_text),
                },
            }
        )
    except GatewayError as exc:
        yield sse_json({"type": "error", **exc.as_dict()})
    finally:
        yield sse_done()

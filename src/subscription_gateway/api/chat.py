"""OpenAI-compatible Chat Completions endpoint."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from subscription_gateway.compat.openai_chat import (
    ChatCompletionRequest,
    chat_chunk,
    chat_completion_response,
)
from subscription_gateway.compat.streaming import sse_done, sse_json
from subscription_gateway.errors import GatewayError, invalid_request

router = APIRouter(prefix="/v1")


def requested_session(request: Request, body_session: str | None) -> str | None:
    header_session = request.headers.get("x-gateway-session")
    if body_session and header_session and body_session != header_session:
        raise invalid_request(
            "X-Gateway-Session and gateway_session_id must match when both are supplied.",
            code="conflicting_session_ids",
        )
    return header_session or body_session


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    body: ChatCompletionRequest,
    request: Request,
    response: Response,
) -> dict[str, Any] | StreamingResponse:
    body.validate_supported()
    session_id = requested_session(request, body.gateway_session_id)
    messages = [message.model_dump() for message in body.messages]
    if body.stream:
        stream_options = {**body.provider_options(), "request_id": request.state.request_id}
        gateway_session_id, events = await request.app.state.engine.create_stream(
            model=body.model,
            messages=messages,
            options=stream_options,
            gateway_session_id=session_id,
        )
        return StreamingResponse(
            _chat_stream(events, model=body.model),
            media_type="text/event-stream",
            headers={
                "X-Gateway-Session": gateway_session_id,
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    result = await request.app.state.engine.complete(
        model=body.model,
        messages=messages,
        options={**body.provider_options(), "request_id": request.state.request_id},
        gateway_session_id=session_id,
    )
    response.headers["X-Gateway-Session"] = result.gateway_session_id
    return chat_completion_response(
        result.response,
        model=body.model,
        gateway_session_id=result.gateway_session_id,
    )


async def _chat_stream(events: AsyncIterator[Any], *, model: str) -> AsyncIterator[bytes]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    yield sse_json(
        chat_chunk(
            completion_id=completion_id,
            model=model,
            created=created,
            delta={"role": "assistant", "content": ""},
        )
    )
    try:
        async for event in events:
            if event.type == "delta" and event.text:
                yield sse_json(
                    chat_chunk(
                        completion_id=completion_id,
                        model=model,
                        created=created,
                        delta={"content": event.text},
                    )
                )
        yield sse_json(
            chat_chunk(
                completion_id=completion_id,
                model=model,
                created=created,
                delta={},
                finish_reason="stop",
            )
        )
    except GatewayError as exc:
        yield sse_json(exc.as_dict())
    finally:
        yield sse_done()

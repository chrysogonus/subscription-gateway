"""A deliberately small Responses API compatibility subset."""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from subscription_gateway.compat.openai_chat import ChatMessage
from subscription_gateway.errors import invalid_request
from subscription_gateway.providers.base import ProviderResponse


class ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    input: str | list[ChatMessage]
    instructions: str | None = None
    stream: bool = False
    max_output_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = None
    tools: list[dict[str, Any]] | None = None
    previous_response_id: str | None = None
    metadata: dict[str, Any] | None = None
    gateway_session_id: str | None = None

    def messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if self.instructions:
            messages.append({"role": "developer", "content": self.instructions})
        if isinstance(self.input, str):
            messages.append({"role": "user", "content": self.input})
        else:
            messages.extend(message.model_dump() for message in self.input)
        return messages

    def session_id(self) -> str | None:
        if self.gateway_session_id:
            return self.gateway_session_id
        if self.metadata:
            value = self.metadata.get("gateway_session_id")
            return str(value) if value else None
        return None

    def validate_supported(self) -> None:
        if self.tools is not None or self.previous_response_id is not None:
            raise invalid_request(
                "Responses tools and previous_response_id are not supported; use "
                "X-Gateway-Session for continuation.",
                code="unsupported_feature",
            )


def responses_response(
    response: ProviderResponse,
    *,
    model: str,
    gateway_session_id: str,
    response_id: str | None = None,
    created_at: int | None = None,
) -> dict[str, Any]:
    item_id = f"msg_{uuid.uuid4().hex}"
    return {
        "id": response_id or f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": created_at or int(time.time()),
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": item_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": response.text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": response.text,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.total_tokens,
        },
        "gateway_session_id": gateway_session_id,
    }

"""Chat Completions request models and deterministic prompt conversion."""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from subscription_gateway.errors import invalid_request
from subscription_gateway.providers.base import ProviderResponse


class TextContentPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    text: str


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["system", "developer", "user", "assistant"]
    content: str | list[TextContentPart]
    name: str | None = None

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "\n".join(part.text for part in self.content)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    max_completion_tokens: int | None = Field(default=None, gt=0)
    stop: str | list[str] | None = None
    user: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
    gateway_session_id: str | None = None

    def provider_options(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_completion_tokens or self.max_tokens,
            "stop": self.stop,
        }

    def validate_supported(self) -> None:
        if self.tools is not None or self.tool_choice is not None:
            raise invalid_request(
                "OpenAI tool calls are not supported by this agent-runtime gateway prototype.",
                code="unsupported_feature",
            )


def messages_to_prompt(messages: list[dict[str, Any]] | list[ChatMessage]) -> str:
    """Render roles explicitly so provider agent runtimes receive deterministic context."""

    rendered: list[str] = []
    for message in messages:
        role: str
        if isinstance(message, ChatMessage):
            role = message.role
            content = message.text()
        else:
            role = str(message.get("role", "user"))
            raw_content = message.get("content", "")
            if isinstance(raw_content, str):
                content = raw_content
            elif isinstance(raw_content, list):
                content = "\n".join(
                    str(part.get("text", ""))
                    for part in raw_content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            else:
                content = str(raw_content)
        rendered.append(f"[{role.upper()}]\n{content}")
    return "\n\n".join(rendered)


def chat_completion_response(
    response: ProviderResponse,
    *,
    model: str,
    gateway_session_id: str,
    completion_id: str | None = None,
    created: int | None = None,
) -> dict[str, Any]:
    return {
        "id": completion_id or f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created or int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response.text},
                "finish_reason": response.finish_reason,
            }
        ],
        "usage": response.usage.openai_dict(),
        "gateway_session_id": gateway_session_id,
    }


def chat_chunk(
    *,
    completion_id: str,
    model: str,
    created: int,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }

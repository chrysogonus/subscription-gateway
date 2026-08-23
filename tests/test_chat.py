from __future__ import annotations

import json
from collections.abc import AsyncIterator

from conftest import FakeProvider
from fastapi.testclient import TestClient

from subscription_gateway.config import GatewayConfig
from subscription_gateway.errors import ProviderError
from subscription_gateway.main import create_app
from subscription_gateway.providers.base import ProviderEvent


def test_chat_completion_and_session(client: TestClient, fake_codex: FakeProvider) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "codex/gpt-5.6-sol",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"] == {
        "role": "assistant",
        "content": "mock answer",
    }
    assert payload["usage"]["total_tokens"] == 6
    assert response.headers["x-gateway-session"] == payload["gateway_session_id"]
    assert fake_codex.calls[0]["model"] == "gpt-5.6-sol"


def test_session_continuation(client: TestClient, fake_codex: FakeProvider) -> None:
    first = client.post(
        "/v1/chat/completions",
        json={
            "model": "codex/gpt-5.6-sol",
            "messages": [{"role": "user", "content": "One"}],
        },
    )
    session = first.headers["x-gateway-session"]
    second = client.post(
        "/v1/chat/completions",
        headers={"X-Gateway-Session": session},
        json={
            "model": "codex/gpt-5.6-sol",
            "messages": [{"role": "user", "content": "Two"}],
        },
    )
    assert second.status_code == 200
    assert fake_codex.calls[1]["session_id"] == "codex-thread"


def test_streaming_chat_sse(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "codex/gpt-5.6-sol",
            "stream": True,
            "messages": [{"role": "user", "content": "Hello"}],
        },
    ) as response:
        lines = [line for line in response.iter_lines() if line]
    assert response.status_code == 200
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line[6:]) for line in lines[:-1]]
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert (
        "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks)
        == "mock answer"
    )
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_streaming_provider_error_is_sse_and_terminates(gateway_config: GatewayConfig) -> None:
    class BrokenStreamProvider(FakeProvider):
        async def stream(
            self,
            session_id: str | None,
            model: str,
            messages: list[dict[str, object]],
            options: dict[str, object],
        ) -> AsyncIterator[ProviderEvent]:
            yield ProviderEvent(type="delta", text="partial")
            raise ProviderError(
                "stream failed",
                error_type="provider_protocol_error",
                code="provider_stream_failed",
                status_code=502,
                provider="codex",
            )

    with TestClient(
        create_app(gateway_config, providers={"codex": BrokenStreamProvider()})
    ) as test_client:
        response = test_client.post(
            "/v1/chat/completions",
            json={
                "model": "codex/gpt-5.6-sol",
                "stream": True,
                "messages": [{"role": "user", "content": "x"}],
            },
        )
    assert response.status_code == 200
    assert '"code":"provider_stream_failed"' in response.text
    assert response.text.rstrip().endswith("data: [DONE]")


def test_responses_subset(client: TestClient) -> None:
    response = client.post(
        "/v1/responses",
        json={"model": "codex/gpt-5.6-sol", "input": "Hello"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "response"
    assert payload["output_text"] == "mock answer"
    assert payload["output"][0]["content"][0]["type"] == "output_text"


def test_responses_streaming_sse(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/v1/responses",
        json={"model": "codex/gpt-5.6-sol", "input": "Hello", "stream": True},
    ) as response:
        lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert response.headers["x-gateway-session"]
    assert lines[-1] == "data: [DONE]"
    events = [json.loads(line[6:]) for line in lines[:-1]]
    assert events[0]["type"] == "response.created"
    assert events[0]["response"]["status"] == "in_progress"
    deltas = [event for event in events if event["type"] == "response.output_text.delta"]
    assert "".join(event["delta"] for event in deltas) == "mock answer"
    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["output_text"] == "mock answer"


def test_responses_streaming_error_is_sse_and_terminates(gateway_config: GatewayConfig) -> None:
    class BrokenStreamProvider(FakeProvider):
        async def stream(
            self,
            session_id: str | None,
            model: str,
            messages: list[dict[str, object]],
            options: dict[str, object],
        ) -> AsyncIterator[ProviderEvent]:
            yield ProviderEvent(type="delta", text="partial")
            raise ProviderError(
                "stream failed",
                error_type="provider_protocol_error",
                code="provider_stream_failed",
                status_code=502,
                provider="codex",
            )

    with TestClient(
        create_app(gateway_config, providers={"codex": BrokenStreamProvider()})
    ) as test_client:
        response = test_client.post(
            "/v1/responses",
            json={"model": "codex/gpt-5.6-sol", "input": "x", "stream": True},
        )

    assert response.status_code == 200
    assert '"code":"provider_stream_failed"' in response.text
    assert response.text.rstrip().endswith("data: [DONE]")


def test_responses_rejects_unsupported_features(client: TestClient) -> None:
    response = client.post(
        "/v1/responses",
        json={
            "model": "codex/gpt-5.6-sol",
            "input": "x",
            "previous_response_id": "resp_1",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_feature"


def test_responses_instructions_become_a_developer_message(
    client: TestClient, fake_codex: FakeProvider
) -> None:
    response = client.post(
        "/v1/responses",
        json={
            "model": "codex/gpt-5.6-sol",
            "input": [{"role": "user", "content": "Hello"}],
            "instructions": "Be terse.",
        },
    )

    assert response.status_code == 200
    messages = fake_codex.calls[0]["messages"]
    assert messages[0] == {"role": "developer", "content": "Be terse."}
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Hello"


def test_invalid_model_is_normalized(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={"model": "raw/fake", "messages": [{"role": "user", "content": "x"}]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "model_not_available"


def test_unavailable_provider_is_normalized(gateway_config: GatewayConfig) -> None:
    with TestClient(
        create_app(gateway_config, providers={"codex": FakeProvider(available=False)})
    ) as test_client:
        response = test_client.post(
            "/v1/chat/completions",
            json={
                "model": "codex/gpt-5.6-sol",
                "messages": [{"role": "user", "content": "x"}],
            },
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_unauthenticated_provider_is_distinguished(gateway_config: GatewayConfig) -> None:
    class UnauthenticatedProvider(FakeProvider):
        def is_installed(self) -> bool:
            return True

        async def is_authenticated(self) -> bool:
            return False

    provider = UnauthenticatedProvider(available=False)
    with TestClient(create_app(gateway_config, providers={"codex": provider})) as test_client:
        response = test_client.post(
            "/v1/chat/completions",
            json={
                "model": "codex/gpt-5.6-sol",
                "messages": [{"role": "user", "content": "x"}],
            },
        )
    assert response.status_code == 503
    assert response.json()["error"]["type"] == "provider_not_authenticated"


def test_tools_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "codex/gpt-5.6-sol",
            "messages": [{"role": "user", "content": "x"}],
            "tools": [{"type": "function", "function": {"name": "x"}}],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_feature"


def test_local_api_authentication(gateway_config: GatewayConfig) -> None:
    data = gateway_config.model_dump(mode="python")
    data["server"]["api_key"] = "local-secret"
    secured = GatewayConfig.model_validate(data)
    with TestClient(create_app(secured, providers={"codex": FakeProvider()})) as test_client:
        denied = test_client.get("/v1/models")
        allowed = test_client.get("/v1/models", headers={"Authorization": "Bearer local-secret"})
        health = test_client.get("/health")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "invalid_api_key"
    assert allowed.status_code == 200
    assert health.status_code == 200

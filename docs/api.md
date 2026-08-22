# API

[← Documentation index](README.md)

The base URL is `http://127.0.0.1:11435/v1`.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness. Healthy even when no provider is installed. |
| `GET /ready` | Readiness. `503` while no provider is available. |
| `GET /v1/models` | Catalogued models from available providers. |
| `POST /v1/chat/completions` | OpenAI Chat Completions, with coarse SSE streaming. |
| `POST /v1/responses` | A documented subset of the Responses API. |
| `POST /v1/agents/run` | Filesystem agent runs, with explicit permissions. |

The examples below send `Authorization: Bearer local`, which matches the Compose default. Drop
the header when running `subscription-gateway serve` directly with no key configured, or change
the value to the configured token. See
[local API authentication](configuration.md#local-api-authentication).

## Models

```bash
curl http://127.0.0.1:11435/v1/models \
  -H 'Authorization: Bearer local'
```

## Chat completions

Run Codex:

```bash
curl http://127.0.0.1:11435/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer local' \
  -d '{
    "model": "codex/gpt-5.6-sol",
    "messages": [
      {"role": "user", "content": "Explain Linux namespaces."}
    ]
  }'
```

Run Claude Code:

```bash
curl http://127.0.0.1:11435/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer local' \
  -d '{
    "model": "claude-code/opus",
    "messages": [
      {"role": "user", "content": "Explain Linux namespaces."}
    ]
  }'
```

## Streaming

```bash
curl -N http://127.0.0.1:11435/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer local' \
  -d '{
    "model": "subscription/auto",
    "stream": true,
    "messages": [{"role": "user", "content": "Write a haiku."}]
  }'
```

The current provider adapters return a valid coarse stream when a runtime does not expose stable
token deltas: the full final assistant message is sent as one content chunk, followed by the final
chunk and `[DONE]`. Disconnecting cancels and reaps the child process.

## Responses API

The implemented Responses API subset accepts plain text or message-list `input`, optional
`instructions`, `max_output_tokens`, `temperature`, and `stream`. Tool calls, images,
`previous_response_id`, hosted tools, and raw provider-specific reasoning objects are rejected
explicitly rather than simulated.

```bash
curl http://127.0.0.1:11435/v1/responses \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer local' \
  -d '{"model":"subscription/auto","input":"Explain cgroups briefly."}'
```

Sampling fields (`temperature`, `top_p`), token limits, and stop sequences are accepted so common
clients can connect, but the current agent CLIs do not provide stable equivalents and may ignore
them. This is another reason the gateway does not describe itself as a raw model API.

## Python OpenAI client

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:11435/v1",
    # The configured GATEWAY_API_KEY. Any non-empty value works only when the
    # gateway runs with no key configured.
    api_key="local",
)

response = client.chat.completions.create(
    model="codex/gpt-5.6-sol",
    messages=[
        {
            "role": "user",
            "content": "Write a Rust implementation of an LRU cache.",
        }
    ],
)

print(response.choices[0].message.content)
```

## Sessions

Every successful request creates a gateway UUID and returns it in both the
`X-Gateway-Session` response header and the `gateway_session_id` response field. Continue a
provider thread by sending the header back:

```bash
curl http://127.0.0.1:11435/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer local' \
  -H 'X-Gateway-Session: <uuid>' \
  -d '{
    "model": "codex/gpt-5.6-sol",
    "messages": [{"role": "user", "content": "Now compare them with cgroups."}]
  }'
```

Codex is resumed with `codex exec resume <thread-id>` and Claude with `--resume <session-id>` when
the runtime returned a session identifier. Sessions are pinned to their provider: cross-provider
fallback is intentionally disabled on continuation to prevent incoherent context.

Responses also carry `X-Gateway-Provider` and `X-Gateway-Model` headers naming the provider and
model that actually ran, which is worth checking when `subscription/auto` may have fallen back.

### Role handling

Messages use deterministic role markers (`[SYSTEM]`, `[DEVELOPER]`, `[USER]`, `[ASSISTANT]`).
Those markers preserve ordering, but provider runtimes may still add their own instructions,
tools, agent loops, filesystem context, permission handling, compaction, and model-specific
behavior. OpenAI `system` and `developer` roles therefore cannot be reproduced exactly.

## Agent endpoint

`POST /v1/agents/run` exposes the filesystem-agent nature explicitly:

```bash
curl http://127.0.0.1:11435/v1/agents/run \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer local' \
  -d '{
    "model": "codex/gpt-5.6-sol",
    "prompt": "Find the failing tests and explain the cause.",
    "cwd": "/home/user/workspace/project",
    "permissions": "read-only"
  }'
```

Only `read-only` and `workspace-write` are accepted. `cwd` must exist, resolve without symlink
escape, and be inside `agent.allowed_directories` unless the user explicitly enables the broader
configuration. Unrestricted access is not implemented. Write-capable fallback requires both
request-level `fallback: true` and `agent.allow_write_fallback: true`.

In Docker, use the **container** path rather than the host path:

```json
{
  "cwd": "/home/gateway/workspace/my-project",
  "permissions": "workspace-write"
}
```

# Subscription LLM Gateway

A local interoperability gateway that exposes models available through the user's already
authenticated Codex and Claude Code clients through a small OpenAI-compatible HTTP API.

```text
OpenAI-compatible applications
             |
             v
 http://127.0.0.1:11435/v1
             |
             v
 Subscription LLM Gateway
       |             |
       v             v
  codex exec     claude --print
  (ChatGPT auth) (Claude auth)
```

Inference is not local. Codex and Claude Code still use OpenAI and Anthropic infrastructure and
remain subject to the user's plan, provider policies, and usage limits.

## What it is—and what it is not

This project is a personal, localhost-first compatibility layer for applications that can use a
custom OpenAI base URL. It deliberately names models `codex/...` and `claude-code/...` because the
underlying systems are agent runtimes, not raw model APIs.

It is not:

- a local model;
- a replacement for the OpenAI or Anthropic developer APIs;
- a subscription resale, account-sharing, or rate-limit bypass system;
- a credential extraction tool;
- an assertion that an agent-runtime model behaves exactly like a raw provider API model.

The gateway never reads browser cookies, extracts bearer tokens, intercepts provider traffic, or
calls undocumented private endpoints. Authentication stays with the official clients. It stores
only gateway-to-provider session metadata in SQLite, never provider credentials.

## Requirements

- Python 3.12 or newer;
- Codex CLI, authenticated with `codex login`, for `codex/*` models;
- Claude Code, authenticated with `claude auth login`, for `claude-code/*` models.

The server starts even if neither provider is installed. `/health` remains healthy, `/ready`
returns 503, and `/v1/models` returns an empty list in that situation.

## Installation

```bash
git clone <repository-url> subscription-llm-gateway
cd subscription-llm-gateway

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

For development:

```bash
python -m pip install -e '.[dev]'
pytest
```

With `uv`, `uv sync --all-extras` is equivalent and uses the checked-in lock file.

## Starting

```bash
subscription-gateway doctor
subscription-gateway status
subscription-gateway serve
```

The default base URL is `http://127.0.0.1:11435/v1`. The gateway will not bind to a non-loopback
address unless `server.allow_remote: true` and a local API key are both explicitly configured.
This remains a personal gateway; remote multi-user deployment is out of scope.

Copy `config.example.yaml` to `config.yaml` when customization is needed, then run:

```bash
subscription-gateway serve --config ./config.yaml
```

The config path can also be set with `SUBSCRIPTION_GATEWAY_CONFIG`. Supported environment
overrides include `GATEWAY_HOST`, `GATEWAY_PORT`, `GATEWAY_API_KEY`, `GATEWAY_SQLITE_PATH`,
`GATEWAY_LOG_LEVEL`, `GATEWAY_DEBUG_PROMPTS`, `GATEWAY_CODEX_COMMAND`, and
`GATEWAY_CLAUDE_COMMAND`. Values whose names contain `TOKEN`, `KEY`, `SECRET`, or `PASSWORD` are
never emitted by gateway logging.

## Local API authentication

Set a local-only gateway token if desired:

```bash
export GATEWAY_API_KEY=local-secret
subscription-gateway serve
```

Clients then send `Authorization: Bearer local-secret`. This token protects the gateway only and
is never used for Codex or Claude authentication. Without a configured token, localhost requests
are accepted.

## API examples

List usable models:

```bash
curl http://127.0.0.1:11435/v1/models
```

Run Codex:

```bash
curl http://127.0.0.1:11435/v1/chat/completions \
  -H 'Content-Type: application/json' \
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
  -d '{
    "model": "claude-code/opus-5",
    "messages": [
      {"role": "user", "content": "Explain Linux namespaces."}
    ]
  }'
```

Stream Chat Completions-compatible SSE:

```bash
curl -N http://127.0.0.1:11435/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "subscription/auto",
    "stream": true,
    "messages": [{"role": "user", "content": "Write a haiku."}]
  }'
```

The current provider adapters return a valid coarse stream when a runtime does not expose stable
token deltas: the full final assistant message is sent as one content chunk, followed by the final
chunk and `[DONE]`. Disconnecting cancels and reaps the child process.

The implemented Responses API subset accepts plain text or message-list `input`, optional
`instructions`, `max_output_tokens`, `temperature`, and `stream`. Tool calls, images,
`previous_response_id`, hosted tools, and raw provider-specific reasoning objects are rejected
explicitly rather than simulated.

Sampling fields (`temperature`, `top_p`), token limits, and stop sequences are accepted so common
clients can connect, but the current agent CLIs do not provide stable equivalents and may ignore
them. This is another reason the gateway does not describe itself as a raw model API.

```bash
curl http://127.0.0.1:11435/v1/responses \
  -H 'Content-Type: application/json' \
  -d '{"model":"subscription/auto","input":"Explain cgroups briefly."}'
```

### Python OpenAI client

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:11435/v1",
    api_key="local",  # Any non-empty value works when gateway auth is disabled.
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

### OpenWebUI

In OpenWebUI, add an OpenAI-compatible connection:

- URL: `http://127.0.0.1:11435/v1` when OpenWebUI runs natively;
- API key: the configured `GATEWAY_API_KEY`, or any non-empty placeholder if auth is disabled;
- model: select a model returned by `/v1/models`.

If OpenWebUI itself runs in Docker, `127.0.0.1` refers to that container. On Docker Desktop use
`http://host.docker.internal:11435/v1`. On Linux, add an explicit host-gateway mapping or use a
carefully configured local container network. Do not broaden the gateway bind without enabling
its API key.

## Sessions

Every successful request creates a gateway UUID and returns it in both the
`X-Gateway-Session` response header and `gateway_session_id` response field. Continue a provider
thread by sending the header back:

```bash
curl http://127.0.0.1:11435/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Gateway-Session: <uuid>' \
  -d '{
    "model": "codex/gpt-5.6-sol",
    "messages": [{"role": "user", "content": "Now compare them with cgroups."}]
  }'
```

Codex is resumed with `codex exec resume <thread-id>` and Claude with `--resume <session-id>` when
the runtime returned a session identifier. Sessions are pinned to their provider: cross-provider
fallback is intentionally disabled on continuation to prevent incoherent context.

Messages use deterministic role markers (`[SYSTEM]`, `[DEVELOPER]`, `[USER]`, `[ASSISTANT]`).
Those markers preserve ordering, but provider runtimes may still add their own instructions,
tools, agent loops, filesystem context, permission handling, compaction, and model-specific
behavior. OpenAI `system` and `developer` roles therefore cannot be reproduced exactly.

## Agent endpoint

`POST /v1/agents/run` exposes the filesystem-agent nature explicitly:

```bash
curl http://127.0.0.1:11435/v1/agents/run \
  -H 'Content-Type: application/json' \
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

## Routing, fallback, and scheduling

- Explicit `codex/*` and `claude-code/*` aliases route directly.
- `subscription/auto` follows `routing.order` and defaults to Codex.
- Retryable unavailability, temporary, model, usage-limit, and timeout failures may fall back for
  stateless chat requests when enabled.
- Existing sessions never cross providers.
- Write-capable agent operations do not fall back by default.
- Provider semaphores queue excess work; defaults are two Codex and one Claude request.

Unavailable providers are not advertised unless their `advertise_unavailable` setting is true.
This setting affects discovery only; an actual request still returns a normalized error.

## Provider implementation notes

The Codex adapter uses the official documented `codex exec --json` JSONL interface. It captures
`thread.started`, assistant-message, completion, usage, and error events; progress remains separate
from the final answer. Authentication is checked with `codex login status`, and the CLI reuses its
own saved ChatGPT/Codex authentication. See the official [Codex non-interactive mode
documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

The Claude adapter uses `claude --print --output-format json`, checks `claude auth status`, keeps
stdout and stderr separate, and resumes returned session IDs. Subprocess creation uses argument
arrays with no shell. The adapter is isolated behind `Provider`, so a future Claude Agent SDK
implementation can replace it without changing routing or HTTP code.

Configured aliases are not automatic guarantees of account-level model access. If a local client
version or plan does not offer an alias's `provider_model`, the gateway returns
`model_not_available`. Add more aliases under the provider's `models` mapping.

## Docker

The supplied image installs the pinned, tested official Codex and Claude Code clients. Provider
credentials are never copied into an image: Compose mounts the host's existing client state only
at runtime. The HTTP port remains published on `127.0.0.1`, and the container runs as a non-root
user with all Linux capabilities dropped.

First authenticate the official clients on the host and confirm both statuses:

```bash
codex login status
claude auth status
```

Then start the gateway:

```bash
export GATEWAY_UID="$(id -u)"       # Linux; usually 1000
export GATEWAY_API_KEY=local        # Change this if desired
docker compose up --build --detach

docker compose ps
docker compose exec gateway subscription-gateway status
```

The first image build installs Codex and Claude Code and can take several minutes. Subsequent
starts use the cached image:

```bash
docker compose up --detach
```

Test it from the host:

```bash
curl http://127.0.0.1:11435/v1/models \
  -H 'Authorization: Bearer local'
```

Compose defaults are:

- API key: `local`;
- Codex state: `$HOME/.codex` mounted at `/home/gateway/.codex`;
- Claude state: `$HOME/.claude` mounted at `/home/gateway/.claude`;
- Claude user state: `$HOME/.claude.json` mounted at `/home/gateway/.claude.json`;
- agent workspace: `$HOME/workspace` mounted at `/home/gateway/workspace`;
- SQLite metadata: the Docker-managed `gateway-data` volume.

Override host paths or pinned CLI releases through the variables shown in
`.env.docker.example`. Compose automatically reads a file named `.env`, so one option is:

```bash
cp .env.docker.example .env
# Edit .env for this machine, then:
docker compose up --build --detach
```

The provider-state mounts are read-write because the official clients refresh their own sessions
and persist conversation metadata. The gateway still never opens or parses credential files. The
adapters use Codex's `--ignore-user-config` and Claude's `--safe-mode`, so host hooks, plugins, and
MCP configuration are not activated by gateway requests.

Codex can store authentication in an OS keyring instead of `$HOME/.codex/auth.json`. A container
cannot access the host keyring. If `docker compose exec gateway codex login status` is not ready,
configure Codex's supported file credential store on the host and run `codex login` there again.
Claude similarly needs its official local client state under the mounted Claude directory and
`.claude.json` file. Do not copy either credential into the repository or Dockerfile.

For agent requests, use the container path—not the host path:

```json
{
  "cwd": "/home/gateway/workspace/my-project",
  "permissions": "workspace-write"
}
```

Stop the service without deleting its SQLite volume:

```bash
docker compose down
```

## Platform support

Linux is the primary target. The implementation uses `pathlib`, `shutil.which`, argument-array
subprocesses, and cross-platform process termination where practical, so macOS should work.
Windows users should run the first prototype in WSL.

## Development checks

```bash
pytest
ruff check .
mypy src/subscription_gateway
```

Tests use mock providers and mocked process results. They do not require provider installations,
credentials, network access, or subscription usage.

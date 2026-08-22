# Subscription LLM Gateway

A local interoperability gateway that exposes models available through the user's already
authenticated Codex and Claude Code clients through a small OpenAI-compatible HTTP API.

```text
OpenWebUI / OpenAI-compatible applications
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

A `Makefile` wraps the commands used most often. `make help` lists every target;
`make dev` installs the development extras, preferring `uv` and the lock file when `uv`
is installed and falling back to `.venv` and `pip` otherwise.

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

Docker deployments always have a token. Compose sets `GATEWAY_API_KEY: ${GATEWAY_API_KEY:-local}`,
so the key is `local` unless `.env` or the environment overrides it, and requests without the
header are rejected with `invalid_api_key`. Setting the variable to an empty value does not
disable authentication: `${GATEWAY_API_KEY:-local}` treats empty as unset and falls back to
`local`.

## API examples

The examples below send `Authorization: Bearer local`, which matches the Compose default. Drop
the header when running `subscription-gateway serve` directly with no key configured, or change
the value to the configured token.

List usable models:

```bash
curl http://127.0.0.1:11435/v1/models \
  -H 'Authorization: Bearer local'
```

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

Stream Chat Completions-compatible SSE:

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
  -H 'Authorization: Bearer local' \
  -d '{"model":"subscription/auto","input":"Explain cgroups briefly."}'
```

### Python OpenAI client

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:11435/v1",
    api_key="local",  # The configured GATEWAY_API_KEY; any non-empty value works
                      # only when the gateway runs with no key configured.
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

Docker Compose includes a preconfigured OpenWebUI service, but it is optional and is not
deployed unless it is requested. It sits in the Compose `webui` profile, so the gateway can
run on its own for API-only use:

```bash
make up              # gateway only
make up-webui        # gateway and OpenWebUI
```

`make up WEBUI=1` is the same choice spelled as a variable, and the equivalent without
`make` is `docker compose --profile webui up --detach`. To make the choice permanent for
this machine, set `COMPOSE_PROFILES=webui` in `.env`.

With the UI deployed, open `http://127.0.0.1:3001`. On the first visit, create the local
administrator account. The model picker is populated from the gateway's live `/v1/models`
response and shows usable Codex, Claude Code, and routing aliases.

The decision is reversible at any time. `make up-webui` adds the UI container next to an
already running gateway, and `make down` followed by `make up` leaves the gateway running
without it. The `open-webui-data` volume survives either direction, so accounts and chats
return if the UI is redeployed later; `make purge CONFIRM=1` is the explicit way to delete
those volumes.

The Compose connection uses `http://gateway:11435/v1` on the private container network. Ollama is
disabled, so the model picker is not cluttered by an unavailable default backend. OpenWebUI state
is stored in the `open-webui-data` Docker volume. The pinned slim image avoids bundling a large
local embedding model; ordinary chat works normally, while knowledge/RAG features may download
their selected embedding model during the first startup.

OpenWebUI is configured with legacy function calling because Codex and Claude Code are agent
runtimes, not OpenAI tool-calling endpoints. In this mode OpenWebUI performs its compatible
prompt-based tool orchestration and sends ordinary message requests to the gateway. Native
OpenAI `tools` payloads remain rejected by the gateway instead of being silently ignored.

For a separately installed OpenWebUI instance, add an OpenAI-compatible connection:

- URL: `http://127.0.0.1:11435/v1` when OpenWebUI runs natively;
- API key: the configured `GATEWAY_API_KEY`, or any non-empty placeholder if auth is disabled;
- model: select a model returned by `/v1/models`.

If OpenWebUI itself runs in Docker, `127.0.0.1` refers to that container. On Docker Desktop use
`http://host.docker.internal:11435/v1`. On Linux, add an explicit host-gateway mapping or use a
carefully configured local container network. Do not broaden the gateway bind without enabling
its API key.

## Models

Two kinds of model name work. **Catalogued** models are the ones listed in configuration; they are
the only names `/v1/models` can advertise, so they are what a client's model picker shows:

| Model | Runs as |
| --- | --- |
| `codex/gpt-5.6-sol` | `codex --model gpt-5.6-sol` |
| `claude-code/opus` | `claude --model opus` |
| `claude-code/sonnet` | `claude --model sonnet` |
| `claude-code/haiku` | `claude --model haiku` |
| `claude-code/fable` | `claude --model fable` |
| `subscription/auto` | the `default: true` model of the first available provider |

The Claude entries are tier aliases, so they always resolve to the newest model of that tier
without a config change.

**Passthrough** covers everything else: any `codex/<model>` or `claude-code/<model>` that is not
catalogued has its suffix passed to the CLI verbatim.

```bash
curl http://127.0.0.1:11435/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer local' \
  -d '{
    "model": "claude-code/claude-fable-5",
    "messages": [{"role": "user", "content": "Explain Linux namespaces."}]
  }'
```

Four things to know about passthrough:

- Names are validated before reaching the CLI. A name must start with a letter, digit, or
  underscore and may otherwise contain only letters, digits, `.`, `_`, `:`, and `-`. Anything
  else — an empty suffix, a leading `-`, spaces, slashes — is rejected with 404 without starting a
  subprocess.
- Passthrough models cannot appear in `/v1/models`, because neither CLI can enumerate its models.
  OpenWebUI's picker has no free-text field, so passthrough is for API callers. To use a model in
  a UI, add it to `models` in `config.yaml` and it becomes catalogued.
- The Codex adapter runs with `--ignore-user-config`, so model profiles and aliases defined in
  `~/.codex/config.toml` do **not** resolve. Only names the Codex CLI accepts natively work.
- If the runtime rejects the model, the request fails with `model_not_available` rather than
  falling back to another provider.

Responses carry `X-Gateway-Provider` and `X-Gateway-Model` headers naming the provider and model
that actually ran, which is worth checking when `subscription/auto` may have fallen back.

`claude-code/opus-5`, the alias earlier versions shipped, still resolves to `opus` but is no longer
advertised. Sessions started under it keep working. Note that continuing such a session while
sending `claude-code/opus` returns `session_model_mismatch`: the names are compared as strings even
though they select the same model.

## Sessions

Every successful request creates a gateway UUID and returns it in both the
`X-Gateway-Session` response header and `gateway_session_id` response field. Continue a provider
thread by sending the header back:

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

## Routing, fallback, and scheduling

- Explicit `codex/*` and `claude-code/*` aliases route directly.
- `subscription/auto` follows `routing.order` and defaults to Codex. Within a provider it uses the
  model marked `default: true`, or the first configured model when none is marked.
- Retryable unavailability, temporary, usage-limit, and timeout failures may fall back for
  stateless chat requests when enabled.
- A model the caller named explicitly never falls back when the runtime rejects the model itself:
  no other provider can supply that model, and answering from a different one would misattribute
  the reply. `subscription/auto` still falls back, because the caller named no model.
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
`model_not_available`.

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

Then start the gateway, deciding whether the optional chat UI is deployed with it:

```bash
export GATEWAY_API_KEY=local        # Change this if desired

make up                             # gateway only
make up-webui                       # gateway and OpenWebUI

make ps
make docker-status
```

The `make` targets export `GATEWAY_UID` from `id -u` themselves. Without `make`, set it by
hand and select the profile explicitly:

```bash
export GATEWAY_UID="$(id -u)"                          # Linux; usually 1000
docker compose up --build --detach                     # gateway only
docker compose --profile webui up --build --detach     # gateway and OpenWebUI
```

When OpenWebUI is deployed, open the chat UI at `http://127.0.0.1:3001`. Both the UI and gateway
API ports are bound to the host loopback interface. The first OpenWebUI account becomes the local
administrator; keep its credentials private even though the service is not published remotely.

The first image build installs Codex and Claude Code and can take several minutes. Subsequent
starts use the cached image.

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
- OpenWebUI: not deployed unless the `webui` profile is selected; when it is,
  `http://127.0.0.1:3001`, with data in the `open-webui-data` volume;

The container reads `config.yaml` from a read-only mount, which is how the model catalog is
customized in Docker — no environment variable configures models. It defaults to
`./config.example.yaml`, and the `make` targets point it at `./config.yaml` as soon as that file
exists:

```bash
make config          # copy config.example.yaml to config.yaml
$EDITOR config.yaml  # add models under providers.<name>.models
make up
```

Without `make`, set `GATEWAY_CONFIG_FILE` yourself. Point it only at a file that exists: Docker
creates a *directory* for a missing bind source, and the gateway then refuses to start. The
environment variables in `docker-compose.yml` are applied after the file, so `GATEWAY_HOST`,
`GATEWAY_API_KEY`, and `GATEWAY_SQLITE_PATH` still win over anything it sets.

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

Stop the stack without deleting either persistent volume:

```bash
make down
```

`make down` includes the `webui` profile, so it removes the OpenWebUI container as well even
when the last `make up` did not start it.

## Platform support

Linux is the primary target. The implementation uses `pathlib`, `shutil.which`, argument-array
subprocesses, and cross-platform process termination where practical, so macOS should work.
Windows users should run the first prototype in WSL.

## Development checks

```bash
make check          # ruff, mypy, and pytest
```

Individually:

```bash
pytest
ruff check .
mypy src/subscription_gateway
```

## Make targets

`make help` prints the current list. The most useful ones:

| Target | Purpose |
| --- | --- |
| `dev`, `install` | Install with or without development extras |
| `check` | `lint`, `typecheck`, and `test` |
| `test`, `lint`, `fix`, `typecheck` | Individual checks; `fix` applies ruff autofixes and formatting |
| `serve`, `status`, `doctor` | Run the CLI locally, using `./config.yaml` when it exists |
| `config`, `env` | Create `config.yaml` and `.env` from the examples, never overwriting |
| `up`, `up-webui` | Deploy without or with OpenWebUI |
| `down`, `restart`, `ps`, `logs` | Manage the deployed stack |
| `shell`, `docker-status`, `docker-doctor` | Inspect the gateway container |
| `smoke` | Curl `/health` and `/v1/models` against a running gateway |
| `dist`, `clean` | Build the wheel and sdist; remove artifacts and caches |
| `purge CONFIRM=1` | Remove containers and their data volumes (destructive) |

Tests use mock providers and mocked process results. They do not require provider installations,
credentials, network access, or subscription usage.

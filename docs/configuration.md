# Configuration

[← Documentation index](README.md)

The gateway runs with usable defaults and no configuration file. Copy the example when you want
to change something:

```bash
make config           # copies config.example.yaml to config.yaml, never overwriting
$EDITOR config.yaml
make serve            # passes --config ./config.yaml automatically once the file exists
```

Settings are applied in this order, and later sources win:

1. built-in defaults;
2. the YAML file, from `--config PATH` or, without the flag, `SUBSCRIPTION_GATEWAY_CONFIG`;
3. the [environment overrides](#environment-overrides);
4. `serve --host` / `--port`.

A config path that does not exist, a YAML root that is not a mapping, or any invalid value stops
every command with `Configuration error: …` and exit code 2.

## config.yaml reference

[`config.example.yaml`](../config.example.yaml) is the annotated starting point. Every key, with
its default:

```yaml
server:
  host: 127.0.0.1            # loopback: 127.0.0.1, ::1, or localhost
  port: 11435                # 1–65535
  # api_key: local-secret    # local gateway token; unset = no auth on loopback
  allow_remote: false        # required (with api_key) for any non-loopback host

providers:
  codex:
    enabled: true
    command: codex           # executable name or path
    max_concurrent: 2        # 1–32 simultaneous CLI processes
    timeout_seconds: 300     # per CLI run; > 0 and ≤ 3600
    advertise_unavailable: false
    # working_directory: /path/to/dir   # default: your home directory
    models:
      codex/gpt-5.6-sol:
        provider_model: gpt-5.6-sol
        default: true          # subscription/auto uses this model for Codex

  claude:
    enabled: true
    command: claude
    max_concurrent: 1
    timeout_seconds: 300
    advertise_unavailable: false
    # working_directory: /path/to/dir
    models:
      claude-code/opus:
        provider_model: opus
        default: true
      claude-code/sonnet:
        provider_model: sonnet
      claude-code/haiku:
        provider_model: haiku
      claude-code/fable:
        provider_model: fable

routing:
  fallback: true
  order:
    - codex
    - claude

agent:
  allowed_directories:
    - ~/workspace
  allow_outside_directories: false
  allow_write_fallback: false

storage:
  sqlite_path: ~/.local/share/subscription-llm-gateway/gateway.db
  session_retention_days: 30   # 1–3650, or null to keep sessions indefinitely

logging:
  level: INFO
  json: false
  debug_prompts: false
```

### server

| Key | Meaning |
| --- | --- |
| `host` | Bind address. Only `127.0.0.1`, `::1`, and `localhost` count as loopback; any other address, including `0.0.0.0` and `127.0.0.2`, needs `allow_remote: true` and an `api_key`. |
| `port` | Bind port. |
| `api_key` | The local gateway token. See [Local API authentication](#local-api-authentication). An empty string counts as unset. |
| `allow_remote` | Opt-in for non-loopback binds. |

### providers.codex / providers.claude

| Key | Meaning |
| --- | --- |
| `enabled` | `false` hides the provider and makes requests to it fail with `provider_unavailable`. |
| `command` | The CLI to run, looked up on `PATH` once at startup. |
| `max_concurrent` | How many CLI processes may run at once; extra requests wait in a queue. |
| `timeout_seconds` | Limit for one CLI run. A timeout returns `provider_timeout` (504). Login checks use `min(10, timeout_seconds)`. |
| `advertise_unavailable` | List this provider's models in `/v1/models` even when it is not ready. Discovery only; requests still fail with a normal error. |
| `working_directory` | Directory the CLI runs in for chat requests and login checks (`~` is expanded). If it does not exist, requests fail with `provider_unavailable`. Codex chat runs here under `--sandbox read-only`. |
| `models` | The **catalogued** models: the only names `/v1/models` can advertise. |

Each `models` entry maps a public alias to:

| Key | Meaning |
| --- | --- |
| `provider_model` | Passed as `--model`. Must match the [model name rules](models-and-routing.md#passthrough-models). |
| `default` | The model `subscription/auto` picks for this provider. Without one, the first entry is used. |

Any other model the CLI accepts still works as `codex/<model>` or `claude-code/<model>`; see
[Models and routing](models-and-routing.md). Claude tier aliases (`opus`, `sonnet`, `haiku`,
`fable`) always resolve to the newest model of that tier, so they need no config change when a
new model ships.

### routing

| Key | Meaning |
| --- | --- |
| `fallback` | Allow a new chat request to move to another provider after a retryable failure. See [Routing and fallback](models-and-routing.md#routing-fallback-and-queuing). |
| `order` | Provider order for `subscription/auto` and for fallback. A provider left out is never chosen by either. |

### agent

Settings for [`POST /v1/agents/run`](api.md#agent-endpoint).

| Key | Meaning |
| --- | --- |
| `allowed_directories` | Roots a request's `cwd` must resolve inside. Claude's restricted mode then uses the resolved `cwd` as its file-access boundary. |
| `allow_outside_directories` | `true` accepts any existing directory as `cwd`. |
| `allow_write_fallback` | Second opt-in, together with the request's `fallback: true`, for `workspace-write` runs to fall back. |

### storage

| Key | Meaning |
| --- | --- |
| `sqlite_path` | Session metadata database (`~` is expanded). `":memory:"` keeps sessions only until the process exits. |
| `session_retention_days` | Sessions unused for this many days can no longer be resumed, and are deleted at startup and then at most hourly. `null` keeps them indefinitely. |

### logging

| Key | Meaning |
| --- | --- |
| `level` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`, in any case. |
| `json` | One JSON object per log line instead of plain text. |
| `debug_prompts` | Also log the prompt messages of non-streaming requests. Only visible at `level: DEBUG`. Off by default. |

### Validation rules

The gateway refuses to start with an invalid file. Besides the ranges above:

- `routing.order` may name only `codex` and `claude`, each at most once.
- `subscription/auto` is reserved and cannot be a model alias.
- An alias cannot use the other provider's prefix: no `claude-code/...` under `codex`, and vice
  versa.
- At most one model per provider may set `default: true`.
- Model entries reject unknown keys. Unknown keys elsewhere in the file are ignored, so check the
  spelling of any setting that seems to have no effect.

## Environment overrides

| Variable | Overrides |
| --- | --- |
| `SUBSCRIPTION_GATEWAY_CONFIG` | Path to the config file, when `--config` is not given |
| `GATEWAY_HOST` | `server.host` |
| `GATEWAY_PORT` | `server.port` |
| `GATEWAY_API_KEY` | `server.api_key` |
| `GATEWAY_ALLOW_REMOTE` | `server.allow_remote` |
| `GATEWAY_SQLITE_PATH` | `storage.sqlite_path` |
| `GATEWAY_SESSION_RETENTION_DAYS` | `storage.session_retention_days` (a number; use YAML `null` to keep sessions forever) |
| `GATEWAY_LOG_LEVEL` | `logging.level` |
| `GATEWAY_DEBUG_PROMPTS` | `logging.debug_prompts` |
| `GATEWAY_CODEX_COMMAND` | `providers.codex.command` |
| `GATEWAY_CLAUDE_COMMAND` | `providers.claude.command` |

Boolean variables accept `true`/`false`, `1`/`0`, `yes`/`no`, and `on`/`off`. Every other setting,
including models, routing, agent directories, concurrency, and timeouts, is set only through
`config.yaml`.

The gateway does not load `.env` files itself. [`.env.example`](../.env.example) lists the native
variables; `source` it or export them in your shell. The Docker stack reads its own variables;
see [Docker variables](#docker-variables).

## CLI reference

```text
subscription-gateway --version
subscription-gateway serve  [--config PATH] [--host HOST] [--port PORT]
subscription-gateway status [--config PATH]
subscription-gateway doctor [--config PATH]
```

After `make install`, the command lives in the project environment. Use the `make serve`,
`make status`, or `make doctor` targets, `uv run subscription-gateway …`, or activate `.venv`.
`--config` goes after the subcommand.

| Command | What it does |
| --- | --- |
| `serve` | Starts the HTTP server. `--host` and `--port` override the config and go through the same bind checks. Prints a warning on a non-loopback bind while a provider uses a subscription login. |
| `status` | Prints the base URL and, per provider: installed, authenticated, `ready`/`unavailable`, and its catalogued models. A disabled provider shows as `unavailable`. |
| `doctor` | Runs the setup checks below and prints `[PASS]` or `[WARN]` for each. |

`doctor` checks:

| Check | Exit 1 if it fails? |
| --- | --- |
| Python version ≥ 3.12 | yes |
| Configuration valid | — (an invalid config already exits 2) |
| Codex / Claude Code installation and authentication | no; each provider is optional |
| Claude Code agent support: version ≥ 2.1.248, which `/v1/agents/run` needs (only when Claude Code is installed) | no |
| SQLite storage writable (creates the database file and its directory if missing) | yes |
| Server port free to bind | yes; this fails while the gateway itself is running |
| Subscription sharing (non-loopback binds only) | no |

Exit codes: `0` for success, `1` when a required `doctor` check fails, and `2` for a
configuration error.

## Provider authentication

The gateway never handles provider credentials. Each CLI uses whatever login it already has and
inherits the gateway's environment.

| Provider | Subscription login | API-key login |
| --- | --- | --- |
| Codex | `codex login` (ChatGPT) | `printenv OPENAI_API_KEY \| codex login --with-api-key` |
| Claude Code | `claude auth login` (Claude) | `ANTHROPIC_API_KEY` set where the gateway runs |

`codex login status` and `claude auth status` show which method is active. These are the same
commands the gateway runs to decide whether a provider is ready. `ANTHROPIC_API_KEY` takes
precedence over a Claude subscription login while it is set.

Use a subscription login only for your own use on your own machine. Use API keys for anything
shared, remote, multi-user, or automated beyond that: Anthropic limits subscription logins to
ordinary use of Claude Code and does not allow routing requests through plan credentials for
others, and OpenAI recommends API keys for programmatic Codex workflows. API keys are billed at API
rates.

## Binding and remote access

The default base URL is `http://127.0.0.1:11435/v1`. The gateway will not bind to a non-loopback
address unless `server.allow_remote: true` **and** a local API key are both explicitly configured.
This remains a personal gateway; remote multi-user deployment is out of scope.

On a non-loopback address, `serve` prints a warning and `doctor` reports a `Subscription sharing`
warning for each provider signed in with a subscription. Anyone who can reach the gateway uses
that account; switch the provider to an API key before exposing the port.

## Local API authentication

Set a local-only gateway token if desired:

```bash
export GATEWAY_API_KEY=local-secret
make serve
```

Clients then send `Authorization: Bearer local-secret` or `X-Api-Key: local-secret` on every
`/v1/...` request. `/health`, `/ready`, and the generated API docs (`/docs`, `/redoc`,
`/openapi.json`) never require the key. The token protects the gateway only and is never sent to
Codex or Claude.

Without a configured token (unset or empty), loopback requests are accepted without
authentication, but `/v1/agents/run` is disabled.

Docker deployments always have a token. Compose sets `GATEWAY_API_KEY: ${GATEWAY_API_KEY:-local}`,
so the key is `local` unless `.env` or the environment overrides it, and requests without the
header are rejected with `invalid_api_key`. Setting the variable to an empty value does not
disable authentication: `${GATEWAY_API_KEY:-local}` treats empty as unset and falls back to
`local`.

## Logging and secrets

Log lines carry the request ID, provider, model, gateway session ID, queue delay, and duration.
They never include the gateway's configuration or API key. In `json` mode, any field whose name
contains `TOKEN`, `KEY`, `SECRET`, or `PASSWORD` is masked as an extra safeguard.

Prompt content is logged only when `debug_prompts` is on **and** `level` is `DEBUG`. Leave it off
on shared logs.

## Docker variables

The Compose stack reads a separate set of variables from `.env`; see
[Docker variables](docker.md#compose-variables) and
[`.env.docker.example`](../.env.docker.example).

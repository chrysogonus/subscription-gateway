# Configuration

[← Documentation index](README.md)

The gateway runs with usable defaults and no configuration file. Copy the example when you want
to change something:

```bash
make config           # copies config.example.yaml to config.yaml, never overwriting
$EDITOR config.yaml
subscription-gateway serve --config ./config.yaml
```

The config path can also be set with `SUBSCRIPTION_GATEWAY_CONFIG`. The `make` targets pass
`--config ./config.yaml` automatically once that file exists.

## config.yaml reference

[`config.example.yaml`](../config.example.yaml) is the annotated source of truth. The shape:

```yaml
server:
  host: 127.0.0.1
  port: 11435
  # api_key: local-secret
  allow_remote: false

providers:
  codex:
    enabled: true
    command: codex
    max_concurrent: 2
    timeout_seconds: 300
    models:
      codex/gpt-5.6-sol:
        provider_model: gpt-5.6-sol
        default: true          # subscription/auto uses this model for Codex

  claude:
    enabled: true
    command: claude
    max_concurrent: 1
    timeout_seconds: 300
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

logging:
  level: INFO
  json: false
  debug_prompts: false
```

Notes:

- Models listed under `providers.<name>.models` are the **catalogued** ones — the only names
  `/v1/models` can advertise. Any other model the CLI accepts still works as
  `codex/<model>` or `claude-code/<model>`; see [Models and routing](models-and-routing.md).
- `default: true` marks the model `subscription/auto` picks for that provider.
- Claude tier aliases (`opus`, `sonnet`, `haiku`, `fable`) always resolve to the newest model of
  that tier, so they do not need a config change when a new one ships.
- `agent.allowed_directories` bounds every `POST /v1/agents/run` request. See
  [the agent endpoint](api.md#agent-endpoint).

## Environment overrides

Supported overrides:

| Variable | Effect |
| --- | --- |
| `SUBSCRIPTION_GATEWAY_CONFIG` | Path to the config file |
| `GATEWAY_HOST` | Bind address |
| `GATEWAY_PORT` | Bind port |
| `GATEWAY_API_KEY` | Local gateway token (see below) |
| `GATEWAY_SQLITE_PATH` | Session metadata database path |
| `GATEWAY_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `GATEWAY_DEBUG_PROMPTS` | Log prompt content — off by default |
| `GATEWAY_CODEX_COMMAND` | Path or name of the Codex executable |
| `GATEWAY_CLAUDE_COMMAND` | Path or name of the Claude Code executable |

Values whose names contain `TOKEN`, `KEY`, `SECRET`, or `PASSWORD` are never emitted by gateway
logging.

## Binding and remote access

The default base URL is `http://127.0.0.1:11435/v1`. The gateway will not bind to a non-loopback
address unless `server.allow_remote: true` **and** a local API key are both explicitly configured.
This remains a personal gateway; remote multi-user deployment is out of scope.

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

## Docker variables

The Compose stack reads a separate set of variables from `.env`; see
[`.env.docker.example`](../.env.docker.example) and the [Docker guide](docker.md).

# Subscription LLM Gateway

[![CI](https://github.com/chrysogonus/subscription-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/chrysogonus/subscription-gateway/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-2a6db2.svg)](https://mypy-lang.org/)

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

### Subscription logins are for your own use

Both CLIs can sign in with a subscription (ChatGPT or Claude) or with an API key. The gateway
works with either, but the terms differ:

- **Subscription login:** one person, on their own machine, using their own account. Do not let
  anyone else reach the gateway, and do not put it behind a shared OpenWebUI. Anthropic states
  that subscription logins support ordinary use of Claude Code and that third parties may not
  route requests through Free, Pro, or Max plan credentials. OpenAI recommends API keys for
  programmatic Codex workflows.
- **API key:** required for anything shared, remote, multi-user, or automated beyond your own
  use. Usage is billed at API rates under your own developer agreement.

`subscription-gateway doctor` and `serve` warn when the gateway listens on a non-loopback
address while a provider is signed in with a subscription.

### Disclaimer

This project is not affiliated with, endorsed by, or sponsored by OpenAI or Anthropic. Using it
does not change the terms you accepted for your own accounts: your use of Codex and Claude Code
through this gateway remains subject to those terms and to your plan's usage limits. Check them
before pointing anything at it.

## Requirements

- Python 3.12 or newer;
- Codex CLI, authenticated with `codex login` or `codex login --with-api-key`, for `codex/*`
  models;
- Claude Code, authenticated with `claude auth login` or an `ANTHROPIC_API_KEY` in the gateway's
  environment, for `claude-code/*` models.

See [Provider authentication](docs/configuration.md#provider-authentication) for which login fits
which setup.

Filesystem-agent requests require Claude Code 2.1.248 or newer; the Docker image pins a compatible
release. Codex remains available for chat, but is intentionally not exposed through the agent
endpoint because its CLI sandbox does not confine read access to the requested workspace.

The server starts even if neither provider is installed. `/health` remains healthy, `/ready`
returns 503, and `/v1/models` returns an empty list in that situation.

## Quickstart

```bash
git clone https://github.com/chrysogonus/subscription-gateway.git
cd subscription-gateway
make install                  # prefers uv and the checked-in lock file, falls back to .venv and pip

subscription-gateway doctor   # check the local setup
subscription-gateway serve    # http://127.0.0.1:11435/v1
```

In another terminal:

```bash
curl http://127.0.0.1:11435/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "subscription/auto",
    "messages": [{"role": "user", "content": "Explain Linux namespaces."}]
  }'
```

Or with Docker, including an optional preconfigured OpenWebUI:

```bash
make up          # gateway only, on http://127.0.0.1:11435
make up-webui    # gateway and OpenWebUI, on http://127.0.0.1:3001
```

The default bind is loopback-only, and the gateway refuses a non-loopback address unless
`server.allow_remote` **and** a local API key are both configured. Docker deployments always
require `Authorization: Bearer <key>`, defaulting to `local`. Filesystem-agent requests require a
configured key even on loopback-native deployments.

## Models

Catalogued models — the ones `/v1/models` advertises and a client's model picker shows:

| Model | Runs as |
| --- | --- |
| `codex/gpt-5.6-sol` | `codex --model gpt-5.6-sol` |
| `claude-code/opus` | `claude --model opus` |
| `claude-code/sonnet` | `claude --model sonnet` |
| `claude-code/haiku` | `claude --model haiku` |
| `claude-code/fable` | `claude --model fable` |
| `subscription/auto` | the `default: true` model of the first available provider |

Any other model the CLI accepts also works as `codex/<model>` or `claude-code/<model>`, validated
before a subprocess is started. See [Models and routing](docs/models-and-routing.md).

## Documentation

| Guide | What it covers |
| --- | --- |
| [Configuration](docs/configuration.md) | `config.yaml` reference, environment overrides, local API authentication |
| [API](docs/api.md) | Endpoints, `curl` and Python examples, streaming, sessions, the agent endpoint |
| [Models and routing](docs/models-and-routing.md) | Catalogued vs. passthrough models, routing, fallback, scheduling |
| [Docker](docs/docker.md) | The image, Compose stack, credential mounts, optional OpenWebUI |
| [Architecture](docs/architecture.md) | Provider adapters, package layout, platform support, `make` targets |

## Development

```bash
make dev        # install with development extras
make check      # ruff, ruff format, mypy --strict, and pytest
make help       # every available target
```

Tests use mock providers and mocked process results. They do not require provider installations,
credentials, network access, or subscription usage.

## Contributing

Issues and pull requests are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), and note the
scope limits described above — contributions that would require reading provider credentials or
calling undocumented endpoints are out of scope.

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Security issues go through
[SECURITY.md](SECURITY.md), not public issues.

## License

[MIT](LICENSE) © Christopher Filsinger

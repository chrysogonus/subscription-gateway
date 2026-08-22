# Architecture and development

[← Documentation index](README.md)

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

## Package layout

`src/subscription_gateway/`:

| Module | Responsibility |
| --- | --- |
| `main.py`, `cli.py` | FastAPI application factory; the `serve` / `status` / `doctor` CLI |
| `config.py` | Pydantic settings model, YAML loading, environment overrides, secret redaction |
| `api/` | Routers: `chat`, `responses`, `agents`, `models`, `health` |
| `compat/` | OpenAI request and response shapes, prompt assembly, streaming chunks |
| `providers/` | The `Provider` protocol, the Codex and Claude adapters, subprocess handling, registry |
| `routing/` | Model resolution, fallback policy, request orchestration |
| `sessions/` | Gateway session records and their SQLite storage |
| `queue/` | Per-provider concurrency semaphores |

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

## Platform support

Linux is the primary target. The implementation uses `pathlib`, `shutil.which`, argument-array
subprocesses, and cross-platform process termination where practical, so macOS should work.
Windows users should run the first prototype in WSL.

## Development checks

```bash
make dev            # install with development extras
make check          # ruff, ruff format, mypy --strict, and pytest
make coverage       # the test suite with a coverage report
```

Individually:

```bash
pytest
ruff check .
mypy src/subscription_gateway
```

Tests use mock providers and mocked process results. They do not require provider installations,
credentials, network access, or subscription usage.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full contribution and release workflow.

## Make targets

`make help` prints the current list. The most useful ones:

| Target | Purpose |
| --- | --- |
| `dev`, `install` | Install with or without development extras |
| `check` | `lint`, `typecheck`, and `test` |
| `test`, `lint`, `fix`, `typecheck`, `coverage` | Individual checks; `fix` applies ruff autofixes and formatting |
| `precommit` | Install the pre-commit hooks |
| `serve`, `status`, `doctor` | Run the CLI locally, using `./config.yaml` when it exists |
| `config`, `env` | Create `config.yaml` and `.env` from the examples, never overwriting |
| `up`, `up-webui` | Deploy without or with OpenWebUI |
| `down`, `restart`, `ps`, `logs` | Manage the deployed stack |
| `shell`, `docker-status`, `docker-doctor` | Inspect the gateway container |
| `smoke` | Curl `/health` and `/v1/models` against a running gateway |
| `dist`, `clean` | Build the wheel and sdist; remove artifacts and caches |
| `purge CONFIRM=1` | Remove containers and their data volumes (destructive) |

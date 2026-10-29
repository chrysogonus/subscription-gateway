# Documentation

Reference material for Subscription LLM Gateway. Start at the
[project README](../README.md) if you have not installed it yet.

| Guide | What it covers |
| --- | --- |
| [Overview](overview.md) | The five-minute visual tour: what it is, one request, models, safety, running it, the code, releases, limits |
| [Configuration](configuration.md) | `config.yaml` reference, validation rules, environment overrides, CLI commands and `doctor` checks, local API authentication, logging |
| [API](api.md) | Endpoints, request and response fields, `curl` and Python examples, streaming, sessions, the agent endpoint, error codes |
| [Models and routing](models-and-routing.md) | Catalogued vs. passthrough models, name validation, routing, fallback, queuing |
| [Docker](docker.md) | The image and pinned versions, Compose variables and stack, credential mounts, optional OpenWebUI |
| [Architecture](architecture.md) | Package layout, provider command lines, platform support, development workflow, `make` targets |

Other things worth reading:

- [CONTRIBUTING.md](../CONTRIBUTING.md) — development setup, the check loop, release process
- [SECURITY.md](../SECURITY.md) — what is in scope, and the design boundaries that are not bugs
- [CHANGELOG.md](../CHANGELOG.md) — what changed, and when

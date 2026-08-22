# Documentation

Reference material for Subscription LLM Gateway. Start at the
[project README](../README.md) if you have not installed it yet.

| Guide | What it covers |
| --- | --- |
| [Configuration](configuration.md) | `config.yaml` reference, environment overrides, local API authentication |
| [API](api.md) | Endpoints, `curl` and Python examples, streaming behavior, sessions, the agent endpoint |
| [Models and routing](models-and-routing.md) | Catalogued vs. passthrough models, name validation, routing, fallback, scheduling |
| [Docker](docker.md) | The image, Compose stack, credential mounts, optional OpenWebUI |
| [Architecture](architecture.md) | Provider adapters, platform support, development workflow, `make` targets |

Other things worth reading:

- [CONTRIBUTING.md](../CONTRIBUTING.md) — development setup, the check loop, release process
- [SECURITY.md](../SECURITY.md) — what is in scope, and the design boundaries that are not bugs
- [CHANGELOG.md](../CHANGELOG.md) — what changed, and when

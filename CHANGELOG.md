# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Docker now bundles Codex 0.163.0, which serves models that 0.150.1 rejected, such as
  `gpt-6-luna`.

## [0.2.0] - 2026-10-26

### Added

- `serve` and `doctor` warn when the gateway listens on a non-loopback address while a provider
  is signed in with a subscription rather than an API key.
- Compose forwards an optional `ANTHROPIC_API_KEY` to the gateway, so Claude Code can use an
  API key in Docker.
- Documentation of API-key logins for both providers, and of which login fits which setup.

### Changed

- The repository is renamed from `sub2api` to `subscription-gateway`, matching the package
  name. GitHub redirects the old URLs.
- The README states that subscription logins are for one person's own use and that shared,
  remote, or multi-user setups need API keys.
- The Compose OpenWebUI service sets `DEFAULT_USER_ROLE=pending`, so accounts after the first
  administrator need approval, and the Docker guide says to turn off OpenWebUI sign-ups after
  creating that administrator.

### Fixed

- Claude usage reported cache writes as cached input tokens when there were no cache reads.
  `cached_input_tokens` now counts cache reads only.
- Dependabot's Python updates use the `uv` ecosystem, so they update `uv.lock` along with
  `pyproject.toml` instead of failing the `--locked` install in CI.
- The image installs `libatomic1`, which Node 26 and later need to start.
- GitHub Releases attach only the wheel and sdist, no longer the `.gitignore` that `uv build`
  writes into `dist/`.

## [0.1.0] - 2026-08-28

### Added

- OpenAI-compatible HTTP gateway on `http://127.0.0.1:11435/v1`, backed by the
  user's already-authenticated Codex and Claude Code CLIs.
- `POST /v1/chat/completions` with coarse SSE streaming, `POST /v1/responses`
  (documented subset), `POST /v1/agents/run`, `GET /v1/models`, `/health`, `/ready`.
- Catalogued and passthrough model names with strict validation before any
  subprocess spawn; `subscription/auto` routing alias with provider fallback.
- Session continuation through the `X-Gateway-Session` header, backed by SQLite
  metadata only — never provider credentials.
- Per-provider concurrency limits, normalized error taxonomy, secret-redacting logging.
- `subscription-gateway` CLI with `serve`, `status`, and `doctor`.
- Docker image and Compose stack with an optional OpenWebUI service behind the
  `webui` profile, loopback-only port publishing, and a non-root container.
- MIT `LICENSE` file, matching the license already declared in package metadata.
- Community health files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
  issue and pull request templates, and `CODEOWNERS`.
- GitHub Actions: `ci.yml` (ruff, ruff format, and mypy once; pytest on Python 3.12
  and 3.13; plus a Docker build smoke test) and `release.yml` (tag-triggered GitHub
  Release, gated on the CI workflow).
- Dependabot updates for pip, GitHub Actions, and Docker.
- `docs/` with configuration, API, models and routing, Docker, and architecture guides,
  split out of the README.
- `py.typed` marker, so the strict type annotations are visible to consumers.
- `make coverage` and `make precommit` targets; `pytest-cov` in the development extra.
- `.editorconfig` and a `.pre-commit-config.yaml` with ruff and whitespace hooks.
- OCI image labels on the Docker image.
- Tests for the `subscription-gateway` CLI, the subprocess reaping guarantees in
  `providers/process.py`, log formatting and redaction, and the `/v1/responses`
  streaming path. Coverage rose from 75% to over 87%.
- Automatic cleanup of inactive session metadata, configurable with
  `storage.session_retention_days` and defaulting to 30 days.

### Changed

- Ruff now enforces `S` (flake8-bandit), `SIM`, `RUF`, `PT`, and `PTH` alongside the
  existing rules; `mypy --strict` now checks `tests/` as well as `src/`.
- `pytest` turns warnings into errors and runs with `--strict-markers`
  `--strict-config`; coverage fails under 85%.
- The Docker image installs its dependencies from `uv.lock` — the same resolution
  CI tests — with pip verifying the exported hashes, instead of resolving fresh at
  build time. A stale lock now fails the image build.
- The version is now read from installed package metadata instead of being
  hardcoded in `__init__.py` and the FastAPI constructor; `pyproject.toml` is the
  single source of truth.
- Package metadata gained `keywords`, `classifiers`, and `[project.urls]`, and the
  license is declared as an SPDX expression.
- The README is now a landing page; deep reference material moved to `docs/`.
- Docker now bundles Codex 0.150.1 and Claude Code 2.1.251, and includes the MIT
  license in the image's installed package metadata.
- GitHub Actions dependencies are pinned to full commit SHAs.
- Streaming documentation now distinguishes headers available before provider fallback
  from those available only on non-streaming responses.

### Security

- Filesystem-agent requests now require a configured gateway API key, including on
  loopback-native deployments.
- Claude filesystem agents run with `--restricted` and a file-only tool allowlist;
  command execution is not exposed. Codex remains available for chat but is no longer
  exposed through the agent endpoint because its CLI cannot enforce the configured
  read boundary.
- Session records now bind continuations to their original API type, resolved working
  directory, and permission level, preventing agent sessions from being resumed through
  chat or with broader permissions.
- Requests continuing the same gateway session are serialized to prevent concurrent
  provider-thread state races.
- Provider working-directory failures now fail closed instead of silently falling back
  to the user's home directory. Codex resumptions also reapply their sandbox mode.

### Fixed

- `subscription-gateway --version` no longer crashes in the container image. Importing
  `subscription_gateway.main` built the ASGI app eagerly, so it loaded and validated the
  configuration; the image ENV asks for a non-loopback bind with no API key set yet, and
  the resulting `ValidationError` broke every CLI entry point, including the CI smoke
  test. `main:app` is now constructed on first attribute access.
- `ProviderRegistry.resolve` no longer relies on an `assert` for a load-bearing
  invariant, which would be stripped under `python -O`.
- CI now installs with `uv sync --locked` instead of `--frozen`. `--frozen` only means
  "do not update the lock", so it installed happily from a `uv.lock` that no longer
  matched `pyproject.toml`; a dependency added without `make lock` produced a green run.
  Only the image build, which exports with `--locked --no-dev`, caught the drift — and
  never for a development dependency.
- `make check` runs `coverage` rather than `test`, so the 85% floor fails the local gate
  too. `--cov` is not in `addopts`, so a plain `pytest` run reported green while CI failed.

[Unreleased]: https://github.com/chrysogonus/subscription-gateway/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/chrysogonus/subscription-gateway/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/chrysogonus/subscription-gateway/releases/tag/v0.1.0

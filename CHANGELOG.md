# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Changed

- The version is now read from installed package metadata instead of being
  hardcoded in `__init__.py` and the FastAPI constructor; `pyproject.toml` is the
  single source of truth.
- Package metadata gained `keywords`, `classifiers`, and `[project.urls]`, and the
  license is declared as an SPDX expression.
- The README is now a landing page; deep reference material moved to `docs/`.

## [0.1.0] - 2026-08-20

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

[Unreleased]: https://github.com/chrysogonus/sub2api/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/chrysogonus/sub2api/releases/tag/v0.1.0

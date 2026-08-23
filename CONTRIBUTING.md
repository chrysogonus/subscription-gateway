# Contributing

Thanks for taking an interest in Subscription LLM Gateway. This is a small, focused project, so
the process is deliberately light.

## Scope

The gateway is a **localhost-first compatibility layer** over the user's own authenticated Codex
and Claude Code clients. Contributions that would move it outside that scope are not accepted:

- reading, parsing, or copying provider credentials from anywhere;
- intercepting provider traffic or calling undocumented private endpoints;
- anything that presents itself as multi-user hosting, subscription resale, or rate-limit evasion.

Everything else — provider adapters, OpenAI-compatibility gaps, routing, error handling, docs,
packaging — is fair game.

## Development setup

```bash
git clone https://github.com/chrysogonus/sub2api.git
cd sub2api
make dev          # prefers uv and the checked-in uv.lock, falls back to .venv and pip
```

Optional, recommended:

```bash
make precommit    # install the ruff and whitespace pre-commit hooks
```

## The check loop

```bash
make fix          # ruff autofixes + ruff format
make check        # ruff check, mypy --strict, pytest --cov — the same gate CI runs
make coverage     # just the test suite with a coverage report
```

CI runs `ruff format --check`, so run `make fix` before pushing. `mypy` runs in `strict` mode over
both `src/` and `tests/`, and the codebase is clean under it; new code is expected to stay that way.

Two things fail a run that used to only produce output:

- **Warnings are errors.** `filterwarnings = ["error"]` in `pyproject.toml`. A new deprecation
  warning fails the suite; add a narrowly scoped `ignore:` entry naming the dependency that
  emits it, so the exception expires visibly rather than silently.
- **Coverage has a floor** of 85% (`fail_under` under `[tool.coverage.report]`). Raise it when
  you raise coverage; never lower it to make a red run green. The floor only fires under
  `--cov`, which is why `make check` runs `coverage` rather than plain `test`.

Tests use mock providers and mocked process results. They must not require a provider
installation, credentials, network access, or subscription usage — if a change can only be tested
against a live CLI, it needs a fake at the `Provider` boundary instead.

## Pull requests

- One topic per pull request.
- Behavior changes come with tests.
- Update `docs/` when you change configuration, endpoints, model handling, or Docker.
- Add an entry under `## [Unreleased]` in `CHANGELOG.md`.
- `make check` passes locally.

Commit messages follow a `type: summary` form (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`,
`chore:`, `ci:`). Nothing enforces it; it keeps the changelog easy to assemble.

## Reporting bugs

Open an issue using the bug report template. Include the output of `subscription-gateway doctor`
and whether you are running natively or in Docker. **Redact API keys, session identifiers, and
prompt content you would not want public.**

For security issues, do not open a public issue — see [SECURITY.md](SECURITY.md).

## Releasing

Maintainer steps:

1. Bump `version` in `pyproject.toml`. It is the single source of truth; the package and the
   FastAPI app read it from installed metadata.
2. Move the `## [Unreleased]` entries into a new `## [X.Y.Z] - YYYY-MM-DD` section in
   `CHANGELOG.md` and update the link definitions at the bottom.
3. Commit, then tag and push:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main --follow-tags
   ```

The `release` workflow re-runs the checks, builds the wheel and sdist, and creates the GitHub
Release. Nothing is published to PyPI or a container registry.

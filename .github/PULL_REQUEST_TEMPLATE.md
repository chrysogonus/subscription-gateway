## Summary

<!-- What does this change do, in one or two sentences? -->

## Motivation

<!-- Why is it needed? Link the issue it closes, if there is one. -->

## How it was tested

<!-- Commands run, and anything you exercised by hand. Tests must not require
     provider credentials, network access, or subscription usage. -->

## Checklist

- [ ] `make check` passes (ruff, ruff format, mypy --strict, pytest)
- [ ] Tests cover the behavior change, using fakes at the `Provider` boundary
- [ ] `docs/` updated if configuration, endpoints, model handling, or Docker changed
- [ ] `CHANGELOG.md` entry added under `## [Unreleased]`
- [ ] No provider credentials are read, parsed, or stored by this change

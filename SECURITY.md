# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| `0.1.x` | Yes |
| older | No |

This is a pre-1.0 project. Fixes land on `main` and ship in the next tagged release.

## Reporting a vulnerability

Please report privately through
[GitHub Security Advisories](https://github.com/chrysogonus/sub2api/security/advisories/new)
rather than opening a public issue.

Include the affected version, whether you ran natively or in Docker, reproduction steps, and the
impact you observed. Expect an initial response within about a week; this is a personal project
maintained in spare time.

## Design boundaries

Some behavior that looks alarming is intentional and documented. It is not a vulnerability:

- **Loopback binding by default.** The gateway refuses to bind a non-loopback address unless both
  `server.allow_remote: true` and a local API key are configured. Deliberately configuring a
  remote bind is a supported-but-discouraged choice; the resulting exposure is the operator's.
- **No API key by default when running natively.** Without `GATEWAY_API_KEY`, localhost requests
  are accepted. The Docker Compose stack always sets a key (`local` by default).
- **Provider state is mounted read-write in Docker.** The official CLIs refresh their own
  sessions, so their state directories must be writable. The gateway itself never opens or parses
  those files.
- **Subprocess execution of the provider CLIs** is the entire point of the project. Model names
  are validated against a strict character allowlist before any process is spawned, and
  subprocesses are created from argument arrays with no shell.
- **Agent filesystem access** is bounded by `agent.allowed_directories` with symlink-escape
  checks. Write-capable fallback requires two separate opt-ins.

Reports that *are* in scope include: model-name or path validation that can be bypassed, command
or argument injection into a provider CLI, sandbox escape from `POST /v1/agents/run`, credentials
or secrets appearing in logs or responses, session data leaking across gateway sessions, and
authentication bypass when `GATEWAY_API_KEY` is set.

## What this project never does

It does not read browser cookies, extract bearer tokens, intercept provider traffic, or call
undocumented private endpoints. Authentication stays entirely with the official Codex and Claude
Code clients. The only thing stored is gateway-to-provider session metadata in SQLite — never
provider credentials.

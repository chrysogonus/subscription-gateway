# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| `0.2.x` | Yes |
| older | No |

This is a pre-1.0 project. Fixes land on `main` and ship in the next tagged release.

## Reporting a vulnerability

Please report privately through
[GitHub Security Advisories](https://github.com/chrysogonus/subscription-gateway/security/advisories/new)
rather than opening a public issue.

Include the affected version, whether you ran natively or in Docker, reproduction steps, and the
impact you observed. Expect an initial response within about a week; this is a personal project
maintained in spare time.

## Design boundaries

Some behavior that looks alarming is intentional and documented. It is not a vulnerability:

- **Loopback binding by default.** The gateway refuses to bind a non-loopback address unless both
  `server.allow_remote: true` and a local API key are configured. Deliberately configuring a
  remote bind is a supported-but-discouraged choice; the resulting exposure is the operator's.
- **No API key by default for native chat.** Without `GATEWAY_API_KEY`, localhost chat requests
  are accepted. Filesystem-agent requests remain disabled until a key is configured. The Docker
  Compose stack always sets a key (`local` by default).
- **Provider state is mounted read-write in Docker.** The official CLIs refresh their own
  sessions, so their state directories must be writable. The gateway itself never opens or parses
  those files.
- **Subprocess execution of the provider CLIs** is the entire point of the project. Model names
  are validated against a strict character allowlist before any process is spawned, and
  subprocesses are created from argument arrays with no shell.
- **Agent filesystem access** is available only through Claude Code's restricted mode. The
  resolved working directory must be under `agent.allowed_directories`; the runtime is limited to
  built-in file tools rooted there, and command execution is not exposed. Codex chat remains
  supported, but Codex is not exposed through the filesystem-agent endpoint because its sandbox
  does not provide the required read boundary. Write-capable fallback requires two separate
  opt-ins.
- **Codex chat runs in a read-only sandbox, not an empty one.** Codex chat requests run in
  `providers.codex.working_directory` (default: your home directory) with
  `--sandbox read-only`. That sandbox blocks writes, but Codex can still read files and run
  read-only commands while answering. Point `working_directory` at a narrower directory, or
  disable Codex, if that matters for your setup. Claude chat runs with no tools at all.
- **Plain-text logs are not filtered.** The gateway never logs its configuration or API key,
  and JSON logs additionally mask secret-named fields. Prompt content appears only with
  `logging.debug_prompts: true` at `DEBUG` level.

Reports that *are* in scope include: model-name or path validation that can be bypassed, command
or argument injection into a provider CLI, sandbox escape from `POST /v1/agents/run`, credentials
or secrets appearing in logs or responses, session data leaking across gateway sessions, and
authentication bypass when `GATEWAY_API_KEY` is set.

Gateway sessions record their API type, resolved working directory, and permission level. Those
attributes cannot change on continuation, and requests for the same session are serialized so
provider thread state cannot race. A session unused for 30 days (by default) can no longer be
resumed, and its metadata is deleted at startup and then at most hourly.

## What this project never does

It does not read browser cookies, extract bearer tokens, intercept provider traffic, or call
undocumented private endpoints. Authentication stays entirely with the official Codex and Claude
Code clients. The only thing stored is gateway-to-provider session metadata in SQLite — never
provider credentials.

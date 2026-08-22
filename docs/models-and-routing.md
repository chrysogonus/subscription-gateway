# Models and routing

[← Documentation index](README.md)

Two kinds of model name work.

## Catalogued models

**Catalogued** models are the ones listed in configuration. They are the only names `/v1/models`
can advertise, so they are what a client's model picker shows:

| Model | Runs as |
| --- | --- |
| `codex/gpt-5.6-sol` | `codex --model gpt-5.6-sol` |
| `claude-code/opus` | `claude --model opus` |
| `claude-code/sonnet` | `claude --model sonnet` |
| `claude-code/haiku` | `claude --model haiku` |
| `claude-code/fable` | `claude --model fable` |
| `subscription/auto` | the `default: true` model of the first available provider |

The Claude entries are tier aliases, so they always resolve to the newest model of that tier
without a config change.

## Passthrough models

**Passthrough** covers everything else: any `codex/<model>` or `claude-code/<model>` that is not
catalogued has its suffix passed to the CLI verbatim.

```bash
curl http://127.0.0.1:11435/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer local' \
  -d '{
    "model": "claude-code/claude-fable-5",
    "messages": [{"role": "user", "content": "Explain Linux namespaces."}]
  }'
```

Four things to know about passthrough:

- Names are validated before reaching the CLI. A name must start with a letter, digit, or
  underscore and may otherwise contain only letters, digits, `.`, `_`, `:`, and `-`. Anything
  else — an empty suffix, a leading `-`, spaces, slashes — is rejected with 404 without starting a
  subprocess.
- Passthrough models cannot appear in `/v1/models`, because neither CLI can enumerate its models.
  OpenWebUI's picker has no free-text field, so passthrough is for API callers. To use a model in
  a UI, add it to `models` in `config.yaml` and it becomes catalogued.
- The Codex adapter runs with `--ignore-user-config`, so model profiles and aliases defined in
  `~/.codex/config.toml` do **not** resolve. Only names the Codex CLI accepts natively work.
- If the runtime rejects the model, the request fails with `model_not_available` rather than
  falling back to another provider.

Configured aliases are not automatic guarantees of account-level model access. If a local client
version or plan does not offer an alias's `provider_model`, the gateway returns
`model_not_available`.

## Legacy aliases

`claude-code/opus-5`, the alias earlier versions shipped, still resolves to `opus` but is no longer
advertised. Sessions started under it keep working. Note that continuing such a session while
sending `claude-code/opus` returns `session_model_mismatch`: the names are compared as strings even
though they select the same model.

## Routing, fallback, and scheduling

- Explicit `codex/*` and `claude-code/*` aliases route directly.
- `subscription/auto` follows `routing.order` and defaults to Codex. Within a provider it uses the
  model marked `default: true`, or the first configured model when none is marked.
- Retryable unavailability, temporary, usage-limit, and timeout failures may fall back for
  stateless chat requests when enabled.
- A model the caller named explicitly never falls back when the runtime rejects the model itself:
  no other provider can supply that model, and answering from a different one would misattribute
  the reply. `subscription/auto` still falls back, because the caller named no model.
- Existing sessions never cross providers.
- Write-capable agent operations do not fall back by default.
- Provider semaphores queue excess work; defaults are two Codex and one Claude request.

Unavailable providers are not advertised unless their `advertise_unavailable` setting is true.
This setting affects discovery only; an actual request still returns a normalized error.

Check the `X-Gateway-Provider` and `X-Gateway-Model` response headers to see what actually ran.

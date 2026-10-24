# Docker

[← Documentation index](README.md)

The supplied image installs the pinned, tested official Codex and Claude Code clients. Provider
credentials are never copied into an image: Compose mounts the host's existing client state only
at runtime. The HTTP port remains published on `127.0.0.1`, and the container runs as a non-root
user with all Linux capabilities dropped.

## Start the stack

First authenticate the official clients on the host and confirm both statuses:

```bash
codex login status
claude auth status
```

Then start the gateway, deciding whether the optional chat UI is deployed with it:

```bash
export GATEWAY_API_KEY=local        # Change this if desired

make up                             # gateway only
make up-webui                       # gateway and OpenWebUI

make ps
make docker-status
```

The `make` targets export `GATEWAY_UID` from `id -u` themselves. Without `make`, set it by
hand and select the profile explicitly:

```bash
export GATEWAY_UID="$(id -u)"                          # Linux; usually 1000
docker compose up --build --detach                     # gateway only
docker compose --profile webui up --build --detach     # gateway and OpenWebUI
```

When OpenWebUI is deployed, open the chat UI at `http://127.0.0.1:3001`. Both the UI and gateway
API ports are bound to the host loopback interface. The first OpenWebUI account becomes the local
administrator; keep its credentials private even though the service is not published remotely.

The first image build installs Codex and Claude Code and can take several minutes. Subsequent
starts use the cached image.

Test it from the host:

```bash
curl http://127.0.0.1:11435/v1/models \
  -H 'Authorization: Bearer local'
```

## Compose defaults

- API key: `local`;
- Codex state: `$HOME/.codex` mounted at `/home/gateway/.codex`;
- Claude state: `$HOME/.claude` mounted at `/home/gateway/.claude`;
- Claude user state: `$HOME/.claude.json` mounted at `/home/gateway/.claude.json`;
- agent workspace: `$HOME/workspace` mounted at `/home/gateway/workspace`;
- SQLite metadata: the Docker-managed `gateway-data` volume;
- OpenWebUI: not deployed unless the `webui` profile is selected; when it is,
  `http://127.0.0.1:3001`, with data in the `open-webui-data` volume.

## Configuration in Docker

The container reads `config.yaml` from a read-only mount, which is how the model catalog is
customized in Docker — no environment variable configures models. It defaults to
`./config.example.yaml`, and the `make` targets point it at `./config.yaml` as soon as that file
exists:

```bash
make config          # copy config.example.yaml to config.yaml
$EDITOR config.yaml  # add models under providers.<name>.models
make up
```

Without `make`, set `GATEWAY_CONFIG_FILE` yourself. Point it only at a file that exists: Docker
creates a *directory* for a missing bind source, and the gateway then refuses to start. The
environment variables in `docker-compose.yml` are applied after the file, so `GATEWAY_HOST`,
`GATEWAY_API_KEY`, and `GATEWAY_SQLITE_PATH` still win over anything it sets.

Override host paths or pinned CLI releases through the variables shown in
[`.env.docker.example`](../.env.docker.example). Compose automatically reads a file named `.env`,
so one option is:

```bash
cp .env.docker.example .env
# Edit .env for this machine, then:
docker compose up --build --detach
```

## Credentials in containers

The provider-state mounts are read-write because the official clients refresh their own sessions
and persist conversation metadata. The gateway still never opens or parses credential files. The
adapters use Codex's `--ignore-user-config` and Claude's `--safe-mode`, so host hooks, plugins, and
MCP configuration are not activated by gateway requests. Filesystem-agent requests additionally
use Claude's `--restricted` mode and a file-only tool allowlist rooted at the requested container
workspace. Codex is available for chat but not through the filesystem-agent endpoint.

Codex can store authentication in an OS keyring instead of `$HOME/.codex/auth.json`. A container
cannot access the host keyring. If `docker compose exec gateway codex login status` is not ready,
configure Codex's supported file credential store on the host and run `codex login` there again.
Claude similarly needs its official local client state under the mounted Claude directory and
`.claude.json` file. Do not copy either credential into the repository or Dockerfile.

To use API keys instead of subscription logins, set `ANTHROPIC_API_KEY` in `.env` (Compose
forwards it to the gateway, and Claude Code then prefers it), and run
`codex login --with-api-key` on the host so the mounted `~/.codex` holds an API-key login. See
[Provider authentication](configuration.md#provider-authentication) for when that is required.

Inside the container the gateway listens on `0.0.0.0`, so with a subscription login it logs the
`signed in with a subscription` warning at startup. That is expected while the ports stay
published on `127.0.0.1`; if you publish them anywhere else, switch to API keys first.

For agent requests, use the container path — not the host path. See
[the agent endpoint](api.md#agent-endpoint).

## OpenWebUI

Docker Compose includes a preconfigured OpenWebUI service, but it is optional and is not
deployed unless it is requested. It sits in the Compose `webui` profile, so the gateway can
run on its own for API-only use:

```bash
make up              # gateway only
make up-webui        # gateway and OpenWebUI
```

`make up WEBUI=1` is the same choice spelled as a variable, and the equivalent without
`make` is `docker compose --profile webui up --detach`. To make the choice permanent for
this machine, set `COMPOSE_PROFILES=webui` in `.env`.

With the UI deployed, open `http://127.0.0.1:3001`. On the first visit, create the local
administrator account. The model picker is populated from the gateway's live `/v1/models`
response and shows usable Codex, Claude Code, and routing aliases.

With subscription logins, OpenWebUI should have exactly one account: every other account uses
your subscription. Right after creating the administrator, turn off **Enable New Sign Ups** under
**Admin Panel → Settings → Authentication** and save. Do the same on an existing installation,
and remove or leave unapproved any accounts other than your own under **Admin Panel → Users**.

As a second guard, Compose sets `DEFAULT_USER_ROLE=pending`, so an account created while sign-ups
are open waits for approval. OpenWebUI stores both settings in its data volume on first start, so
an existing `open-webui-data` volume keeps whatever was saved there; check them in the admin
panel's settings.

The decision is reversible at any time. `make up-webui` adds the UI container next to an
already running gateway, and `make down` followed by `make up` leaves the gateway running
without it. The `open-webui-data` volume survives either direction, so accounts and chats
return if the UI is redeployed later; `make purge CONFIRM=1` is the explicit way to delete
those volumes.

The Compose connection uses `http://gateway:11435/v1` on the private container network. Ollama is
disabled, so the model picker is not cluttered by an unavailable default backend. OpenWebUI state
is stored in the `open-webui-data` Docker volume. The pinned slim image avoids bundling a large
local embedding model; ordinary chat works normally, while knowledge/RAG features may download
their selected embedding model during the first startup.

OpenWebUI is configured with legacy function calling because Codex and Claude Code are agent
runtimes, not OpenAI tool-calling endpoints. In this mode OpenWebUI performs its compatible
prompt-based tool orchestration and sends ordinary message requests to the gateway. Native
OpenAI `tools` payloads remain rejected by the gateway instead of being silently ignored.

### A separately installed OpenWebUI

For a separately installed OpenWebUI instance, add an OpenAI-compatible connection:

- URL: `http://127.0.0.1:11435/v1` when OpenWebUI runs natively;
- API key: the configured `GATEWAY_API_KEY`, or any non-empty placeholder if auth is disabled;
- model: select a model returned by `/v1/models`.

If OpenWebUI itself runs in Docker, `127.0.0.1` refers to that container. On Docker Desktop use
`http://host.docker.internal:11435/v1`. On Linux, add an explicit host-gateway mapping or use a
carefully configured local container network. Do not broaden the gateway bind without enabling
its API key.

## Stopping

Stop the stack without deleting either persistent volume:

```bash
make down
```

`make down` includes the `webui` profile, so it removes the OpenWebUI container as well even
when the last `make up` did not start it. `make purge CONFIRM=1` also deletes the data volumes.

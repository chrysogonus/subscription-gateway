ARG CODEX_VERSION=0.150.1
ARG CLAUDE_CODE_VERSION=2.1.251
ARG UV_VERSION=0.11.21

# uv is a build-time tool only: it exports uv.lock to a hash-pinned requirements
# file and is deleted before the final layer.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM node:22-slim AS provider-clients

ARG CODEX_VERSION
ARG CLAUDE_CODE_VERSION

RUN npm install --global \
        "@openai/codex@${CODEX_VERSION}" \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force

FROM python:3.12-slim

ARG GATEWAY_UID=1000
ARG APP_VERSION=dev

LABEL org.opencontainers.image.title="Subscription LLM Gateway" \
      org.opencontainers.image.description="Local OpenAI-compatible gateway for authenticated Codex and Claude Code clients" \
      org.opencontainers.image.source="https://github.com/chrysogonus/subscription-gateway" \
      org.opencontainers.image.documentation="https://github.com/chrysogonus/subscription-gateway#readme" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/gateway \
    CODEX_HOME=/home/gateway/.codex \
    DISABLE_AUTOUPDATER=1

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=provider-clients /usr/local/bin/node /usr/local/bin/node
COPY --from=provider-clients /usr/local/lib/node_modules /usr/local/lib/node_modules
# The claude symlink target really is claude.exe: that is the launcher the
# claude-code package declares in its own `bin` field, on every platform.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash \
        ca-certificates \
        git \
        libstdc++6 \
        ripgrep \
        tini \
    && ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && ln -s /usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe /usr/local/bin/claude \
    # Dependencies come from uv.lock -- the same resolution CI tests -- instead
    # of a fresh resolve at build time. `--locked` fails the build on a stale
    # lock, and the exported hashes make pip verify every download.
    && uv export --locked --no-dev --no-emit-project --format requirements.txt \
        -o /tmp/requirements.txt \
    && python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
    && python -m pip install --no-cache-dir --no-deps . \
    && rm /tmp/requirements.txt /usr/local/bin/uv \
    && useradd --create-home --uid "${GATEWAY_UID}" gateway \
    && mkdir -p /data /home/gateway/.codex /home/gateway/.claude /home/gateway/workspace \
    && chown -R gateway:gateway /data /home/gateway \
    && rm -rf /var/lib/apt/lists/*

USER gateway
ENV GATEWAY_HOST=0.0.0.0 \
    GATEWAY_ALLOW_REMOTE=true \
    GATEWAY_SQLITE_PATH=/data/gateway.db

EXPOSE 11435
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11435/health', timeout=2).read()"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["subscription-gateway", "serve"]

ARG CODEX_VERSION=0.149.0
ARG CLAUDE_CODE_VERSION=2.1.226

FROM node:22-slim AS provider-clients

ARG CODEX_VERSION
ARG CLAUDE_CODE_VERSION

RUN npm install --global \
        "@openai/codex@${CODEX_VERSION}" \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force

FROM python:3.12-slim

ARG GATEWAY_UID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/gateway \
    CODEX_HOME=/home/gateway/.codex \
    DISABLE_AUTOUPDATER=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=provider-clients /usr/local/bin/node /usr/local/bin/node
COPY --from=provider-clients /usr/local/lib/node_modules /usr/local/lib/node_modules
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
    && python -m pip install --no-cache-dir . \
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

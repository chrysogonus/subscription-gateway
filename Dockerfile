FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 gateway \
    && mkdir -p /data \
    && chown gateway:gateway /data

USER gateway
ENV GATEWAY_HOST=0.0.0.0 \
    GATEWAY_ALLOW_REMOTE=true \
    GATEWAY_SQLITE_PATH=/data/gateway.db

EXPOSE 11435
CMD ["subscription-gateway", "serve"]

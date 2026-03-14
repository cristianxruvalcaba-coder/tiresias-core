# syntax=docker/dockerfile:1
# Multi-stage build: builder → runtime (python:3.12-slim)

FROM python:3.12-slim AS builder

WORKDIR /build

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/

# Build wheel
RUN pip install --upgrade pip build && python -m build --wheel --outdir /wheels

# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Tiresias"
LABEL org.opencontainers.image.description="AI observability proxy"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Install wheel from builder
COPY --from=builder /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Copy entrypoint
COPY src/ src/

# Non-root user
RUN useradd -m -u 1000 tiresias && chown -R tiresias /app
USER tiresias

# Default ports (overridable via env)
ENV PROXY_PORT=8080
ENV DASHBOARD_PORT=3000
ENV LOG_LEVEL=info

EXPOSE ${PROXY_PORT} ${DASHBOARD_PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:${PROXY_PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn tiresias.proxy.app:app --host 0.0.0.0 --port ${PROXY_PORT} --log-level ${LOG_LEVEL}"]

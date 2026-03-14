# ============================================================
# PSKC - Predictive Secure Key Caching
# Dockerfile (Multi-stage build)
# ============================================================

# ---- Stage 1: Builder ----
# Install dependencies in an isolated stage so the final image stays smaller.
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ---- Stage 2: Runtime ----
FROM python:3.11-slim AS runtime

LABEL maintainer="PSKC Research Team"
LABEL description="Predictive Secure Key Caching - Authentication Latency Reduction"
LABEL version="1.0.0"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

RUN groupadd --gid 1001 pskc && \
    useradd --uid 1001 --gid pskc --shell /bin/bash --create-home pskc && \
    chown -R pskc:pskc /app

USER pskc

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    APP_PORT=8000 \
    LOG_LEVEL=info

CMD ["uvicorn", "src.api.routes:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

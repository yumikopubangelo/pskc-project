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

# Upgrade pip first
RUN pip install --upgrade pip setuptools wheel

# Install typing-extensions early (required by pydantic)
RUN pip install --no-cache-dir typing-extensions>=4.5.0

# ✅ FIX: Install PyTorch with --prefix so it gets copied to runtime stage
# CPU-only version for smaller image size
RUN pip install --prefix=/install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Install remaining dependencies using --prefix to /install
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt


# ---- Stage 2: Runtime ----
FROM python:3.11-slim AS runtime

LABEL maintainer="PSKC Research Team"
LABEL description="Predictive Secure Key Caching - Authentication Latency Reduction"
LABEL version="1.0.0"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy everything from builder's /install to runtime's /usr/local
COPY --from=builder /install /usr/local

# ✅ CRITICAL FIX: Ensure both typing-extensions and PyTorch are available
# Install typing-extensions again in runtime as insurance
RUN pip install --no-cache-dir typing-extensions>=4.5.0

# ✅ CRITICAL FIX: Ensure PyTorch is available in runtime
# Install PyTorch again from PyTorch's official index as backup
# In case the copy from builder stage didn't work properly
RUN pip install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

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

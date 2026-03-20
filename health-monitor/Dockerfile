FROM python:3.11-slim

# ─── Build Arguments ──────────────────────────────────────
ARG APP_USER=monitor
ARG APP_UID=1001

# ─── Labels ───────────────────────────────────────────────
LABEL maintainer="DevOps Team <devops@monitoring.local>"
LABEL version="1.0.0"
LABEL description="Container Health Monitor Agent"

# ─── Security: non-root user ──────────────────────────────
RUN groupadd -g ${APP_UID} ${APP_USER} && \
    useradd -u ${APP_UID} -g ${APP_USER} -s /sbin/nologin -M ${APP_USER}

# ─── System Dependencies ──────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# ─── Working Directory ────────────────────────────────────
WORKDIR /app

# ─── Python Dependencies ─────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ─── Application Source ───────────────────────────────────
COPY src/ ./src/
COPY main.py .

# ─── Docker socket needs special permissions ─────────────
# The monitor user is added to the docker group at runtime
# via the docker socket volume mount

# ─── Health check endpoint ───────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:${PROMETHEUS_PORT:-8000}/health || exit 1

# ─── Expose Prometheus metrics port ──────────────────────
EXPOSE 8000

# Run as non-root (socket permissions handled via group)
USER ${APP_USER}

ENTRYPOINT ["python", "-u", "main.py"]

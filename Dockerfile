"""Dockerfile for the Telegram DAV Bot."""
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
RUN pip install uv

# Copy only dependency files first for layer caching
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Create non-root user for security
RUN groupadd --gid 1000 botgroup && \
    useradd --uid 1000 --gid botgroup --shell /bin/bash botuser

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=botuser:botgroup src/ ./src/
COPY --chown=botuser:botgroup data/ ./data/
COPY --chown=botuser:botgroup pyproject.toml .

# Switch to non-root user
USER botuser

# Create data directory for SQLite and logs
RUN mkdir -p /home/botuser/data && chmod 755 /home/botuser/data

# Environment defaults (overridable at runtime)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL=sqlite+aiosqlite:///./data/bot.db \
    LOG_LEVEL=INFO \
    CHECK_INTERVAL_MINUTES=720 \
    NOTIFICATION_TIMES=12:00,17:00 \
    TIMEZONE=Asia/Ho_Chi_Minh \
    MAX_PDF_SIZE_MB=10 \
    GEMINI_MODEL=gemini-2.0-flash

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('https://api.telegram.org').raise_for_status()" || exit 1

ENTRYPOINT ["python", "-m", "src.main"]

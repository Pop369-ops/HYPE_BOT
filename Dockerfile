# ═══════════════════════════════════════════════════════════════
# HYPE_BOT v2.0 — Production Dockerfile
# Uses official Python image (pip guaranteed, no Nix surprises)
# ═══════════════════════════════════════════════════════════════

FROM python:3.11.9-slim-bookworm

# Production-grade Python settings
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONIOENCODING=UTF-8

# Working directory
WORKDIR /app

# Install system dependencies (curl for healthchecks, ca-certs for HTTPS)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tzdata && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies (cached layer if requirements unchanged)
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY HYPE_BOT.py .

# Default command
CMD ["python", "HYPE_BOT.py"]

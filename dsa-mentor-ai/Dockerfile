# Stage 1: Build React + Vite Dashboard
FROM node:20-alpine AS frontend-builder
WORKDIR /build

COPY dashboard/package*.json ./
RUN npm ci

COPY dashboard/ ./
RUN npm run build

# Stage 2: Python Backend & Production Runtime
FROM python:3.12-slim AS runner

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code, catalogue, schema, and scripts
COPY app/ ./app/
COPY data/ ./data/
COPY database/ ./database/
COPY scripts/ ./scripts/

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /build/dist ./dashboard/dist

# Ensure persistence directories exist
RUN mkdir -p database backups data/raw data/snapshots

# Security: Non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

ENV PYTHONUNBUFFERED=1 \
    API_HOST=0.0.0.0 \
    API_PORT=5000 \
    DB_PATH=/app/database/dsa_mentor.db

# Default command starts the Flask API serving both API and bundled dashboard
CMD ["python", "-m", "app.api"]

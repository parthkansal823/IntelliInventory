# ---- 1. Build the React app -------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Python API that also serves the built SPA ------------------------------------
FROM python:3.11-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY integrations/ /app/integrations/
COPY --from=web /web/dist /app/frontend/dist
ENV PATH="/app/backend/.venv/bin:$PATH" \
    FRONTEND_DIST=/app/frontend/dist \
    DATABASE_URL=sqlite:////data/intelliinventory.db
RUN mkdir -p /data
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health')"
# $PORT is set by most free hosts (Render, Railway, Koyeb, Fly); 8000 otherwise.
CMD ["sh", "-c", "alembic upgrade head || true; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

# Emby Watch Party 2.0 -- Multi-stage build
#
# Stage 1 builds the Vue frontend with Vite. Vite's outDir in
# vite.config.ts is "../backend/static", so the build artefacts land
# at /app/backend/static inside this stage; stage 2 copies that
# directory across.
#
# Stage 2 installs the Python backend, drops the built frontend into
# backend/static, and serves both via uvicorn on port 5000.

FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
# Use build-only (no vue-tsc) so type errors do not block image
# builds. Type-checking still runs in `npm run build` for dev/CI.
RUN npm run build-only


FROM python:3.12-slim
WORKDIR /app

# curl is needed for HEALTHCHECK; everything else is pure Python.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-build /app/backend/static ./backend/static/

# Pre-create the log directory so a docker-compose volume mount
# lands somewhere already-writable.
RUN mkdir -p /app/logs

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:5000/api/version || exit 1

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "5000"]

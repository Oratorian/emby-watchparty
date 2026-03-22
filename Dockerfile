# Emby Watch Party 2.0 - Multi-stage build
# Stage 1: Build Vue frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Python backend
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY --from=frontend-build /app/backend/static ./backend/static/
COPY .env* config.json* ./
EXPOSE 5000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "5000"]

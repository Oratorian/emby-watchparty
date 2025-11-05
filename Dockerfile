# Emby Watch Party - Dockerfile
# Original contribution by: MaaHeebTrackbee
# https://github.com/Oratorian/emby-watchparty

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose default port (configurable via WATCH_PARTY_PORT env var)
EXPOSE 5000

# Run the application
CMD ["python", "app.py"]

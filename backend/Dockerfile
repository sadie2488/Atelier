# Build from the repo root: docker build -f backend/Dockerfile .
FROM python:3.12-slim

# OpenCV / MediaPipe runtime libraries
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY contract/ contract/
COPY backend/ backend/

ENV PYTHONPATH=/srv
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

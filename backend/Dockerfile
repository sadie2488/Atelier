# Build from the repo root: docker build -f backend/Dockerfile .
FROM python:3.12-slim

WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY contract/ contract/
COPY backend/ backend/

WORKDIR /srv/backend
ENV PYTHONPATH=/srv/backend:/srv
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

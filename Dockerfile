# Python 3.13: the same version as CI (.github/workflows/ci.yml), so that "the tests pass" and "the
# image runs" are claims about the same interpreter.
FROM python:3.13-slim

# PYTHONUNBUFFERED is a prerequisite of the logging, not a preference: outside a terminal, stdout is
# block-buffered, so the lines of a ten-minute run would arrive bunched at the end — and would be lost
# if the process dies before flushing the buffer, which is exactly when they need reading.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies before the code: a change under backend/ does not reinstall the grpc stack.
# requirements-gcp.txt includes requirements.txt and adds Firestore — the image always carries the
# persistence backend production requires, VIGIE_STORAGE picks which one activates.
COPY backend/requirements.txt backend/requirements-gcp.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements-gcp.txt

COPY backend/ ./backend/

# Non root. The chown covers /app because under VIGIE_STORAGE=local the persistence writes below
# backend/ (backend/memory/persistence.py, _LOCAL_ROOT): without it, running the container locally —
# the step that validates the image before adding the Firestore unknown to it — would fail on
# permissions.
RUN useradd --create-home --uid 1000 veille && chown -R veille:veille /app
USER veille

EXPOSE 8080

# By default, the service that serves the digest. The daily Job reuses the same image, overriding
# the command with: python -m backend.job
CMD ["sh", "-c", "uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

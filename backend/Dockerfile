# TestPilot API / worker image. Contains NO test-runner tooling and never
# executes repository code itself (execution is delegated to a sandbox provider).
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY demo-project/ /srv/demo-project/
RUN useradd --uid 10001 --create-home app && mkdir -p /srv/backend/data && chown -R app /srv/backend/data
USER app
ENV DEMO_PROJECT_PATH=/srv/demo-project STORAGE_ROOT=/srv/backend/data/storage
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]

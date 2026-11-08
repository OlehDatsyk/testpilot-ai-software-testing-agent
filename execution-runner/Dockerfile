# TestPilot isolated test-runner image.
#
# This image contains ONLY test tooling — no TestPilot application code,
# no credentials, no database drivers. The worker starts one short-lived
# container per test job with: no network, read-only root filesystem,
# all capabilities dropped, no-new-privileges, non-root user, CPU / memory /
# PID limits and a hard timeout. See EXECUTION_SECURITY.md.

FROM node:22-bookworm-slim AS nodetools
WORKDIR /opt/runner
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund && npm cache clean --force

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir "pytest>=8.2,<9" "coverage>=7.5,<8"
COPY --from=nodetools /usr/local/bin/node /usr/local/bin/node
COPY --from=nodetools /opt/runner/node_modules /opt/runner/node_modules
COPY vitest.config.mjs runner.py /opt/runner/
# Unprivileged user; the worker additionally forces --user 65534:65534
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin runner \
    && chmod -R a+rX /opt/runner
USER 10001
WORKDIR /work
ENTRYPOINT ["python", "/opt/runner/runner.py"]

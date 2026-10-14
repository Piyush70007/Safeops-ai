# Ephemeral AI worker: Codex CLI + the gateway client + what is needed to run the tests.
# It holds no cloud, cluster or Git credentials. Its only authority is a short-lived token
# that the gateway checks against the policy on every single call.
FROM node:22-bookworm-slim
ARG CODEX_VERSION=latest
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/workspace/home WORKDIR=/workspace \
    PYTHONPATH=/opt/safeops
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends python3 python3-venv git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g npm@11.21.0 \
    && npm install -g "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force \
    && rm -rf /usr/local/lib/node_modules/npm \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx \
    && groupadd --system --gid 10001 worker \
    && useradd --system --uid 10001 --gid worker --no-create-home --shell /usr/sbin/nologin worker
COPY requirements-dev.txt requirements.txt /tmp/
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements-dev.txt \
    && /opt/venv/bin/pip install --no-cache-dir "setuptools>=78.1.1"
ENV PATH=/opt/venv/bin:$PATH
COPY ai-worker/safeops_worker /opt/safeops/safeops_worker
COPY ai-worker/skills /opt/safeops/skills
RUN printf '#!/bin/sh\nexec python -m safeops_worker.cli "$@"\n' > /usr/local/bin/safeops-tool \
    && chmod 0755 /usr/local/bin/safeops-tool
USER 10001:10001
CMD ["python", "-m", "safeops_worker.codex_runner"]

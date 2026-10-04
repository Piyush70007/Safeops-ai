# The control plane: gateway, orchestration and the fast verification gates.
# It runs the shop's test suite against proposed patches, so it needs the dev tools and git.
FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 safeops \
    && useradd --system --uid 10001 --gid safeops --create-home --shell /usr/sbin/nologin safeops
COPY requirements-dev.txt requirements.txt /tmp/
RUN pip install -r /tmp/requirements-dev.txt
WORKDIR /srv
COPY automation ./automation
COPY verification ./verification
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "--factory", "automation.controlplane.main:build", "--host", "0.0.0.0", "--port", "8080"]

# SafeOps AI - command catalogue. `make help` lists everything.
SHELL := /bin/bash
.DEFAULT_GOAL := help
PY := .venv/bin/python
CLUSTER := safeops
SHA := $(shell git rev-parse --short=12 HEAD 2>/dev/null || echo dev)
REGISTRY ?= localhost:5001
SHOP_IMAGE := $(REGISTRY)/safeops-shop:$(SHA)
CONTROL_IMAGE := $(REGISTRY)/safeops-control:$(SHA)
WORKER_IMAGE := $(REGISTRY)/safeops-ai-worker:$(SHA)
OVERLAY ?= microservices

.PHONY: help venv lint test test-policy run-monolith run-control shop-image images kind-up kind-down \
        push-images patch-image platform deploy secrets-k8s status inject reset-scenario evaluate clean

help: ## List all targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

venv: ## Create .venv with all development dependencies
	python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements-dev.txt

lint: ## Ruff lint + format check, OPA format check
	$(PY) -m ruff check . && $(PY) -m ruff format --check .
	opa fmt --list --fail automation/policy-engine/policies

test: ## All tests: app, policy, control plane, demos A/B/C (needs opa on PATH)
	$(PY) -m pytest --cov=app --cov=automation --cov-report=term-missing:skip-covered

test-policy: ## Only the Rego policy unit tests
	opa test -v automation/policy-engine/policies automation/policy-engine/data

run-monolith: ## Run the shop as a monolith on :8000 (SQLite, lab faults enabled)
	SERVICE_MODE=monolith FAULTS_ENABLED=true DATABASE_URL=sqlite+pysqlite:///./shop.db \
	  $(PY) -m uvicorn --factory app.main:build --port 8000 --reload

run-control: ## Run OPA + control plane locally (needs .env.control, see PDF 3)
	set -a && . ./.env.control && set +a && \
	  (opa run --server --addr 127.0.0.1:8181 automation/policy-engine/policies automation/policy-engine/data/catalog.json &) && \
	  $(PY) -m uvicorn --factory automation.controlplane.main:build --port 8088

shop-image: ## Build + push only the shop image (PDF 1-2)
	docker build -f platform/docker/shop.Dockerfile --build-arg GIT_SHA=$(SHA) -t $(SHOP_IMAGE) .
	docker push $(SHOP_IMAGE)

images: ## Build the three images (shop, control plane, AI worker)
	docker build -f platform/docker/shop.Dockerfile --build-arg GIT_SHA=$(SHA) -t $(SHOP_IMAGE) .
	docker build -f platform/docker/control.Dockerfile -t $(CONTROL_IMAGE) .
	docker build -f platform/docker/worker.Dockerfile -t $(WORKER_IMAGE) .

kind-up: ## Create the local Kubernetes cluster with a local image registry
	bash platform/kind/create-with-registry.sh

kind-down: ## Delete the local cluster (frees all resources)
	kind delete cluster --name $(CLUSTER)

push-images: ## Push the three images to the local registry (gives them digests)
	docker push $(SHOP_IMAGE) && docker push $(CONTROL_IMAGE) && docker push $(WORKER_IMAGE)

patch-image: ## Build + push an image of an AI patch: make patch-image INCIDENT=INC-...
	bash scripts/build-patch-image.sh $(INCIDENT)

platform: ## Install Argo Rollouts, Prometheus stack, Loki, Alloy (Helm)
	bash platform/helm/install.sh

secrets-k8s: ## Create database, control-plane and Grafana secrets (never stored in Git)
	bash platform/kubernetes/create-secrets.sh

deploy: ## Deploy: make deploy OVERLAY=shop-only|microservices|monolith
	bash platform/kubernetes/deploy.sh $(OVERLAY) $(SHOP_IMAGE) $(CONTROL_IMAGE) $(WORKER_IMAGE)

status: ## Rollouts, pods and incidents at a glance
	kubectl get rollouts -A; kubectl get pods -A -l 'app.kubernetes.io/part-of=safeops'

inject: ## Inject a scenario: make inject SCENARIO=inventory-keyerror
	$(PY) incidents/inject.py $(SCENARIO)

reset-scenario: ## Reset a scenario: make reset-scenario SCENARIO=inventory-keyerror
	$(PY) incidents/inject.py $(SCENARIO) --reset

evaluate: ## Aggregate experiment results into docs/experiments/results.md
	$(PY) evaluation/report.py

clean: ## Remove local databases, caches and evidence
	rm -rf shop.db .pytest_cache .ruff_cache .coverage evidence/

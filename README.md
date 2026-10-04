# SafeOps AI - Guarded AI Security Operations & Autonomous Remediation Lab

An AI agent investigates and fixes predefined incidents, but it is never the authority over
what it may change. JEV routes, a policy engine (OPA) authorizes every single tool call,
deterministic gates verify every patch, and Argo Rollouts decides promotion or rollback.

> Central question: how much operational autonomy can an AI agent safely receive when its
> permissions, blast radius, verification gates and rollback are explicitly controlled?

## What is in here
| Area | Implementation |
|---|---|
| Application | orders / inventory / payments, runnable as a monolith or as 3 services (FastAPI, PostgreSQL) |
| Platform | kind + Kubernetes, namespaces as blast-radius boundaries, NetworkPolicies, Argo Rollouts canaries |
| Observability | Prometheus, Alertmanager, Grafana, Loki, Alloy, SLO burn-rate alerts |
| Delivery | GitHub Actions: tests, policy tests, Gitleaks, pip-audit, Bandit, kubeconform, Terraform, Checkov, Trivy |
| Cloud | Terraform: GitHub OIDC role (no stored keys), versioned evidence bucket, budget |
| Guarded AI | JEV routing, OPA policy, tool gateway, scoped short-lived worker tokens, Codex worker, circuit breaker, kill switch |
| Verification | scope, dependencies, secrets, lint, SAST, tests, load gate, canary analysis |
| Red team | 20-attack playbook, prompt injection in logs, cross-service and guardrail-tampering attempts |
| Evaluation | offline lab + cluster runs, measured results in docs/experiments/ |

## Quick start (no cluster needed)
```bash
make venv && make test          # 58 tests: app, policy, gateway, demos A/B/C (needs opa on PATH)
.venv/bin/python evaluation/offline_lab.py   # run all scenarios, write a measured report
```

## Honest scope
The safety layer (policy, gateway, gates, red-team suite, evaluation) is fully tested. Cluster,
cloud and model runs are reproducible with the course instructions; results depend on your run.
This is a learning and portfolio lab, not a production autonomous-remediation product.

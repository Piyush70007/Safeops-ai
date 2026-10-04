# Architecture

```mermaid
flowchart TB
  fault[Bug / attack / failed deploy] --> obs[Prometheus + Loki + Grafana]
  obs -->|Alertmanager webhook| cp[SafeOps control plane]
  cp --> jev[JEV: type, component, severity, autonomy]
  cp -->|every tool call| opa[OPA policy: ALLOW / REVIEW / DENY]
  cp -->|scoped token| worker[Ephemeral Codex worker - no credentials]
  worker -->|safeops-tool| cp
  cp --> gates[Verification gates]
  gates -->|verified digest| argo[Argo Rollouts canary + analysis]
  argo -->|healthy| promote[Promote]
  argo -->|unhealthy| rollback[Rollback]
  cp --> n8n[n8n: humans informed, never authorizes]
  cp --> audit[(Hash-chained audit log)]
```

| Control plane (decides) | Execution plane (acts, holds no authority) |
|---|---|
| JEV decision, policy evaluation, approvals | Codex investigation in an isolated container |
| Grants, tokens, audit, circuit breaker | Reading logs/metrics through the gateway only |
| Verification gates, deployment authorization | Writing a patch in its own workspace |

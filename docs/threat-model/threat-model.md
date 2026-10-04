# Threat model: the AI remediation boundary

Assumption: the model can be wrong, and the model can be manipulated (prompt injection via
logs, alerts, repository content or tool output). Security must not depend on its obedience.

| Threat | Example | Control (independent of the model) | Test |
|---|---|---|---|
| Prompt injection | order note says: delete a namespace | logs marked untrusted; destructive tools hard-denied | Demo B |
| Cross-service change | fix "the real bug" in payments | grant scope, policy path check, CI scope gate | Rego, Demo C |
| Guardrail tampering | edit policy, CI, dependencies | never_writable paths | Rego tests, playbook |
| Argument manipulation | raw LogQL, path traversal, extra args | strict argument models, server-built queries, path rules | playbook |
| Credential theft | read secrets | no secrets in worker; secrets kind never readable; read_secret hard-denied | playbook |
| Self-approval | AI promotes its own change | promote_production hard-denied; Argo Rollouts decides | Rego tests, Demo A |
| Unsafe patch | SQL injection, hidden error | lint, SAST, tests, canary analysis | Demo C |
| Runaway automation | repeated attempts | circuit breaker, grant TTL, kill switch | breaker tests |
| Policy outage | OPA down | fail closed (DENY) | unit test |
| Token forgery/replay | stolen or edited token | HS256 signature, expiry, server-side grant lookup | token tests |
| Evidence tampering | edit the audit log | SHA-256 hash chain | audit test |

Residual risks (documented, not hidden): single-replica in-memory control plane (lab),
shared admin token for humans/Alertmanager/CI (use separate identities in production),
worker egress to all public HTTPS (restrict to the model API via an egress proxy in production).

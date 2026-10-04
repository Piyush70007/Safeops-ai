#!/usr/bin/env bash
# Creates every secret the lab needs with random values. Nothing is written to Git.
# Safe to re-run: existing secrets are kept (delete them first to rotate).
set -euo pipefail
rand() { openssl rand -base64 32 | tr -d '/+=' | cut -c1-32; }
create() { # namespace name key=value...
  local ns=$1 name=$2; shift 2
  if kubectl -n "$ns" get secret "$name" >/dev/null 2>&1; then echo "keep  $ns/$name"; return; fi
  kubectl -n "$ns" create secret generic "$name" $(printf -- '--from-literal=%s ' "$@") >/dev/null
  echo "made  $ns/$name"
}
kubectl create namespace observability --dry-run=client -o yaml | kubectl apply -f - >/dev/null

declare -A PW
for svc in orders inventory payments shop; do PW[$svc]=$(rand); done
create data postgres-credentials POSTGRES_PASSWORD="$(rand)" \
  ORDERS_DB_PASSWORD="${PW[orders]}" INVENTORY_DB_PASSWORD="${PW[inventory]}" \
  PAYMENTS_DB_PASSWORD="${PW[payments]}" SHOP_DB_PASSWORD="${PW[shop]}"
for svc in orders inventory payments shop; do
  create "$svc" database url="postgresql+psycopg://${svc}:${PW[$svc]}@postgres.data.svc:5432/${svc}"
done

ADMIN_TOKEN=$(rand)
create safeops safeops-control SAFEOPS_ADMIN_TOKEN="$ADMIN_TOKEN" SAFEOPS_SIGNING_KEY="$(rand)$(rand)"
create observability safeops-admin token="$ADMIN_TOKEN"          # Alertmanager -> webhook
create observability grafana-admin admin-user=admin admin-password="$(rand)"
if [[ -n "${CODEX_API_KEY:-}" ]]; then
  create safeops-workers codex-api-key key="$CODEX_API_KEY"
else
  echo "skip  safeops-workers/codex-api-key (export CODEX_API_KEY first to enable the Codex worker)"
fi
echo "Admin token for the control plane API:"
echo "  kubectl -n safeops get secret safeops-control -o jsonpath='{.data.SAFEOPS_ADMIN_TOKEN}' | base64 -d"

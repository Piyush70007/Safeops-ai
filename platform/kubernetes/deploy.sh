#!/usr/bin/env bash
# Deploy an overlay and set the images.
#   platform/kubernetes/deploy.sh <overlay> <shop-image> [<control-image> <worker-image>]
# overlays: shop-only (PDF 1-2), microservices or monolith (PDF 3-4, with the control plane)
set -euo pipefail
OVERLAY=$1 SHOP=$2 CONTROL=${3:-} WORKER=${4:-}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)

kubectl apply -k "$ROOT/platform/kubernetes/overlays/$OVERLAY"
for target in orders/orders inventory/inventory payments/payments shop/shop-monolith; do
  ns=${target%/*} name=${target#*/}
  if kubectl -n "$ns" get rollout "$name" >/dev/null 2>&1; then
    kubectl -n "$ns" patch rollout "$name" --type=json \
      -p "[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/image\",\"value\":\"$SHOP\"}]"
  fi
done
[ "$OVERLAY" = "shop-only" ] && exit 0

kubectl -n safeops create configmap opa-policies \
  --from-file="$ROOT/automation/policy-engine/policies/safeops/authz.rego" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n safeops create configmap opa-data \
  --from-file="$ROOT/automation/policy-engine/data/catalog.json" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n safeops rollout restart deployment/opa       # load the current policy
kubectl -n safeops set image deployment/safeops-control control="$CONTROL" clone="$CONTROL"
kubectl -n safeops patch configmap safeops-control --type merge \
  -p "{\"data\":{\"SAFEOPS_WORKER_IMAGE\":\"$WORKER\"}}"
kubectl -n safeops rollout restart deployment/safeops-control

#!/usr/bin/env bash
# Installs the established building blocks (spec: use them, do not rebuild them).
# Chart versions are pinned. Check for newer ones with: helm search repo <chart> --versions
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
helm repo update >/dev/null

helm upgrade --install argo-rollouts argo/argo-rollouts --version 2.43.2 \
  --namespace argo-rollouts --create-namespace --wait
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --version 91.9.0 --namespace observability --create-namespace \
  --values "$HERE/kube-prometheus-stack.yaml" --wait --timeout 10m
helm upgrade --install loki grafana/loki --version 7.4.0 --namespace observability \
  --values "$HERE/loki.yaml" --wait --timeout 10m
helm upgrade --install alloy grafana/alloy --version 1.13.0 --namespace observability \
  --values "$HERE/alloy.yaml" --wait
echo "platform installed: kubectl get pods -n observability -n argo-rollouts"

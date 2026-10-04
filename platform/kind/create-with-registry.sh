#!/usr/bin/env bash
# kind cluster + local registry (localhost:5001), following the kind local-registry guide.
# A registry gives every image a real digest, so canaries are deployed by digest, not by tag.
set -euo pipefail
REG_NAME=kind-registry REG_PORT=5001
if [ "$(docker inspect -f '{{.State.Running}}' "$REG_NAME" 2>/dev/null || true)" != "true" ]; then
  docker run -d --restart=always -p "127.0.0.1:${REG_PORT}:5000" --network bridge --name "$REG_NAME" registry:2
fi
kind create cluster --config "$(dirname "$0")/cluster.yaml"
REGISTRY_DIR="/etc/containerd/certs.d/localhost:${REG_PORT}"
for node in $(kind get nodes --name safeops); do
  docker exec "$node" mkdir -p "$REGISTRY_DIR"
  printf '[host."http://%s:5000"]\n' "$REG_NAME" | docker exec -i "$node" cp /dev/stdin "$REGISTRY_DIR/hosts.toml"
done
docker network connect kind "$REG_NAME" 2>/dev/null || true
kubectl apply -f - <<YAML
apiVersion: v1
kind: ConfigMap
metadata: {name: local-registry-hosting, namespace: kube-public}
data:
  localRegistryHosting.v1: |
    host: "localhost:${REG_PORT}"
YAML
echo "cluster 'safeops' ready; push images to localhost:${REG_PORT}/..."

#!/usr/bin/env bash
# Builds the verified AI patch into an image and registers its DIGEST with the control plane.
# (In a GitHub-hosted setup, the verify-ai-patch workflow does this instead.)
#   SAFEOPS_URL=http://localhost:8088 SAFEOPS_ADMIN_TOKEN=... scripts/build-patch-image.sh INC-...
set -euo pipefail
INCIDENT=$1
URL=${SAFEOPS_URL:-http://localhost:8088}
AUTH="Authorization: Bearer ${SAFEOPS_ADMIN_TOKEN:?export SAFEOPS_ADMIN_TOKEN}"
INFO=$(curl -sf -H "$AUTH" "$URL/incidents/$INCIDENT")
STATUS=$(echo "$INFO" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
[ "$STATUS" = "VERIFIED" ] || [ "$STATUS" = "AWAITING_APPROVAL" ] || { echo "incident is $STATUS, not VERIFIED"; exit 1; }
BASE=$(echo "$INFO" | python3 -c "import json,sys; print(json.load(sys.stdin)['base_commit'])")
WORK=$(mktemp -d)
git worktree add --detach "$WORK" "$BASE" >/dev/null
curl -sf -H "$AUTH" "$URL/incidents/$INCIDENT/patch" | git -C "$WORK" apply -
TAG="localhost:5001/safeops-shop:${INCIDENT,,}"
docker build -q -f platform/docker/shop.Dockerfile --build-arg "GIT_SHA=${INCIDENT,,}" -t "$TAG" "$WORK"
docker push -q "$TAG" >/dev/null
DIGEST=$(docker inspect --format '{{index .RepoDigests 0}}' "$TAG")
git worktree remove --force "$WORK"
curl -sf -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"image\": \"$DIGEST\"}" "$URL/incidents/$INCIDENT/artifacts"
echo; echo "registered $DIGEST for $INCIDENT"

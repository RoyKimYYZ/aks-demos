#!/bin/bash
# Runbook: Deploy & test Phi-4-reasoning-vision-15B on AKS via KAITO (vLLM)
# Usage: ./6-deploy-phi-4-reasoning-vision.sh [image-file]
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS=workspace-phi-4-reasoning-vision
MODEL=microsoft/Phi-4-reasoning-vision-15B
IMG="${1:-$DIR/salad.jpg}"

# Step 1 — Deploy
kubectl apply -f "$DIR/phi-4-reasoning-vision-workspace.yaml"
kubectl apply -f "$DIR/ingress-nginx-kaito.yaml"

# Step 2 — Wait for workspace ready (up to 45 min — 15B model is larger)
echo "Waiting for workspace (GPU ~10 min, model download+load ~20 min)..."
until kubectl get workspace $WS -o jsonpath='{.status.conditions[?(@.type=="WorkspaceSucceeded")].status}' 2>/dev/null | grep -q True; do
  kubectl get pods -l apps=phi-4-reasoning-vision --no-headers 2>/dev/null | awk '{printf "[%s] %s %s\n",strftime("%H:%M:%S"),$1,$3}' || true
  sleep 30
done
echo "Workspace READY"

# Step 3 — Get ingress endpoint
INGRESS_IP=$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
ENDPOINT="https://$INGRESS_IP/phi4rv"
HOST_HDR="-H Host:ai.roykim.ca"
echo "Ingress endpoint: $ENDPOINT (Host: ai.roykim.ca)"

# Step 4 — Text-only test
echo -e "\n--- Text test ---"
curl -sk -m120 $HOST_HDR -XPOST "$ENDPOINT/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"What language model are you? Describe your version and capabilities.\"}],\"max_tokens\":120}" \
| jq -r '.choices[0].message.content'

# Step 5 — Vision test (base64 image via ingress)
echo -e "\n\n--- Vision test: $IMG ---"
[ -f "$IMG" ] || { echo "Image not found: $IMG" >&2; exit 1; }
REQ=$(mktemp); trap "rm -f $REQ" EXIT
B64=$(base64 -w0 "$IMG") MIME=$(file --mime-type -b "$IMG")
cat >"$REQ" <<JSON
{"model":"$MODEL","messages":[{"role":"user","content":[
{"type":"text","text":"List each ingredient in this meal made for an individual. In detail, list each ingredient's macronutrients, then totals."},
{"type":"image_url","image_url":{"url":"data:$MIME;base64,$B64"}}]}],"max_tokens":1024}
JSON
curl -sk -m180 $HOST_HDR -XPOST "$ENDPOINT/v1/chat/completions" \
  -H "Content-Type: application/json" -d @"$REQ" \
  | jq -r '.choices[0].message.content'

# Teardown: kubectl delete workspace workspace-phi-4-reasoning-vision

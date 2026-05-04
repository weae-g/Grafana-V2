#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== Keenetic Agent Deploy ==="
echo ""

if [ ! -f .env ]; then
  echo "ERROR: .env не найден."
  echo "  cp .env.example .env"
  echo "  nano .env"
  exit 1
fi

if ! command -v docker &>/dev/null; then
  echo "ERROR: Docker не установлен."
  echo "  curl -fsSL https://get.docker.com | sh"
  exit 1
fi

# Read vars from .env without sourcing (handles comments safely)
_val() { grep -E "^${1}=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"; }
ROUTER_ID=$(_val ROUTER_ID)
MEM_AGENT=$(_val MEM_AGENT)
ROUTER_ID=${ROUTER_ID:-agent}
MEM_AGENT=${MEM_AGENT:-256m}

CONTAINER="keenetic-agent-${ROUTER_ID}"
IMAGE="keenetic-agent-${ROUTER_ID}"

echo "Router ID:    $ROUTER_ID"
echo "Container:    $CONTAINER"
echo "Memory limit: $MEM_AGENT"
echo ""

echo ">>> Building image: $IMAGE"
docker build -t "$IMAGE" .

echo ""
echo ">>> Stopping old container (if running)"
docker stop "$CONTAINER" 2>/dev/null && echo "  Stopped $CONTAINER" || true
docker rm   "$CONTAINER" 2>/dev/null && echo "  Removed $CONTAINER" || true

echo ""
echo ">>> Starting $CONTAINER"
docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  --network host \
  --memory "$MEM_AGENT" \
  -v "$(pwd)/.env:/app/.env:ro" \
  "$IMAGE"

echo ""
echo "=== Готово ==="
docker ps --filter "name=${CONTAINER}" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
echo ""
echo "Логи (Ctrl+C — выйти без остановки контейнера):"
sleep 2
docker logs -f "$CONTAINER"

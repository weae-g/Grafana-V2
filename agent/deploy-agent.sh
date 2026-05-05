#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== Keenetic Agent Deploy ==="
echo ""

# ── .env check ────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  echo "ERROR: .env не найден."
  echo "  cp .env.example .env && nano .env"
  exit 1
fi

# ── Docker check ──────────────────────────────────────────────────────────────
export PATH="$PATH:/usr/bin:/usr/local/bin"
if ! command -v docker &>/dev/null; then
  echo "Docker не установлен. Установить сейчас? [y/N]"
  read -r answer
  if [[ "$answer" =~ ^[Yy]$ ]]; then
    echo ">>> Устанавливаю Docker..."
    curl -fsSL https://get.docker.com | sh
    echo ""
  else
    echo "Установи Docker вручную: curl -fsSL https://get.docker.com | sh"
    exit 1
  fi
fi

# ── Read .env (|| true — чтобы set -e не убивал скрипт при отсутствии ключа) ──
_val() { grep -E "^${1}=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" || true; }
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

# ── Build ─────────────────────────────────────────────────────────────────────
echo ">>> Building image: $IMAGE"
docker build -t "$IMAGE" .

# ── Stop & remove old container if exists ─────────────────────────────────────
echo ""
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo ">>> Контейнер $CONTAINER уже существует — пересоздаю"
  docker stop "$CONTAINER" 2>/dev/null || true
  docker rm   "$CONTAINER" 2>/dev/null || true
else
  echo ">>> Старого контейнера нет — создаю новый"
fi

# ── Start ─────────────────────────────────────────────────────────────────────
echo ""
echo ">>> Starting $CONTAINER"
docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  --network host \
  --memory "$MEM_AGENT" \
  -v "$(pwd)/.env:/app/.env:ro" \
  "$IMAGE"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=== Готово ==="
docker ps --filter "name=${CONTAINER}" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
echo ""
echo "Логи (Ctrl+C — выйти без остановки контейнера):"
sleep 2
docker logs -f "$CONTAINER"

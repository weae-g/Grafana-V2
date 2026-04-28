#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "=== Keenetic Monitor — Deploy ==="
echo ""

# Check server .env
if [ ! -f server/.env ]; then
  echo "ERROR: server/.env не найден."
  echo "Создай его из примера и заполни:"
  echo "  cp server/.env.example server/.env"
  echo "  nano server/.env"
  exit 1
fi

# Check agent .env
if [ ! -f agent/.env ]; then
  echo "ERROR: agent/.env не найден."
  echo "Создай его из примера и заполни:"
  echo "  cp agent/.env.example agent/.env"
  echo "  nano agent/.env"
  exit 1
fi

echo ">>> git pull"
git pull

echo ""
echo ">>> docker compose build + start"
cd server
docker compose up -d --build

echo ""
echo "=== Статус контейнеров ==="
docker compose ps

echo ""
echo "=== Готово ==="
echo "Grafana:  http://$(hostname -I | awk '{print $1}'):3000"
echo "Receiver: http://$(hostname -I | awk '{print $1}'):8080/health"
echo ""
echo "Логи:"
echo "  docker compose logs -f receiver"
echo "  docker compose logs -f agent"
echo "  docker compose logs -f ping_monitor"

#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== Keenetic Monitor — Server Deploy ==="
echo ""

if [ ! -f server/.env ]; then
  echo "ERROR: server/.env не найден."
  echo "  cp server/.env.example server/.env"
  echo "  nano server/.env"
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
LOCAL_IP=$(hostname -I | awk '{print $1}')
echo "Grafana:  http://${LOCAL_IP}:3000"
echo "Receiver: http://${LOCAL_IP}:8080/health"
echo ""
echo "Деплой агента на удалённый сервер:"
echo "  scp -r agent/ user@SERVER:/opt/keenetic-agent"
echo "  ssh user@SERVER 'cd /opt/keenetic-agent && bash deploy-agent.sh'"
echo ""
echo "Логи:"
echo "  cd server && docker compose logs -f receiver"
echo "  cd server && docker compose logs -f grafana"

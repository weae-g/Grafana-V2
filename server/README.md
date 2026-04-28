# Keenetic Monitor — Server (Receiver + InfluxDB + Grafana)

Центральный сервер. Принимает зашифрованные метрики от **50+ агентов**, хранит в InfluxDB с автоматической очисткой по времени, отображает в Grafana.

Всё поднимается одной командой через Docker Compose. Ты заходишь в браузер — видишь все роутеры сразу. Никакого ПО устанавливать не нужно.

---

## Требования

- Ubuntu 20.04+ / Debian 11+
- Docker 24+ и Docker Compose v2
- Открытые порты: `8080` (receiver), `3000` (Grafana)
- Минимум 1 GB RAM, 10 GB диска

---

## Установка

### 1. Установить Docker (если ещё не стоит)

```bash
# Подключиться к серверу
ssh user@central-server

# Установить Docker одной командой
curl -fsSL https://get.docker.com | sh

# Установить Docker Compose v2 plugin (нужен отдельно на некоторых системах)
sudo apt-get install -y docker-compose-plugin

# Добавить своего пользователя в группу docker (чтобы не писать sudo)
sudo usermod -aG docker $USER
newgrp docker

# Проверить — обе команды должны выдать версию
docker --version        # Docker version 24.x.x
docker compose version  # Docker Compose version v2.x.x
```

> Если `docker compose version` не работает, но работает `docker-compose --version` —  
> у тебя старый v1. Либо установить plugin выше, либо заменить все команды на `docker-compose` (с дефисом).

### 2. Скопировать папку `server/` на сервер

```bash
# Выполнить на своём компе:
scp -r server/ user@central-server:/opt/keenetic-monitor

# Подключиться и перейти в папку
ssh user@central-server
cd /opt/keenetic-monitor
```

### 3. Настроить конфигурацию

```bash
cp .env.example .env
nano .env
```

> **Важно:** не добавляй комментарии (`#`) в конец строк со значениями — Docker  
> берёт всё после `=` буквально, включая комментарий, и токен сломается.  
> Комментарии ставь только на отдельных строках, как в `.env.example`.

Обязательно заменить:

| Переменная | Описание |
|---|---|
| `ENCRYPTION_KEY` | Пароль шифрования (тот же что на агентах) |
| `DOCKER_INFLUXDB_INIT_PASSWORD` | Пароль InfluxDB admin |
| `DOCKER_INFLUXDB_INIT_ADMIN_TOKEN` | Токен InfluxDB (придумать длинный) |
| `INFLUXDB_TOKEN` | Тот же токен (скопировать из строки выше) |
| `GF_SECURITY_ADMIN_PASSWORD` | Пароль Grafana |

> Пример безопасного токена: `openssl rand -hex 32`

### 3. Запустить

```bash
docker compose up -d
```

Проверить что всё запустилось:

```bash
docker compose ps
docker compose logs -f receiver
```

### 4. Проверить receiver

```bash
curl http://localhost:8080/health
# {"status": "ok", "influxdb": true}
```

### 5. Открыть Grafana

Перейти в браузере: `http://your-server-ip:3000`

- Логин: значение `GF_SECURITY_ADMIN_USER` (по умолчанию `admin`)
- Пароль: значение `GF_SECURITY_ADMIN_PASSWORD`

Дашборд **Keenetic Monitor** появится автоматически в папке **Keenetic**.

---

## Структура

```
server/
├── receiver.py              # HTTP-сервер: принимает, дешифрует, пишет в InfluxDB
├── docker-compose.yml       # influxdb + receiver + grafana
├── Dockerfile               # образ для receiver
├── .env                     # конфигурация (создать из .env.example)
└── grafana/
    ├── provisioning/
    │   ├── datasources/     # автоподключение InfluxDB
    │   └── dashboards/      # автозагрузка дашбордов
    └── dashboards/
        └── keenetic.json    # готовый дашборд
```

---

## Хранение данных (retention)

Настраивается в `.env` через `DOCKER_INFLUXDB_INIT_RETENTION`.

| Роутеров | 30 дней | 45 дней | 90 дней |
|---|---|---|---|
| 10 роутеров | ~3 GB | ~5 GB | ~10 GB |
| 50 роутеров | ~16 GB | ~24 GB | ~48 GB |
| 100 роутеров | ~32 GB | ~48 GB | — |

**Рекомендация для 50 роутеров и 20 GB диска:**

```
DOCKER_INFLUXDB_INIT_RETENTION=720h   # 30 дней ≈ 16 GB
```

InfluxDB автоматически удаляет данные старше этого периода. Изменить retention уже после запуска:

```bash
# Найти bucket ID
docker exec keenetic-influxdb influx bucket list --org keenetic --token YOUR_TOKEN

# Обновить retention
docker exec keenetic-influxdb influx bucket update \
  --id BUCKET_ID \
  --retention 1080h \
  --org keenetic \
  --token YOUR_TOKEN
```

---

## Управление

```bash
# Посмотреть логи receiver
docker compose logs -f receiver

# Перезапустить только receiver (после изменения .env)
docker compose restart receiver

# Остановить всё
docker compose down

# Остановить и удалить данные (осторожно!)
docker compose down -v
```

---

## Безопасность

### Закрыть порты от интернета (рекомендуется)

Receiver `8080` должен быть доступен только агентам. Если агенты подключены через WireGuard, можно слушать только на WG-интерфейсе:

```bash
# В .env:
LISTEN_HOST=10.0.1.1   # IP сервера в WG-сети
```

Или настроить firewall:

```bash
# Разрешить только из WG-сети
ufw allow from 10.0.1.0/24 to any port 8080
ufw deny 8080
```

Grafana `3000` — оставить открытой или за nginx с HTTPS.

### Nginx + HTTPS (опционально)

```bash
apt install nginx certbot python3-certbot-nginx
```

Пример конфига `/etc/nginx/sites-available/grafana`:

```nginx
server {
    listen 443 ssl;
    server_name monitor.example.com;
    
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
    }
}
```

---

## Диагностика

**Данные не приходят:**
```bash
docker compose logs receiver   # смотреть ошибки дешифрования
```

**Grafana не видит данные:**
1. Открыть Grafana → Configuration → Data Sources → InfluxDB → Test
2. Проверить что переменная `router` в дашборде не пустая

**InfluxDB не запускается:**
```bash
docker compose logs influxdb
# Если база уже инициализирована, убрать DOCKER_INFLUXDB_INIT_* из .env
```

---

## Обновление дашборда

Отредактировать `grafana/dashboards/keenetic.json` и перезапустить Grafana:

```bash
docker compose restart grafana
```

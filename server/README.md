# Keenetic Monitor — Server (Receiver + InfluxDB + Grafana)

Центральный сервер. Принимает зашифрованные метрики от **50+ агентов**, хранит в InfluxDB с автоматической очисткой по времени, отображает в Grafana.

Всё поднимается одной командой через Docker Compose. Ты заходишь в браузер — видишь все роутеры сразу. Никакого ПО устанавливать не нужно.

---

## Требования

- Ubuntu 20.04+ / Debian 11+ (проверено на Ubuntu 24.04)
- Минимум 1 GB RAM, 10 GB диска
- Открытые порты: `8080` (receiver), `3000` (Grafana)

---

## Установка

### 1. Установить Docker

> **Не используй `apt install docker.io`** — это старый пакет Ubuntu без Compose v2.  
> Используй официальный скрипт от Docker Inc:

```bash
curl -fsSL https://get.docker.com | sh
```

Скрипт сам установит `docker-ce` + `docker-compose-plugin`. После установки:

```bash
# Добавить пользователя в группу docker
sudo usermod -aG docker $USER
newgrp docker

# Проверить — обе команды должны выдать версию
docker --version        # Docker version 29.x.x
docker compose version  # Docker Compose version v2.x.x
```

> **Частая ошибка:** если сначала поставил `docker.io`, а потом запустил скрипт get.docker.com —
> два пакета конфликтуют, демон не стартует.  
> Решение: `apt remove docker.io -y`, затем `systemctl restart docker`.

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

> **Критически важно:** не пиши комментарии (`# текст`) в конце строк со значениями.  
> Docker читает всё после `=` буквально — токен станет `my-token   # комментарий` и сломается.  
> Комментарии только на отдельных строках (строка начинается с `#`).

Обязательно заменить:

| Переменная | Описание |
|---|---|
| `ENCRYPTION_KEY` | Пароль шифрования (тот же что на всех агентах) |
| `DOCKER_INFLUXDB_INIT_PASSWORD` | Пароль InfluxDB admin |
| `DOCKER_INFLUXDB_INIT_ADMIN_TOKEN` | Токен InfluxDB — сгенерировать: `openssl rand -hex 32` |
| `INFLUXDB_TOKEN` | **Тот же токен** что выше — скопировать |
| `GF_SECURITY_ADMIN_PASSWORD` | Пароль Grafana |

### 4. Запустить

```bash
docker compose up -d
```

> **Предупреждение про `version`:** если видишь `the attribute 'version' is obsolete` — это не ошибка,
> просто предупреждение. Compose работает нормально.

Проверить что всё поднялось:

```bash
docker compose ps
```

Ожидаемый результат (все три `Up`):
```
NAME                STATUS
keenetic-grafana    Up X seconds
keenetic-influxdb   Up X seconds (healthy)
keenetic-receiver   Up X seconds
```

### 5. Проверить receiver

```bash
# Только GET, не POST
curl http://localhost:8080/health
# {"status": "ok", "influxdb": true}
```

> **Частая ошибка:** `/health` принимает только GET. `curl -X POST /health` вернёт 405 — это нормально.

### 6. Открыть Grafana

Перейти в браузере: `http://your-server-ip:3000`

- Логин: `GF_SECURITY_ADMIN_USER` (по умолчанию `admin`)
- Пароль: `GF_SECURITY_ADMIN_PASSWORD`

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

Изменить retention уже после запуска:

```bash
docker exec keenetic-influxdb influx bucket list --org keenetic --token YOUR_TOKEN
docker exec keenetic-influxdb influx bucket update \
  --id BUCKET_ID --retention 1080h --org keenetic --token YOUR_TOKEN
```

---

## Управление

```bash
docker compose logs -f receiver     # логи receiver в реальном времени
docker compose restart receiver     # перезапустить после изменения .env
docker compose down                 # остановить всё
docker compose down -v              # остановить и удалить данные (осторожно!)
```

---

## Безопасность

Receiver `8080` — закрыть для всех кроме WG-сети агентов:

```bash
ufw allow from 10.0.1.0/24 to any port 8080
ufw deny 8080
```

Grafana `3000` — оставить открытой или поставить за nginx с HTTPS.

---

## Диагностика

### receiver постоянно рестартует

```bash
docker compose logs receiver
```

**`IsADirectoryError: /app/receiver.log`** — Docker создал директорию вместо файла при монтировании volume.

```bash
# Удалить директорию-мусор
rm -rf ./receiver.log
# Убедиться что volume mount убран из docker-compose.yml (в текущей версии его нет)
docker compose up -d --build receiver
```

### Данные не приходят от агентов

```bash
docker compose logs receiver   # смотреть ошибки дешифрования
```

Ошибка `invalid token` — ENCRYPTION_KEY на агенте и сервере не совпадают.

### Grafana не видит данные

1. Grafana → Connections → Data Sources → InfluxDB → Test
2. Проверить что переменная `router` в дашборде не пустая (выбрать роутер из списка)

### InfluxDB не запускается повторно

```bash
docker compose logs influxdb
```

Если база уже была инициализирована — убрать `DOCKER_INFLUXDB_INIT_*` переменные из `.env` перед повторным запуском.

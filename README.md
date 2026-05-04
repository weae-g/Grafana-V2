# Keenetic Monitor

Система мониторинга роутеров Keenetic с LTE. Агенты на серверах рядом с роутерами опрашивают API,
шифруют метрики и отправляют на центральный сервер. Там — InfluxDB + Grafana.

```
Агент-сервер 1 (рядом с Keenetic)  ──────────────────────────────►┐
Агент-сервер 2 (рядом с Keenetic)  ──────────────────────────────►│  PUSH (AES/Fernet)
...                                                                │
Агент-сервер N (рядом с Keenetic)  ──────────────────────────────►│
                                                                   ▼
                                              ┌────────────────────────────┐
                                              │    Центральный сервер      │
                                              │    (1 VPS, нужен публичный IP)
                                              │                            │
                                              │  receiver   :8080          │
                                              │  InfluxDB   :8086 (внутри)│
                                              │  Grafana    :3000          │
                                              └────────────────────────────┘
                                                           │
                                                  браузер с любого компа
```

---

## Что нужно заранее

На каждом **агент-сервере:**
- Ubuntu 20.04+ / Debian 11+ с Docker (`curl -fsSL https://get.docker.com | sh`)
- WireGuard-туннель до Keenetic уже поднят
- Роутер Keenetic доступен по IP через туннель (проверить: `ping 192.168.1.1`)

На **центральном сервере:**
- Ubuntu 20.04+ / Debian 11+ с Docker и Docker Compose
- Публичный IP (или порт 8080 доступен агент-серверам)
- Свободно ≥ 10 GB RAM (из 20 GB: ~9 GB резервируется под контейнеры)

**Придумать и записать два значения — они нужны на всех серверах:**

| Переменная | Назначение | Пример |
|---|---|---|
| `ENCRYPTION_KEY` | Шифрование трафика агент → сервер | `my-super-secret-key-2024` |
| `INFLUXDB_TOKEN` | Токен доступа к InfluxDB | `openssl rand -hex 32` |

`ENCRYPTION_KEY` одинаковый на всех агентах и сервере. `INFLUXDB_TOKEN` только на сервере (два раза).

---

## Шаг 1 — Агент (на каждом агент-сервере)

Выполняется на сервере, который стоит рядом с Keenetic-роутером.

### 1.1. Скопировать файлы агента на сервер

```bash
# С твоего компа:
scp -r agent/ user@AGENT-SERVER:/opt/keenetic-agent
```

### 1.2. Подключиться к серверу и перейти в папку

```bash
ssh user@AGENT-SERVER
cd /opt/keenetic-agent
```

### 1.3. Настроить конфигурацию

```bash
cp .env.example .env
nano .env
```

Заполнить:

```ini
KEENETIC_IP=192.168.1.1          # IP роутера через WireGuard-туннель
KEENETIC_PORT=80
KEENETIC_USER=admin
KEENETIC_PASS=пароль-роутера

RECEIVER_URL=http://CENTRAL-SERVER-IP:8080   # публичный IP центрального сервера
ENCRYPTION_KEY=my-super-secret-key-2024      # тот же что на сервере

ROUTER_ID=router-spb-01          # уникальное имя этого роутера (латиница, без пробелов)
POLL_INTERVAL=60                 # интервал опроса в секундах

WG_INTERFACE=Wireguard1          # WG-интерфейс мониторинга на Keenetic
LTE_INTERFACE=UsbLte0            # LTE-интерфейс

MEM_AGENT=256m                   # лимит памяти контейнера (хватает с запасом)
```

> Чтобы узнать имена интерфейсов — в веб-интерфейсе Keenetic раздел "Интернет" или
> через туннель: `curl -s http://192.168.1.1/rci/show/interface | python3 -m json.tool | grep '"id"'`

### 1.4. Запустить агента

```bash
bash deploy-agent.sh
```

Скрипт соберёт Docker-образ, запустит контейнер `keenetic-agent-${ROUTER_ID}` и покажет логи.
Успешный старт выглядит так:

```
2024-01-15 12:00:00 [INFO] Agent starting | router=router-spb-01 keenetic=192.168.1.1:80 ...
2024-01-15 12:00:01 [INFO] Sent to receiver: 4821 B raw → 6548 B encrypted
```

Ошибка `Connection refused` на строке `Sent to receiver` — нормально, пока сервер не поднят.
Агент продолжит попытки каждые `POLL_INTERVAL` секунд.

### 1.5. Проверить что контейнер работает

```bash
docker ps --filter name=keenetic-agent
docker logs keenetic-agent-router-spb-01 --tail 20
```

---

## Шаг 2 — Центральный сервер (один раз)

### 2.1. Склонировать репозиторий

```bash
ssh user@CENTRAL-SERVER
git clone https://github.com/weae-g/Grafana-V2.git /opt/keenetic-monitor
cd /opt/keenetic-monitor
```

### 2.2. Настроить конфигурацию сервера

```bash
cp server/.env.example server/.env
nano server/.env
```

Заполнить обязательные поля:

```ini
ENCRYPTION_KEY=my-super-secret-key-2024     # тот же что на агентах

INFLUXDB_TOKEN=вставить-сюда-токен          # из openssl rand -hex 32
DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=тот-же-токен  # повторить тот же токен

GF_SECURITY_ADMIN_PASSWORD=придумать-пароль-grafana
```

Опционально — лимиты памяти (чтобы контейнеры не съели все 20 GB):

```ini
MEM_INFLUXDB=8g       # главный потребитель; снизь до 4g если роутеров мало
MEM_GRAFANA=512m
MEM_RECEIVER=256m
MEM_PING_MONITOR=128m
```

### 2.3. Запустить серверный стек

```bash
bash deploy.sh
```

Скрипт сделает `git pull` и поднимет: InfluxDB, Receiver, Ping Monitor, Grafana.

Проверить что всё поднялось:

```bash
cd server
docker compose ps
curl http://localhost:8080/health
# Должно вернуть: {"status":"ok","influxdb":true}
```

### 2.4. Открыть Grafana

```
http://CENTRAL-SERVER-IP:3000
Логин:  admin
Пароль: тот что задал в GF_SECURITY_ADMIN_PASSWORD
```

Дашборд "Keenetic Monitor" уже подключён автоматически.
Как только агент начнёт присылать данные — метрики появятся в течение 1–2 минут.

---

## Добавить ещё один роутер

Для каждого нового роутера — повторить Шаг 1 на его агент-сервере с уникальным `ROUTER_ID`.
В Grafana появится новый роутер в выпадающем списке автоматически — ничего настраивать не нужно.

```
Агент-сервер 1: ROUTER_ID=router-spb-01
Агент-сервер 2: ROUTER_ID=router-msk-02
Агент-сервер 3: ROUTER_ID=router-ekb-03
```

> Если несколько роутеров на одном агент-сервере — можно запустить несколько контейнеров.
> Каждый имеет свою папку с `.env` и свой `ROUTER_ID`.

---

## Обновить агент или сервер

**Агент** (на агент-сервере):
```bash
cd /opt/keenetic-agent
git pull   # или scp новых файлов
bash deploy-agent.sh
```

**Сервер** (на центральном сервере):
```bash
cd /opt/keenetic-monitor
bash deploy.sh
```

---

## Лимиты памяти

Все лимиты задаются в `server/.env` и применяются при следующем `bash deploy.sh`.
Если сервер начинает тормозить — первым делом снизить `MEM_INFLUXDB`:

| Контейнер | Переменная | По умолчанию | Минимум |
|---|---|---|---|
| InfluxDB | `MEM_INFLUXDB` | `8g` | `2g` |
| Grafana | `MEM_GRAFANA` | `512m` | `256m` |
| Receiver | `MEM_RECEIVER` | `256m` | `128m` |
| Ping Monitor | `MEM_PING_MONITOR` | `128m` | `64m` |
| Агент | `MEM_AGENT` | `256m` | `128m` |

Посмотреть текущее потребление всех контейнеров:
```bash
docker stats --no-stream
```

---

## Порты и файрвол

| Порт | Сервис | Кто подключается |
|---|---|---|
| `8080` | Receiver | Агент-серверы |
| `3000` | Grafana | Браузер |
| `8086` | InfluxDB | Только внутри Docker (не открывать) |

Рекомендуется ограничить `8080` только IP-адресами агент-серверов:
```bash
ufw allow from AGENT-SERVER-IP to any port 8080
ufw deny 8080
```

---

## Структура проекта

```
keenetic-monitor/
├── deploy.sh                    ← деплой центрального сервера
├── agent/
│   ├── deploy-agent.sh          ← деплой агента (запускать на агент-сервере)
│   ├── agent.py
│   ├── Dockerfile
│   ├── .env.example
│   └── requirements.txt
└── server/
    ├── receiver.py
    ├── ping_monitor.py
    ├── docker-compose.yml
    ├── Dockerfile
    ├── .env.example
    └── grafana/
        ├── provisioning/
        └── dashboards/keenetic.json
```

---

## Что мониторится

| Метрика | Откуда | Интервал |
|---|---|---|
| CPU, RAM, uptime, соединения | Keenetic API | 60 сек |
| LTE сигнал (RSSI / RSRP / RSRQ / SINR) | Keenetic API | 60 сек |
| LTE оператор, тип сети | Keenetic API | 60 сек |
| Трафик WireGuard (суммарный + по пирам) | Keenetic API | 60 сек |
| Активные устройства, трафик по хостам | Keenetic API | 60 сек |
| Модель роутера, версия прошивки | Keenetic API | 60 сек |
| Интернет-доступность (ping 8.8.8.8) | Агент | 60 сек |
| Ping-мониторинг станций | ping_monitor | настраивается |

---

## Диагностика

**Агент не видит роутер:**
```bash
ping 192.168.1.1                        # проверить WireGuard-туннель
curl -v http://192.168.1.1/auth         # проверить доступность API
```

**Данные не доходят до сервера:**
```bash
curl http://CENTRAL-SERVER-IP:8080/health   # сервер доступен?
docker logs keenetic-agent-router-spb-01 --tail 50  # ошибки агента
```

**Нет данных в Grafana:**
```bash
cd server && docker compose logs receiver --tail 50   # ошибки receiver
docker compose logs influxdb --tail 20                # ошибки БД
```

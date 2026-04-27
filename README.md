# Keenetic Monitor

Система мониторинга роутеров **Keenetic** с LTE. Собирает метрики через API роутера,
передаёт их зашифрованными на центральный сервер, отображает в Grafana.

---

## Архитектура

```
Сервер-01 (рядом с Keenetic)          ┐
  agent.py ──────────────────────────►│
                                      │
Сервер-02 (рядом с Keenetic)          │  зашифрованный PUSH
  agent.py ──────────────────────────►│  (HTTP POST, Fernet/AES)
                                      │
...                                   │
                                      │
Сервер-50                             │
  agent.py ──────────────────────────►│
                                      ▼
                          ┌───────────────────────┐
                          │   Центральный сервер   │  ← нужен публичный IP
                          │   (1 VPS, ~5$/мес)     │
                          │                        │
                          │  receiver :8080        │  принимает от всех агентов
                          │  InfluxDB :8086        │  хранит (только внутри)
                          │  Grafana  :3000        │  веб-интерфейс
                          └───────────┬───────────┘
                                      │
                            твой браузер на любом компе
                            (логин/пароль Grafana)
                            ключ шифрования вводить не нужно
```

**Ключ шифрования** — только между агентами и receiver.  
Ты открываешь браузер на своём компе, вводишь логин/пароль Grafana и видишь все 50 роутеров.

**Данные шифруются** в transit (Fernet/AES-128-CBC + HMAC). Без ключа расшифровать перехваченный трафик невозможно.

---

## С чего начать

> Сначала всегда поднимается **центральный сервер**, потом агенты.  
> Без работающего сервера агент некуда слать данные.

**Придумай два значения и запиши — они нужны везде:**

| Что | Пример | Где используется |
|---|---|---|
| `ENCRYPTION_KEY` | `my-secret-key-2024` | в `.env` сервера и каждого агента |
| `INFLUXDB_TOKEN` | `openssl rand -hex 32` | в `.env` сервера (два раза) |

---

## Быстрый старт

### Шаг 1 — Центральный сервер (один раз)

```bash
# На центральном сервере:
cd server/
cp .env.example .env
nano .env          # задать ENCRYPTION_KEY, токены, пароли
docker compose up -d
curl http://localhost:8080/health   # должно вернуть {"status":"ok","influxdb":true}
```

Grafana откроется по адресу `http://your-server:3000`

### Шаг 2 — Агент (на каждый сервер с Keenetic)

```bash
# На сервере рядом с роутером:
cd agent/
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env          # задать IP роутера, пароль Keenetic, URL сервера, ENCRYPTION_KEY
python agent.py    # тест
# Если работает — установить как сервис:
sudo cp keenetic-agent.service /etc/systemd/system/
sudo systemctl enable --now keenetic-agent
```

---

## Ключ шифрования

Задаётся в `.env` обеих сторон:

```
ENCRYPTION_KEY=мой-секретный-пароль-любой-длины
```

Используется для генерации AES-ключа через PBKDF2 (100 000 итераций, SHA-256).
**Одинаковый** на агенте и сервере — это единственное условие.

---

## Что мониторится

| Метрика | Обновление |
|---|---|
| CPU нагрузка, RAM, uptime | каждые 60 сек |
| LTE сигнал (RSSI/RSRP/RSRQ/SINR), оператор | каждые 60 сек |
| Трафик LTE (rx/tx bytes → rate) | каждые 60 сек |
| WireGuard трафик | каждые 60 сек |
| Активные устройства в сети | каждые 60 сек |
| Трафик по каждому устройству (MAC/hostname) | каждые 60 сек |

---

## Несколько роутеров

Каждый агент имеет уникальный `ROUTER_ID`. В Grafana — выпадающий список роутеров,
можно смотреть на один или на все сразу через `All`.

---

## Структура проекта

```
keenetic-monitor/
├── README.md            ← этот файл
├── agent/               ← агент (на каждый сервер с роутером)
│   ├── README.md
│   ├── agent.py
│   ├── .env.example
│   ├── requirements.txt
│   └── keenetic-agent.service
└── server/              ← центральный сервер (один)
    ├── README.md
    ├── receiver.py
    ├── docker-compose.yml
    ├── Dockerfile
    ├── .env.example
    ├── requirements.txt
    └── grafana/
        ├── provisioning/
        │   ├── datasources/influxdb.yml
        │   └── dashboards/dashboard.yml
        └── dashboards/keenetic.json
```

---

## Порты

| Порт | Сервис | Кто обращается |
|---|---|---|
| `8080` | Receiver (HTTP) | Агенты |
| `8086` | InfluxDB | Receiver (внутри docker) |
| `3000` | Grafana | Браузер |

Рекомендуется закрыть `8080` для интернета, оставить только для WireGuard-сети агентов.

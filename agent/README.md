# Keenetic Monitor — Agent

Скрипт запускается **на каждом сервере** рядом с Keenetic-роутером.  
Подключается к роутеру через WireGuard-туннель, опрашивает API, шифрует данные и отправляет на центральный сервер.

---

## Требования

- Ubuntu 20.04+ / Debian 11+ (или любой Linux с Python 3.9+)
- Python 3.9 или новее
- WireGuard-туннель до Keenetic должен быть уже поднят
- Доступ к роутеру по IP `192.168.1.1` (или другому из `.env`)

---

## Установка

### 1. Проверить Python и установить если нужно

```bash
# Подключиться к серверу
ssh user@your-server

# Проверить версию Python
python3 --version   # нужно 3.9 или новее

# Если Python не установлен или старый:
sudo apt update && sudo apt install -y python3 python3-pip python3-venv
```

### 2. Проверить что WireGuard-туннель до Keenetic работает

```bash
# Должен быть ping до роутера
ping -c 3 192.168.1.1

# Если нет — проверить статус WireGuard
sudo wg show
```

### 3. Скопировать файлы на сервер

```bash
# Выполнить на своём компе:
scp -r agent/ user@your-server:/opt/keenetic-agent

# Подключиться и перейти в папку
ssh user@your-server
cd /opt/keenetic-agent
```

### 4. Создать виртуальное окружение и установить зависимости

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Настроить конфигурацию

```bash
cp .env.example .env
nano .env
```

Заполнить обязательные поля:

| Поле | Описание | Пример |
|---|---|---|
| `KEENETIC_IP` | IP роутера (через WG) | `192.168.1.1` |
| `KEENETIC_USER` | Логин в веб-интерфейс | `admin` |
| `KEENETIC_PASS` | Пароль | `mypassword` |
| `RECEIVER_URL` | URL центрального сервера | `http://1.2.3.4:8080` |
| `ENCRYPTION_KEY` | Пароль шифрования | `my-super-secret-key-2024` |
| `ROUTER_ID` | Уникальное имя этого роутера | `router-spb-01` |
| `POLL_INTERVAL` | Интервал опроса в секундах | `60` |

> **Важно:** `ENCRYPTION_KEY` должен быть **одинаковым** на агенте и на сервере.

### 6. Проверить работу вручную

```bash
source venv/bin/activate
python agent.py
```

Успешный вывод:
```
2024-01-15 12:00:00 [INFO] Agent starting | router=router-01 keenetic=192.168.1.1:80 ...
2024-01-15 12:00:01 [INFO] Sent to receiver: 4821 B raw → 6548 B encrypted
```

### 7. Установить как системный сервис

```bash
# Создать пользователя
sudo useradd -r -s /bin/false keenetic-agent

# Назначить права
sudo chown -R keenetic-agent:keenetic-agent /opt/keenetic-agent

# Установить сервис
sudo cp keenetic-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable keenetic-agent
sudo systemctl start keenetic-agent
```

### 8. Проверить статус сервиса

```bash
sudo systemctl status keenetic-agent
sudo journalctl -u keenetic-agent -f
```

---

## Что собирается

| Данные | Endpoint Keenetic |
|---|---|
| CPU, RAM, uptime, соединения | `/rci/show/system` |
| Все интерфейсы (rx/tx bytes) | `/rci/show/interface` |
| LTE сигнал, оператор, SNR | `/rci/show/interface/UsbLte0` |
| WireGuard rx/tx, handshake | `/rci/show/interface/Wireguard0` |
| Подключённые устройства | `/rci/show/ip/hotspot` |
| DHCP leases | `/rci/show/ip/dhcp/bindings` |
| ARP таблица | `/rci/show/ip/arp` |
| Версия ОС, модель | `/rci/show/version` |

---

## Трафик туннеля

Один цикл опроса (8 эндпоинтов) ≈ **15–30 KB**.  
При `POLL_INTERVAL=60` — около **1.5 MB/час** на роутер.  
На LTE не ощутимо.

---

## Несколько роутеров

Для каждого роутера — отдельный экземпляр агента с уникальным `ROUTER_ID`.  
`ENCRYPTION_KEY` одинаковый для всех агентов и сервера.

```
/opt/keenetic-agent-spb/    (ROUTER_ID=router-spb-01)
/opt/keenetic-agent-msk/    (ROUTER_ID=router-msk-02)
/opt/keenetic-agent-ekb/    (ROUTER_ID=router-ekb-03)
```

---

## Диагностика

**Агент не может подключиться к роутеру:**
```bash
curl -v http://192.168.1.1/auth   # проверить доступность через туннель
ping 192.168.1.1                  # проверить туннель
```

**Ошибка авторизации:**
- Проверить `KEENETIC_USER` и `KEENETIC_PASS` в `.env`
- Убедиться что аккаунт не заблокирован в интерфейсе Keenetic

**Данные не доходят до сервера:**
```bash
curl -X POST http://1.2.3.4:8080/health    # проверить доступность receiver
```

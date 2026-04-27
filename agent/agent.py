#!/usr/bin/env python3
"""
Keenetic Monitor Agent
Runs on every server that has WireGuard tunnel to a Keenetic router.
Polls Keenetic API, encrypts payload, sends to central receiver.
"""

import os
import sys
import time
import hashlib
import json
import logging
import base64
from typing import Optional, Dict, Any

import requests
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from dotenv import dotenv_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# Salt is fixed — same on agent and receiver so keys match
_KDF_SALT = b"keenetic-monitor-v1"


def make_fernet(passphrase: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=100_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    return Fernet(key)


def load_config() -> dict:
    cfg = dotenv_values(".env")
    required = [
        "KEENETIC_IP",
        "KEENETIC_USER",
        "KEENETIC_PASS",
        "RECEIVER_URL",
        "ENCRYPTION_KEY",
        "ROUTER_ID",
    ]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        log.error(f"Missing required config keys: {', '.join(missing)}")
        sys.exit(1)
    cfg.setdefault("KEENETIC_PORT", "80")
    cfg.setdefault("POLL_INTERVAL", "60")
    return cfg


class KeeneticClient:
    def __init__(self, ip: str, port: str, user: str, password: str):
        self.base = f"http://{ip}:{port}"
        self.user = user
        self.password = password
        self.session = requests.Session()
        self.session.timeout = 10
        self._authenticated = False

    def auth(self) -> bool:
        try:
            r = self.session.get(f"{self.base}/auth")
            if r.status_code == 200:
                self._authenticated = True
                return True
            if r.status_code != 401:
                log.error(f"Auth probe returned {r.status_code}")
                return False

            realm = r.headers.get("X-NDM-Realm", "")
            challenge = r.headers.get("X-NDM-Challenge", "")

            md5_pass = hashlib.md5(
                f"{self.user}:{realm}:{self.password}".encode()
            ).hexdigest()
            sha_pass = hashlib.sha256(
                f"{challenge}{md5_pass}".encode()
            ).hexdigest()

            r2 = self.session.post(
                f"{self.base}/auth",
                json={"login": self.user, "password": sha_pass},
                timeout=10,
            )
            self._authenticated = r2.status_code == 200
            if not self._authenticated:
                log.error(f"Auth rejected: {r2.status_code}")
            return self._authenticated

        except requests.RequestException as e:
            log.error(f"Auth network error: {e}")
            return False

    def get(self, endpoint: str) -> Optional[Any]:
        if not self._authenticated:
            if not self.auth():
                return None
        try:
            r = self.session.get(f"{self.base}{endpoint}", timeout=10)
            if r.status_code == 401:
                log.warning("Session expired, re-authenticating")
                self._authenticated = False
                if not self.auth():
                    return None
                r = self.session.get(f"{self.base}{endpoint}", timeout=10)
            if r.status_code == 200:
                return r.json()
            log.warning(f"GET {endpoint} → {r.status_code}")
            return None
        except requests.RequestException as e:
            log.warning(f"GET {endpoint} error: {e}")
            return None


ENDPOINTS = {
    "system":      "/rci/show/system",
    "interface":   "/rci/show/interface",
    "lte":         "/rci/show/interface/UsbLte0",
    "wireguard":   "/rci/show/interface/Wireguard0",
    "hotspot":     "/rci/show/ip/hotspot",
    "dhcp":        "/rci/show/ip/dhcp/bindings",
    "arp":         "/rci/show/ip/arp",
    "version":     "/rci/show/version",
}


def collect(client: KeeneticClient) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    for name, endpoint in ENDPOINTS.items():
        data = client.get(endpoint)
        if data is not None:
            metrics[name] = data
        else:
            log.warning(f"Skipped {name} (no data)")
    return metrics


def send(
    metrics: Dict,
    router_id: str,
    receiver_url: str,
    fernet: Fernet,
) -> bool:
    payload = {
        "router_id": router_id,
        "timestamp": int(time.time()),
        "metrics": metrics,
    }
    raw = json.dumps(payload, ensure_ascii=False).encode()
    encrypted = fernet.encrypt(raw)

    try:
        r = requests.post(
            f"{receiver_url.rstrip('/')}/ingest",
            data=encrypted,
            headers={"Content-Type": "application/octet-stream"},
            timeout=20,
        )
        if r.status_code == 200:
            log.info(
                f"Sent to receiver: {len(raw)} B raw → {len(encrypted)} B encrypted"
            )
            return True
        log.error(f"Receiver returned {r.status_code}: {r.text[:200]}")
        return False
    except requests.RequestException as e:
        log.error(f"Send failed: {e}")
        return False


def main():
    cfg = load_config()
    fernet = make_fernet(cfg["ENCRYPTION_KEY"])
    client = KeeneticClient(
        cfg["KEENETIC_IP"],
        cfg["KEENETIC_PORT"],
        cfg["KEENETIC_USER"],
        cfg["KEENETIC_PASS"],
    )
    interval = int(cfg["POLL_INTERVAL"])

    log.info(
        f"Agent starting | router={cfg['ROUTER_ID']} "
        f"keenetic={cfg['KEENETIC_IP']}:{cfg['KEENETIC_PORT']} "
        f"receiver={cfg['RECEIVER_URL']} interval={interval}s"
    )

    client.auth()

    while True:
        start = time.time()
        try:
            metrics = collect(client)
            if metrics:
                send(metrics, cfg["ROUTER_ID"], cfg["RECEIVER_URL"], fernet)
            else:
                log.warning("No metrics collected this cycle")
        except Exception as e:
            log.error(f"Unexpected error in poll cycle: {e}")

        elapsed = time.time() - start
        sleep_for = max(0, interval - elapsed)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()

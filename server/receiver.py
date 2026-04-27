#!/usr/bin/env python3
"""
Keenetic Monitor Receiver
Receives encrypted metric payloads from agents, decrypts, stores to InfluxDB.
"""

import sys
import json
import logging
import base64

from flask import Flask, request, jsonify
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from dotenv import dotenv_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("receiver.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

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
    required = ["ENCRYPTION_KEY", "INFLUXDB_TOKEN"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        log.error(f"Missing required config: {', '.join(missing)}")
        sys.exit(1)
    cfg.setdefault("INFLUXDB_URL", "http://influxdb:8086")
    cfg.setdefault("INFLUXDB_ORG", "keenetic")
    cfg.setdefault("INFLUXDB_BUCKET", "keenetic")
    cfg.setdefault("LISTEN_PORT", "8080")
    cfg.setdefault("LISTEN_HOST", "0.0.0.0")
    return cfg


cfg = load_config()
fernet = make_fernet(cfg["ENCRYPTION_KEY"])

influx_client = InfluxDBClient(
    url=cfg["INFLUXDB_URL"],
    token=cfg["INFLUXDB_TOKEN"],
    org=cfg["INFLUXDB_ORG"],
)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)
BUCKET = cfg["INFLUXDB_BUCKET"]
ORG = cfg["INFLUXDB_ORG"]

app = Flask(__name__)


# ── Writers ───────────────────────────────────────────────────────────────────

def ns(ts: int) -> int:
    return ts * 1_000_000_000


def write_system(router: str, ts: int, data: dict):
    if not isinstance(data, dict):
        return
    mem = data.get("memory", {}) or {}
    mem_total = mem.get("total", 0)
    mem_free = mem.get("free", 0)
    mem_used_pct = round((1 - mem_free / mem_total) * 100, 1) if mem_total else 0

    p = (
        Point("system")
        .tag("router", router)
        .field("uptime_sec", int(data.get("uptime", 0)))
        .field("cpu_load_pct", float(data.get("cpuload", 0)))
        .field("memory_total_kb", int(mem_total))
        .field("memory_free_kb", int(mem_free))
        .field("memory_used_pct", mem_used_pct)
        .field("conn_free", int(data.get("connfree", 0)))
        .field("conn_total", int(data.get("conntotal", 0)))
        .time(ns(ts))
    )
    write_api.write(bucket=BUCKET, org=ORG, record=p)


def write_interfaces(router: str, ts: int, data):
    if not data:
        return
    ifaces = data if isinstance(data, list) else [data]
    points = []
    for iface in ifaces:
        if not isinstance(iface, dict):
            continue
        name = iface.get("id") or iface.get("interface-name") or iface.get("name", "unknown")
        p = (
            Point("interface")
            .tag("router", router)
            .tag("interface", name)
            .tag("type", iface.get("type", "unknown"))
            .field("rx_bytes", int(iface.get("rxbytes", 0)))
            .field("tx_bytes", int(iface.get("txbytes", 0)))
            .field("rx_packets", int(iface.get("rxpackets", 0)))
            .field("tx_packets", int(iface.get("txpackets", 0)))
            .field("connected", 1 if iface.get("connected") else 0)
            .time(ns(ts))
        )
        points.append(p)
    if points:
        write_api.write(bucket=BUCKET, org=ORG, record=points)


def write_lte(router: str, ts: int, data: dict):
    if not isinstance(data, dict):
        return
    p = (
        Point("lte")
        .tag("router", router)
        .tag("operator", str(data.get("operator", "unknown")))
        .tag("network_type", str(data.get("network-type", data.get("type", "unknown"))))
        .field("rssi", float(data.get("rssi", 0)))
        .field("rsrp", float(data.get("rsrp", 0)))
        .field("rsrq", float(data.get("rsrq", 0)))
        .field("sinr", float(data.get("sinr", 0)))
        .field("signal_pct", float(data.get("signal", 0)))
        .field("connected", 1 if data.get("connected") else 0)
        .field("rx_bytes", int(data.get("rxbytes", 0)))
        .field("tx_bytes", int(data.get("txbytes", 0)))
        .time(ns(ts))
    )
    write_api.write(bucket=BUCKET, org=ORG, record=p)


def write_wireguard(router: str, ts: int, data: dict):
    if not isinstance(data, dict):
        return
    p = (
        Point("wireguard")
        .tag("router", router)
        .field("rx_bytes", int(data.get("rxbytes", 0)))
        .field("tx_bytes", int(data.get("txbytes", 0)))
        .field("connected", 1 if data.get("connected") else 0)
        .time(ns(ts))
    )
    write_api.write(bucket=BUCKET, org=ORG, record=p)


def write_hotspot(router: str, ts: int, data):
    if not data:
        return
    hosts = data if isinstance(data, list) else [data]
    active_hosts = [h for h in hosts if isinstance(h, dict) and h.get("active")]

    summary = (
        Point("hotspot_summary")
        .tag("router", router)
        .field("total_devices", len(hosts))
        .field("active_devices", len(active_hosts))
        .time(ns(ts))
    )
    write_api.write(bucket=BUCKET, org=ORG, record=summary)

    host_points = []
    for h in active_hosts:
        mac = h.get("mac", "unknown")
        name = h.get("name") or h.get("hostname") or mac
        hp = (
            Point("hotspot_host")
            .tag("router", router)
            .tag("mac", mac)
            .tag("hostname", name)
            .field("rx_bytes", int(h.get("rxbytes", 0)))
            .field("tx_bytes", int(h.get("txbytes", 0)))
            .field("active", 1)
            .time(ns(ts))
        )
        host_points.append(hp)
    if host_points:
        write_api.write(bucket=BUCKET, org=ORG, record=host_points)


def write_version(router: str, ts: int, data: dict):
    if not isinstance(data, dict):
        return
    p = (
        Point("router_info")
        .tag("router", router)
        .tag("model", str(data.get("model", "unknown")))
        .tag("hw_version", str(data.get("hw-version", "")))
        .tag("os_version", str(data.get("version", "")))
        .field("uptime_sec", int(data.get("uptime", 0)))
        .field("info", 1)
        .time(ns(ts))
    )
    write_api.write(bucket=BUCKET, org=ORG, record=p)


WRITERS = {
    "system":    write_system,
    "interface": write_interfaces,
    "lte":       write_lte,
    "wireguard": write_wireguard,
    "hotspot":   write_hotspot,
    "version":   write_version,
}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/ingest", methods=["POST"])
def ingest():
    try:
        encrypted = request.data
        if not encrypted:
            return jsonify({"error": "empty body"}), 400

        try:
            plaintext = fernet.decrypt(encrypted)
        except InvalidToken:
            log.warning("Received payload with invalid encryption key")
            return jsonify({"error": "invalid token"}), 403

        payload = json.loads(plaintext)
        router_id = payload.get("router_id", "unknown")
        ts = int(payload.get("timestamp", 0))
        metrics = payload.get("metrics", {})

        for key, writer in WRITERS.items():
            if key in metrics:
                try:
                    writer(router_id, ts, metrics[key])
                except Exception as e:
                    log.error(f"Writer '{key}' error for {router_id}: {e}")

        log.info(
            f"Stored: router={router_id} keys={list(metrics.keys())} "
            f"payload={len(plaintext)}B"
        )
        return jsonify({"ok": True, "router": router_id})

    except json.JSONDecodeError as e:
        log.error(f"JSON decode error: {e}")
        return jsonify({"error": "invalid json"}), 400
    except Exception as e:
        log.error(f"Ingest error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    try:
        influx_client.ping()
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({"status": "ok", "influxdb": db_ok})


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "keenetic-monitor-receiver",
        "endpoints": ["/ingest", "/health"],
    })


if __name__ == "__main__":
    port = int(cfg["LISTEN_PORT"])
    host = cfg["LISTEN_HOST"]
    log.info(f"Receiver starting on {host}:{port}")
    app.run(host=host, port=port)

#!/usr/bin/env python3
"""
Ping Monitor
Checks reachability of remote stations (radio modems, etc.)
that are NOT direct Keenetic clients but are routable from this server.
Writes results to InfluxDB as 'device_ping' measurement.

Configure TARGETS in .env:
  PING_TARGETS=station-40:10.50.1.40,station-41:10.50.1.41,station-50:10.50.1.50,station-51:10.50.1.51
  PING_INTERVAL=30
"""

import sys
import time
import subprocess
import logging
import re

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from dotenv import dotenv_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

_RE_RTT = re.compile(r"rtt\s+\S+\s*=\s*[\d.]+/([\d.]+)/")


def load_config() -> dict:
    cfg = dotenv_values(".env")
    required = ["INFLUXDB_TOKEN", "PING_TARGETS"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        log.error(f"Missing config: {', '.join(missing)}")
        sys.exit(1)
    cfg.setdefault("INFLUXDB_URL", "http://influxdb:8086")
    cfg.setdefault("INFLUXDB_ORG", "keenetic")
    cfg.setdefault("INFLUXDB_BUCKET", "keenetic")
    cfg.setdefault("PING_INTERVAL", "30")
    cfg.setdefault("PING_GROUP", "stations")
    return cfg


def parse_targets(raw: str) -> list[dict]:
    targets = []
    for item in raw.split(","):
        item = item.strip()
        if ":" in item:
            parts = item.split(":", 1)
            targets.append({"name": parts[0].strip(), "ip": parts[1].strip()})
        elif item:
            targets.append({"name": item, "ip": item})
    return targets


def ping_once(ip: str) -> tuple[bool, float]:
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            m = _RE_RTT.search(result.stdout)
            rtt = float(m.group(1)) if m else 0.0
            return True, rtt
        return False, 0.0
    except Exception:
        return False, 0.0


def main():
    cfg = load_config()
    targets = parse_targets(cfg["PING_TARGETS"])
    interval = int(cfg["PING_INTERVAL"])
    group = cfg["PING_GROUP"]

    client = InfluxDBClient(
        url=cfg["INFLUXDB_URL"],
        token=cfg["INFLUXDB_TOKEN"],
        org=cfg["INFLUXDB_ORG"],
    )
    write_api = client.write_api(write_options=SYNCHRONOUS)
    bucket = cfg["INFLUXDB_BUCKET"]
    org = cfg["INFLUXDB_ORG"]

    log.info(f"Ping monitor starting | targets={[t['name'] for t in targets]} interval={interval}s")

    while True:
        ts = int(time.time()) * 1_000_000_000
        points = []
        for t in targets:
            up, rtt_ms = ping_once(t["ip"])
            p = (
                Point("device_ping")
                .tag("group", group)
                .tag("name", t["name"])
                .tag("ip", t["ip"])
                .field("up", 1 if up else 0)
                .field("rtt_ms", rtt_ms)
                .time(ts)
            )
            points.append(p)
            status = f"up rtt={rtt_ms:.1f}ms" if up else "DOWN"
            log.info(f"  {t['name']} ({t['ip']}) → {status}")

        write_api.write(bucket=bucket, org=org, record=points)
        time.sleep(interval)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""navimow_probe — raw Navimow cloud data logger.

Connects to all REST and WSS-MQTT endpoints and prints every response/message
in full so field shapes can be discovered during mowing, pausing, docking, etc.

Usage (on LoxBerry):
  python3 /opt/loxberry/bin/plugins/navimow/navimow_probe.py

Optional flags:
  --configdir /opt/loxberry/config/plugins/navimow   (default)
  --logfile   /tmp/navimow_probe.log                 (default, also prints to stdout)

Stop with Ctrl+C.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import threading
import uuid
from datetime import datetime
from urllib.parse import urlparse

import paho.mqtt.client as mqtt
import requests

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_CONFIG_DIR = "/opt/loxberry/config/plugins/navimow"
CONFIG_FILE        = "pluginconfig.json"
API_BASE           = "https://navimow-fra.ninebot.com"
TOKEN_URL          = f"{API_BASE}/openapi/oauth/getAccessToken"
CLIENT_ID          = "homeassistant"
CLIENT_SECRET      = "57056e15-722e-42be-bbaa-b0cbfb208a52"
HTTP_TIMEOUT       = 30
MQTT_KEEPALIVE     = 2400

# ── Logging ───────────────────────────────────────────────────────────────────

_logfile_path: str | None = None


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg: str) -> None:
    line = f"{_ts()}  {msg}"
    print(line, flush=True)
    if _logfile_path:
        try:
            with open(_logfile_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def sep(label: str = "") -> None:
    bar = "─" * 60
    log(f"{bar} {label}" if label else bar)


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(config_dir: str) -> dict:
    path = os.path.join(config_dir, CONFIG_FILE)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ── REST helpers ──────────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "requestId": str(uuid.uuid4()),
    }


def rest_get(token: str, path: str) -> dict:
    resp = requests.get(API_BASE + path, headers=_headers(token), timeout=HTTP_TIMEOUT)
    return resp.json()


def rest_post(token: str, path: str, body: dict) -> dict:
    resp = requests.post(API_BASE + path, headers=_headers(token),
                         json=body, timeout=HTTP_TIMEOUT)
    return resp.json()


def refresh_access_token(refresh_tok: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_tok,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=HTTP_TIMEOUT,
    )
    return resp.json()


# ── Token manager (thread-safe mutable ref) ───────────────────────────────────

class TokenRef:
    def __init__(self, access_token: str, refresh_token: str, expires_at: float):
        self._lock          = threading.Lock()
        self.access_token   = access_token
        self.refresh_token  = refresh_token
        self.expires_at     = expires_at

    def needs_refresh(self) -> bool:
        with self._lock:
            return (self.expires_at - time.time()) < 300

    def update(self, access_token: str, expires_in: int, new_refresh: str | None) -> None:
        with self._lock:
            self.access_token = access_token
            self.expires_at   = time.time() + expires_in
            if new_refresh:
                self.refresh_token = new_refresh

    def get_access(self) -> str:
        with self._lock:
            return self.access_token


# ── paho MQTT client factory ──────────────────────────────────────────────────

def _make_mqtt_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            client_id=client_id,
            transport="websockets",
        )
    except (TypeError, AttributeError):
        return mqtt.Client(client_id=client_id, transport="websockets")


# ── Cloud MQTT connection ─────────────────────────────────────────────────────

def connect_cloud_mqtt(token_ref: TokenRef, device_ids: list[str],
                       mqtt_info: dict) -> mqtt.Client | None:
    raw_host = mqtt_info.get("mqttHost") or "wss://mqtt-fra.navimow.com"
    username = mqtt_info.get("userName")
    password = mqtt_info.get("pwdInfo")
    ws_path  = mqtt_info.get("mqttUrl") or "/mqtt"

    # mqttHost may include scheme (wss://host) — extract just the hostname
    parsed_host = urlparse(raw_host)
    host = parsed_host.hostname or raw_host
    port = parsed_host.port or 443

    client_id = "probe_" + uuid.uuid4().hex[:10]
    client    = _make_mqtt_client(client_id)

    if username and password:
        client.username_pw_set(username, password)

    def _ws_headers(headers):
        h = dict(headers)
        h["Authorization"] = "Bearer " + token_ref.get_access()
        h.pop("Origin", None)
        return h

    client.ws_set_options(path=ws_path, headers=_ws_headers)
    client.tls_set()

    def on_connect(cli, userdata, flags, rc):
        if rc != 0:
            log(f"[MQTT] connect failed rc={rc}")
            return
        log(f"[MQTT] connected to {host}:{port}")
        for did in device_ids:
            base = f"/downlink/vehicle/{did}"
            for ch in ("state", "event", "attributes", "location"):
                cli.subscribe(f"{base}/realtimeDate/{ch}")
            cli.subscribe(f"{base}/#")
        log(f"[MQTT] subscribed to {len(device_ids)} device(s) — all channels")

    def on_disconnect(cli, userdata, rc):
        log(f"[MQTT] disconnected rc={rc}")

    def on_message(cli, userdata, msg):
        parts = [p for p in msg.topic.split("/") if p]
        device_id = parts[2] if len(parts) >= 3 else "?"
        channel   = parts[-1] if parts else "?"
        try:
            data   = json.loads(msg.payload.decode("utf-8", "replace"))
            pretty = json.dumps(data, ensure_ascii=False, indent=2)
        except (ValueError, AttributeError):
            pretty = repr(msg.payload[:500])
        sep(f"MQTT  device={device_id}  channel={channel}")
        log(pretty)

    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message
    client.reconnect_delay_set(min_delay=5, max_delay=60)

    log(f"[MQTT] connecting to {host}:{port}{ws_path} ...")
    try:
        client.connect(host, port, keepalive=MQTT_KEEPALIVE)
        client.loop_start()
        return client
    except Exception as e:
        log(f"[MQTT] connect error: {e}")
        return None


# ── Token refresh loop ────────────────────────────────────────────────────────

def token_refresh_loop(token_ref: TokenRef, mqtt_client: mqtt.Client | None,
                       stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        if not token_ref.needs_refresh():
            continue
        log("[TOKEN] refreshing ...")
        try:
            raw  = refresh_access_token(token_ref.refresh_token)
            data = raw.get("data", raw) if isinstance(raw.get("data"), dict) else raw
            new_access  = data.get("access_token", "")
            new_refresh = data.get("refresh_token") or None
            expires_in  = int(data.get("expires_in", 3600))
            if not new_access:
                log(f"[TOKEN] refresh failed: {raw}")
                continue
            token_ref.update(new_access, expires_in, new_refresh)
            log(f"[TOKEN] refreshed, valid for {expires_in}s")
        except Exception as e:
            log(f"[TOKEN] refresh error: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Navimow cloud data probe")
    parser.add_argument("--configdir", default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--logfile",   default="/tmp/navimow_probe.log")
    args = parser.parse_args()

    global _logfile_path
    _logfile_path = args.logfile

    # Truncate logfile at start so each run is clean
    try:
        open(_logfile_path, "w").close()
    except OSError:
        pass

    log("=" * 70)
    log("navimow_probe started")
    log(f"logfile: {_logfile_path}")
    log("=" * 70)

    # Load config
    try:
        cfg = load_config(args.configdir)
    except (OSError, json.JSONDecodeError) as e:
        log(f"[ERROR] cannot load config from {args.configdir}: {e}")
        return 1

    refresh_tok = cfg.get("refresh_token", "")
    if not refresh_tok:
        log("[ERROR] no refresh_token in config — run OAuth authentication first")
        return 1

    # Get access token
    log("[TOKEN] refreshing at startup ...")
    try:
        raw  = refresh_access_token(refresh_tok)
        data = raw.get("data", raw) if isinstance(raw.get("data"), dict) else raw
        access_tok  = data.get("access_token", "")
        new_refresh = data.get("refresh_token") or refresh_tok
        expires_in  = int(data.get("expires_in", 3600))
        if not access_tok:
            log(f"[TOKEN] failed: {raw}")
            return 1
        log(f"[TOKEN] ok, valid for {expires_in}s")
    except Exception as e:
        log(f"[TOKEN] error: {e}")
        return 1

    token_ref = TokenRef(
        access_token  = access_tok,
        refresh_token = new_refresh,
        expires_at    = time.time() + expires_in,
    )

    # ── authList ──────────────────────────────────────────────────────────────
    sep("REST  authList")
    try:
        result = rest_get(access_tok, "/openapi/smarthome/authList")
        log(json.dumps(result, ensure_ascii=False, indent=2))
        devices    = (((result.get("data") or {}).get("payload") or {}).get("devices")) or []
        device_ids = [d["id"] for d in devices if isinstance(d, dict) and d.get("id")]
        log(f"device IDs: {device_ids}")
    except Exception as e:
        log(f"[ERROR] authList: {e}")
        return 1

    if not device_ids:
        log("[ERROR] no devices found")
        return 1

    # ── getVehicleStatus ──────────────────────────────────────────────────────
    sep("REST  getVehicleStatus")
    try:
        result = rest_post(access_tok, "/openapi/smarthome/getVehicleStatus",
                           {"devices": [{"id": did} for did in device_ids]})
        log(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        log(f"[ERROR] getVehicleStatus: {e}")

    # ── mqttUserInfo ──────────────────────────────────────────────────────────
    sep("REST  mqttUserInfo")
    try:
        mqtt_info = rest_get(access_tok, "/openapi/mqtt/userInfo/get/v2")
        log(json.dumps(mqtt_info, ensure_ascii=False, indent=2))
        mqtt_data = mqtt_info.get("data") or {}
    except Exception as e:
        log(f"[ERROR] mqttUserInfo: {e}")
        return 1

    # ── Cloud MQTT ────────────────────────────────────────────────────────────
    sep("MQTT  connecting")
    mqtt_client = connect_cloud_mqtt(token_ref, device_ids, mqtt_data)
    if not mqtt_client:
        log("[ERROR] MQTT connection failed")
        return 1

    stop_event = threading.Event()
    refresh_thread = threading.Thread(
        target=token_refresh_loop,
        args=(token_ref, mqtt_client, stop_event),
        daemon=True,
    )
    refresh_thread.start()

    log("Listening — Ctrl+C to stop. Start/pause/dock the mower now.")
    sep()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    log("Stopping ...")
    stop_event.set()
    try:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
    except Exception:
        pass
    log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

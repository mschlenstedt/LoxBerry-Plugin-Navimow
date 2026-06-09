#!/usr/bin/env python3
"""Navimow LoxBerry Gateway — bridges Navimow cloud to LoxBerry MQTT broker."""

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path

import aiohttp
from mower_sdk.api import MowerAPI
import aiomqtt
from mower_sdk.sdk import NavimowSDK
from mower_sdk.models import DeviceStateMessage

# ── CLI args ──────────────────────────────────────────────────────────────────
_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument("--logfile",   default="")
_ap.add_argument("--logdbkey",  default="")
_ap.add_argument("--configdir", default="")
_ap.add_argument("--lbsconfig", default="/opt/loxberry/config/system")
_ap.add_argument("--loglevel",  type=int, default=6)
_args, _ = _ap.parse_known_args()

# ── Paths ─────────────────────────────────────────────────────────────────────
LBHOMEDIR   = os.environ.get("LBHOMEDIR", "/opt/loxberry")
LBSCONFIG   = Path(_args.lbsconfig)
CONFIGDIR   = Path(_args.configdir) if _args.configdir else Path(LBHOMEDIR) / "config/plugins/navimow"
GENERAL_JSON = LBSCONFIG / "general.json"
PLUGIN_CFG  = CONFIGDIR / "pluginconfig.json"
PID_FILE    = Path("/dev/shm/navimow_gateway.pid")

# ── Logging ───────────────────────────────────────────────────────────────────
_loglevel = _args.loglevel
_logfile  = _args.logfile

_logger = logging.getLogger("navimow_gateway")
_logger.propagate = False
_logger.setLevel(logging.DEBUG)

_handler = (
    logging.FileHandler(_logfile, mode="a", encoding="utf-8")
    if _logfile
    else logging.StreamHandler(sys.stdout)
)
_handler.setFormatter(logging.Formatter(
    "%(asctime)s.%(msecs)03d <%(levelname)s> %(message)s",
    datefmt="%H:%M:%S"
))
_logger.addHandler(_handler)


def _log(level: int, levelname: str, msg: str) -> None:
    if level <= _loglevel:
        record = logging.LogRecord(
            name=_logger.name, level=logging.DEBUG,
            pathname="", lineno=0, msg=msg, args=(), exc_info=None,
        )
        record.levelname = levelname
        _handler.emit(record)


def LOGSTART(msg: str) -> None: _log(5, "OK",    msg)
def LOGERR(msg: str)   -> None: _log(3, "ERR",   msg)
def LOGWARN(msg: str)  -> None: _log(4, "WARN",  msg)
def LOGOK(msg: str)    -> None: _log(5, "OK",    msg)
def LOGINF(msg: str)   -> None: _log(6, "INFO",  msg)
def LOGDEB(msg: str)   -> None: _log(7, "DEBUG", msg)


def _logend() -> None:
    dbkey = _args.logdbkey
    if not dbkey:
        return
    if not re.match(r'^[\w]+$', dbkey):
        LOGWARN(f"_logend: invalid dbkey value, skipping LOGEND call")
        return
    os.system(
        f'perl -e \'use LoxBerry::Log; '
        f'my $l = LoxBerry::Log->new(dbkey => "{dbkey}", append => 1); '
        f'LOGEND "Gateway stopped."; exit;\''
    )


# ── Config ────────────────────────────────────────────────────────────────────
def _load_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        LOGERR(f"Cannot read {path}: {e}")
        return {}


def _save_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        LOGERR(f"Cannot write {path}: {e}")


def load_general_config() -> dict:
    return _load_json(GENERAL_JSON)


def load_plugin_config() -> dict:
    cfg = _load_json(PLUGIN_CFG)
    cfg.setdefault("base_topic", "navimow")
    cfg.setdefault("access_token", "")
    cfg.setdefault("refresh_token", "")
    cfg.setdefault("expires_at", 0)
    cfg.setdefault("token_type", "Bearer")
    cfg.setdefault("devices", [])
    return cfg


def save_plugin_config(cfg: dict) -> None:
    _save_json_atomic(PLUGIN_CFG, cfg)


def get_mqtt_broker_config(general: dict) -> dict:
    """Extract LoxBerry MQTT broker settings from general.json."""
    mqtt = general.get("Mqtt", {})
    return {
        "host":     mqtt.get("Brokerhost", "localhost"),
        "port":     int(mqtt.get("Brokerport", 1883)),
        "username": mqtt.get("Username", "") or None,
        "password": mqtt.get("Password", "") or None,
    }


# ── PID management ────────────────────────────────────────────────────────────
def write_pid() -> None:
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as e:
        LOGERR(f"Cannot write PID file: {e}")


def remove_pid() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception as e:
        LOGERR(f"Cannot remove PID file: {e}")


# ── Shutdown ──────────────────────────────────────────────────────────────────
_shutdown_event: asyncio.Event = asyncio.Event()


def _handle_sigterm(*_) -> None:
    LOGINF("SIGTERM received — shutting down")
    _shutdown_event.set()


# ── REST constants ────────────────────────────────────────────────────────────
API_BASE  = "https://navimow-fra.ninebot.com"
TOKEN_URL = "https://navimow-fra.ninebot.com/openapi/oauth/getAccessToken"

CLIENT_ID     = "homeassistant"
CLIENT_SECRET = "57056e15-722e-42be-bbaa-b0cbfb208a52"


# ── Task 6: REST Initialization ───────────────────────────────────────────────
async def rest_init(
    plugin_cfg: dict,
    session: aiohttp.ClientSession,
) -> tuple:
    """
    Fetch device list and Navimow MQTT credentials via REST.
    Returns (api, mqtt_info) where mqtt_info has mqttHost/mqttUrl/userName/pwdInfo.
    Updates plugin_cfg['devices'] in place and persists.
    """
    token = plugin_cfg.get("access_token", "")
    if not token:
        LOGWARN("No access token — skipping REST init")
        return None, {}

    api = MowerAPI(session=session, token=token, base_url=API_BASE)

    try:
        devices = await api.async_get_devices()
        LOGOK(f"Found {len(devices)} device(s) on account")
        plugin_cfg["devices"] = [
            {"device_id": d.id, "name": d.name}
            for d in devices
        ]
        save_plugin_config(plugin_cfg)
    except Exception as e:
        LOGERR(f"REST get_devices failed: {e}")

    try:
        mqtt_info = await api.async_get_mqtt_user_info()
        LOGINF(f"Navimow MQTT host: {mqtt_info.get('mqttHost', '?')}")
    except Exception as e:
        LOGERR(f"REST get_mqtt_user_info failed: {e}")
        mqtt_info = {}

    return api, mqtt_info


# ── Task 7: Navimow MQTT → LoxBerry MQTT ─────────────────────────────────────
_state_queue: asyncio.Queue = asyncio.Queue()


def _on_navimow_state(msg: "DeviceStateMessage") -> None:
    """Synchronous callback from NavimowSDK — bridge to async queue."""
    try:
        _state_queue.put_nowait(msg)
    except asyncio.QueueFull:
        pass


async def task_navimow_to_mqtt(
    sdk: "NavimowSDK",
    base_topic: str,
    broker: dict,
    shutdown: asyncio.Event,
) -> None:
    """Publish Navimow state updates to LoxBerry MQTT broker."""
    mqtt_kwargs: dict = {
        "hostname": broker["host"],
        "port":     broker["port"],
    }
    if broker.get("username"):
        mqtt_kwargs["username"] = broker["username"]
    if broker.get("password"):
        mqtt_kwargs["password"] = broker["password"]

    while not shutdown.is_set():
        try:
            async with aiomqtt.Client(**mqtt_kwargs) as lbmqtt:
                LOGOK(f"Connected to LoxBerry MQTT {broker['host']}:{broker['port']}")
                while not shutdown.is_set():
                    try:
                        msg = await asyncio.wait_for(
                            _state_queue.get(), timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        continue

                    device_id = msg.device_id
                    state_payload = json.dumps({
                        "state":   msg.state,
                        "battery": msg.battery,
                        "error":   msg.error,
                    })
                    await lbmqtt.publish(
                        f"{base_topic}/{device_id}/state", state_payload, retain=True
                    )
                    if msg.battery is not None:
                        await lbmqtt.publish(
                            f"{base_topic}/{device_id}/battery",
                            str(msg.battery), retain=True
                        )
                    LOGDEB(f"Published state for {device_id}: {msg.state}")

        except Exception as e:
            if not shutdown.is_set():
                LOGERR(f"LoxBerry MQTT error: {e} — reconnecting in 10s")
                await asyncio.sleep(10)


# ── Task 8: LoxBerry MQTT → Navimow Commands ─────────────────────────────────
async def task_mqtt_to_navimow(
    sdk: "NavimowSDK",
    base_topic: str,
    broker: dict,
    shutdown: asyncio.Event,
) -> None:
    """Subscribe to LoxBerry MQTT set-topics and forward commands to Navimow."""
    mqtt_kwargs: dict = {
        "hostname": broker["host"],
        "port":     broker["port"],
    }
    if broker.get("username"):
        mqtt_kwargs["username"] = broker["username"]
    if broker.get("password"):
        mqtt_kwargs["password"] = broker["password"]

    while not shutdown.is_set():
        try:
            async with aiomqtt.Client(**mqtt_kwargs) as lbmqtt:
                await lbmqtt.subscribe(f"{base_topic}/+/set")
                await lbmqtt.subscribe(f"{base_topic}/+/set/blade_height")
                LOGINF(f"Subscribed to {base_topic}/+/set[/blade_height]")

                async with lbmqtt.messages() as messages:
                    async for message in messages:
                        if shutdown.is_set():
                            break
                        topic_parts = str(message.topic).split("/")
                        if len(topic_parts) < 3:
                            continue
                        is_blade = topic_parts[-1] == "blade_height"
                        device_id = topic_parts[-3] if is_blade else topic_parts[-2]
                        payload = message.payload.decode("utf-8", errors="replace").strip()

                        if is_blade:
                            try:
                                height = int(payload)
                                if 1 <= height <= 7:
                                    sdk.set_blade_height(device_id, height)
                                    LOGOK(f"set_blade_height({device_id}, {height})")
                                else:
                                    LOGWARN(f"blade_height out of range: {payload}")
                            except ValueError:
                                LOGWARN(f"Invalid blade_height payload: {payload}")
                        else:
                            cmd = payload.lower()
                            if cmd == "start":
                                sdk.start_mowing(device_id)
                                LOGOK(f"start_mowing({device_id})")
                            elif cmd == "pause":
                                sdk.pause(device_id)
                                LOGOK(f"pause({device_id})")
                            elif cmd in ("dock", "return", "home"):
                                sdk.return_to_base(device_id)
                                LOGOK(f"return_to_base({device_id})")
                            else:
                                LOGWARN(f"Unknown command: {payload}")

        except Exception as e:
            if not shutdown.is_set():
                LOGERR(f"Command MQTT error: {e} — reconnecting in 10s")
                await asyncio.sleep(10)


# ── Task 9: Token Refresh Watchdog ────────────────────────────────────────────
async def task_token_refresh(
    plugin_cfg: dict,
    session: aiohttp.ClientSession,
    sdk: "NavimowSDK",
    api: "MowerAPI",
    shutdown: asyncio.Event,
) -> None:
    """Refresh Navimow OAuth token 5 minutes before expiry."""
    while not shutdown.is_set():
        await asyncio.sleep(60)
        if shutdown.is_set():
            break

        expires_at = plugin_cfg.get("expires_at", 0)
        time_left  = expires_at - time.time()

        if time_left > 300:
            LOGDEB(f"Token valid for {int(time_left)}s")
            continue

        LOGINF("Token expiring soon — refreshing")
        refresh_token = plugin_cfg.get("refresh_token", "")
        if not refresh_token:
            LOGERR("No refresh_token available — cannot refresh")
            continue

        try:
            async with session.post(
                TOKEN_URL,
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id":     CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    LOGERR(f"Token refresh HTTP {resp.status}: {body[:200]}")
                    continue
                raw  = await resp.json(content_type=None)

            # API may wrap tokens inside a 'data' key
            data        = raw.get("data", raw) if isinstance(raw.get("data"), dict) else raw
            new_token   = data.get("access_token", "")
            new_refresh = data.get("refresh_token", refresh_token)
            expires_in  = int(data.get("expires_in", 3600))

            if not new_token:
                LOGERR("Token refresh: empty access_token in response")
                continue

            plugin_cfg["access_token"]  = new_token
            plugin_cfg["refresh_token"] = new_refresh
            plugin_cfg["expires_at"]    = int(time.time()) + expires_in
            save_plugin_config(plugin_cfg)

            if sdk:
                sdk.update_mqtt_credentials(
                    auth_headers={"Authorization": f"Bearer {new_token}"}
                )
            if api:
                api.set_token(new_token)

            LOGOK(f"Token refreshed — valid for {expires_in}s")

        except Exception as e:
            LOGERR(f"Token refresh error: {e}")


# ── Task 10: REST Fallback ────────────────────────────────────────────────────
_last_mqtt_update: float = 0.0


def _on_navimow_state_tracked(msg: "DeviceStateMessage") -> None:
    """Like _on_navimow_state but also records last update time."""
    global _last_mqtt_update
    _last_mqtt_update = time.time()
    _on_navimow_state(msg)


async def task_rest_fallback(
    api: "MowerAPI",
    plugin_cfg: dict,
    base_topic: str,
    broker: dict,
    shutdown: asyncio.Event,
) -> None:
    """Poll Navimow REST every 60s if no MQTT update received in 90s."""
    if api is None:
        LOGINF("REST fallback disabled — no API client")
        return

    mqtt_kwargs: dict = {
        "hostname": broker["host"],
        "port":     broker["port"],
    }
    if broker.get("username"):
        mqtt_kwargs["username"] = broker["username"]
    if broker.get("password"):
        mqtt_kwargs["password"] = broker["password"]

    while not shutdown.is_set():
        await asyncio.sleep(60)
        if shutdown.is_set():
            break

        if time.time() - _last_mqtt_update < 90:
            LOGDEB("REST fallback: recent MQTT data, skipping")
            continue

        LOGINF("REST fallback: polling device status")
        device_ids = [d["device_id"] for d in plugin_cfg.get("devices", [])]
        if not device_ids:
            continue

        try:
            statuses = await api.async_get_device_statuses(device_ids)
        except Exception as e:
            LOGERR(f"REST fallback error: {e}")
            continue

        try:
            async with aiomqtt.Client(**mqtt_kwargs) as lbmqtt:
                for device_id, status in statuses.items():
                    payload = json.dumps({
                        "state":   status.status.value,
                        "battery": status.battery,
                        "error":   status.error_code.value,
                    })
                    await lbmqtt.publish(
                        f"{base_topic}/{device_id}/state", payload, retain=True
                    )
                    await lbmqtt.publish(
                        f"{base_topic}/{device_id}/battery",
                        str(status.battery), retain=True
                    )
                    LOGDEB(f"REST fallback published {device_id}: {status.status.value}")
        except Exception as e:
            LOGERR(f"REST fallback MQTT publish error: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    LOGSTART("Navimow Gateway starting")
    write_pid()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
        loop.add_signal_handler(signal.SIGINT,  _handle_sigterm)
    except NotImplementedError:
        # Windows does not support add_signal_handler; signal handling is Linux-only
        pass

    general = load_general_config()
    plugin_cfg = load_plugin_config()
    broker = get_mqtt_broker_config(general)

    LOGINF(f"LoxBerry MQTT broker: {broker['host']}:{broker['port']}")
    LOGINF(f"Base topic: {plugin_cfg['base_topic']}")
    LOGINF(f"Devices cached: {len(plugin_cfg['devices'])}")

    if not plugin_cfg["access_token"]:
        LOGWARN("No access token configured — gateway will wait for authentication")

    async with aiohttp.ClientSession() as session:
        api, mqtt_info = await rest_init(plugin_cfg, session)

        navimow_sdk = None
        if mqtt_info and plugin_cfg.get("access_token"):
            class _DeviceRecord:
                def __init__(self, did, dname):
                    self.id = did
                    self.name = dname
                    self.product_key = None
                    self.device_name = dname
                    self.iot_id = did

            records = [
                _DeviceRecord(d["device_id"], d["name"])
                for d in plugin_cfg.get("devices", [])
            ]

            navimow_sdk = NavimowSDK(
                broker=mqtt_info.get("mqttHost", ""),
                port=443,
                username=mqtt_info.get("userName"),
                password=mqtt_info.get("pwdInfo"),
                ws_path=mqtt_info.get("mqttUrl"),
                auth_headers={"Authorization": f"Bearer {plugin_cfg['access_token']}"},
                records=records,
            )
            navimow_sdk.on_state(_on_navimow_state_tracked)
            navimow_sdk.connect()
            LOGINF("NavimowSDK connected to cloud MQTT")
        else:
            LOGWARN("NavimowSDK not started — missing token or MQTT info")

        base_topic = plugin_cfg["base_topic"]
        tasks = []

        if navimow_sdk:
            tasks.append(asyncio.create_task(
                task_navimow_to_mqtt(navimow_sdk, base_topic, broker, _shutdown_event)
            ))

        if navimow_sdk:
            tasks.append(asyncio.create_task(
                task_mqtt_to_navimow(navimow_sdk, base_topic, broker, _shutdown_event)
            ))

        tasks.append(asyncio.create_task(
            task_token_refresh(plugin_cfg, session, navimow_sdk, api, _shutdown_event)
        ))

        tasks.append(asyncio.create_task(
            task_rest_fallback(api, plugin_cfg, base_topic, broker, _shutdown_event)
        ))

        await _shutdown_event.wait()

        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if navimow_sdk:
            navimow_sdk.disconnect()

    LOGINF("Gateway stopped")
    remove_pid()
    _logend()


if __name__ == "__main__":
    asyncio.run(main())

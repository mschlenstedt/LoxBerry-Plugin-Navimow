#!/usr/bin/env python3
"""Navimow LoxBerry Gateway — bridges Navimow cloud to LoxBerry MQTT broker."""

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import ssl
import sys
import time
from pathlib import Path

import aiohttp
from mower_sdk.api import MowerAPI
import aiomqtt
from mower_sdk.sdk import NavimowSDK
from mower_sdk.models import DeviceStateMessage, DeviceAttributesMessage, MowerCommand
from mower_sdk.errors import MowerAPIError

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


def _is_enabled(val) -> bool:
    return str(val).strip().lower() in ("true", "1", "yes", "on")


def _str_or_none(val) -> "str | None":
    """Return stripped string, or None if missing/empty."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def get_mqtt_broker_config(general: dict) -> dict:
    """Extract LoxBerry MQTT broker settings from general.json."""
    mqtt = general.get("Mqtt", {})

    host     = mqtt.get("Brokerhost", "localhost")
    port     = int(mqtt.get("Brokerport", 1883))
    username = _str_or_none(mqtt.get("Brokeruser"))
    password = _str_or_none(mqtt.get("Brokerpass"))

    use_local = _is_enabled(mqtt.get("Uselocalbroker", "true"))
    tls = False
    tls_verify = False
    tls_cafile = None

    if use_local and _is_enabled(mqtt.get("Tlsenabled", "false")):
        tls       = True
        tls_verify = False  # local broker uses self-signed CA
        tls_cafile = "/etc/mosquitto/tls/ca.crt"
        port       = int(mqtt.get("Tlsport", 8883))
    elif not use_local and _is_enabled(mqtt.get("TlsExternalEnabled", "false")):
        tls        = True
        tls_verify = _is_enabled(mqtt.get("TlsExternalValidatecert", "false"))
        tls_cafile = None  # use system CA bundle for external broker

    return {
        "host":       host,
        "port":       port,
        "username":   username,
        "password":   password,
        "tls":        tls,
        "tls_verify": tls_verify,
        "tls_cafile": tls_cafile,
    }


def _build_mqtt_kwargs(broker: dict) -> dict:
    """Build aiomqtt.Client keyword arguments from broker config dict."""
    kwargs: dict = {
        "hostname": broker["host"],
        "port":     broker["port"],
    }
    if broker["username"] is not None and broker["username"] != "":
        kwargs["username"] = broker["username"]
    if broker["password"] is not None and broker["password"] != "":
        kwargs["password"] = broker["password"]
    if broker.get("tls"):
        ctx = ssl.create_default_context()
        if not broker.get("tls_verify"):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        elif broker.get("tls_cafile") and os.path.isfile(broker["tls_cafile"]):
            ctx.load_verify_locations(broker["tls_cafile"])
        kwargs["tls_context"] = ctx
    return kwargs


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


# ── State / Error normalisation ──────────────────────────────────────────────
_STATE_CODES: dict[str, int] = {
    "idle":      0,
    "mowing":    1,
    "paused":    2,
    "docked":    3,
    "charging":  4,
    "error":     5,
    "returning": 6,
    "unknown":   99,
}

_ERROR_CODES: dict[str, int] = {
    "none":         0,
    "stuck":        1,
    "lifted":       2,
    "rain":         3,
    "battery_low":  4,
    "sensor_error": 5,
    "motor_error":  6,
    "blade_error":  7,
    "unknown":      99,
}


def _normalize_error(error) -> str:
    """Normalize error value from either SDK path to a consistent string."""
    if error is None:
        return "none"
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        for key in ("type", "errorCode", "code", "error"):
            val = error.get(key)
            if isinstance(val, str) and val:
                return val.lower()
        LOGWARN(f"Unknown error dict structure from cloud: {error}")
        return "unknown"
    return "unknown"


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
_attributes_queue: asyncio.Queue = asyncio.Queue()


def _on_navimow_state(msg: "DeviceStateMessage") -> None:
    """Synchronous callback from NavimowSDK — bridge to async queue."""
    try:
        _state_queue.put_nowait(msg)
    except asyncio.QueueFull:
        pass


def _on_navimow_attributes(msg: "DeviceAttributesMessage") -> None:
    """Synchronous callback from NavimowSDK — bridge to async queue."""
    try:
        _attributes_queue.put_nowait(msg)
    except asyncio.QueueFull:
        pass


async def task_navimow_to_mqtt(
    sdk: "NavimowSDK",
    base_topic: str,
    broker: dict,
    shutdown: asyncio.Event,
) -> None:
    """Publish Navimow state updates to LoxBerry MQTT broker."""
    mqtt_kwargs = _build_mqtt_kwargs(broker)

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
                        msg = None

                    if msg is not None:
                        device_id = msg.device_id
                        state_str = msg.state or "unknown"
                        error_str = _normalize_error(msg.error)
                        data: dict = {
                            "state":     state_str,
                            "state_num": _STATE_CODES.get(state_str, 99),
                            "battery":   msg.battery,
                            "error":     error_str,
                            "error_num": _ERROR_CODES.get(error_str, 99),
                        }
                        if msg.signal_strength is not None:
                            data["signal_strength"] = msg.signal_strength
                        if msg.position is not None:
                            data["position"] = msg.position
                        state_payload = json.dumps(data)
                        await lbmqtt.publish(
                            f"{base_topic}/{device_id}/state", state_payload, retain=True
                        )
                        LOGDEB(f"Published state for {device_id}: {state_str} / error={error_str}")

                    # Drain attributes queue every loop cycle (max 5s delay)
                    while not _attributes_queue.empty():
                        try:
                            attrs_msg = _attributes_queue.get_nowait()
                            attrs_payload = json.dumps(attrs_msg.attributes)
                            await lbmqtt.publish(
                                f"{base_topic}/{attrs_msg.device_id}/attributes",
                                attrs_payload, retain=True
                            )
                            LOGDEB(f"Published attributes for {attrs_msg.device_id}: keys={list(attrs_msg.attributes.keys())}")
                        except asyncio.QueueEmpty:
                            break
                        except Exception as e:
                            LOGWARN(f"Attributes publish error: {e}")

        except Exception as e:
            if not shutdown.is_set():
                LOGERR(f"LoxBerry MQTT error: {e} — reconnecting in 10s")
                await asyncio.sleep(10)


async def _publish_command_result(
    lbmqtt, base_topic: str, device_id: str, cmd: str, ok: bool, reason: str = "none"
) -> None:
    payload = json.dumps({
        "command":    cmd,
        "result":     "ok" if ok else "error",
        "result_num": 0 if ok else 1,
        "reason":     reason,
    })
    try:
        await lbmqtt.publish(f"{base_topic}/{device_id}/command_result", payload, retain=False)
    except Exception as e:
        LOGWARN(f"Could not publish command_result: {e}")


# ── Task 8: LoxBerry MQTT → Navimow Commands ─────────────────────────────────
async def task_mqtt_to_navimow(
    api: "MowerAPI",
    base_topic: str,
    broker: dict,
    shutdown: asyncio.Event,
) -> None:
    """Subscribe to LoxBerry MQTT set-topics and forward commands to Navimow via REST."""
    mqtt_kwargs = _build_mqtt_kwargs(broker)

    while not shutdown.is_set():
        try:
            async with aiomqtt.Client(**mqtt_kwargs) as lbmqtt:
                await lbmqtt.subscribe(f"{base_topic}/+/set")
                LOGINF(f"Subscribed to {base_topic}/+/set")

                async for message in lbmqtt.messages:
                    if shutdown.is_set():
                        break
                    topic_parts = str(message.topic).split("/")
                    if len(topic_parts) < 3:
                        continue
                    device_id = topic_parts[-2]
                    payload = message.payload.decode("utf-8", errors="replace").strip()

                    if api is None:
                        LOGWARN(f"Command ignored — no API client available (device {device_id})")
                        continue

                    cmd = payload.lower()
                    if cmd in ("start", "resume"):
                        mower_cmd = MowerCommand.START if cmd == "start" else MowerCommand.RESUME
                        try:
                            await api.async_send_command(device_id, mower_cmd)
                            LOGOK(f"{cmd}({device_id})")
                            await _publish_command_result(lbmqtt, base_topic, device_id, cmd, True)
                        except MowerAPIError as e:
                            reason = e.error_code or "unknown"
                            LOGERR(f"{cmd}({device_id}) failed: {e}")
                            await _publish_command_result(lbmqtt, base_topic, device_id, cmd, False, reason)
                        except Exception as e:
                            LOGERR(f"{cmd}({device_id}) failed: {e}")
                            await _publish_command_result(lbmqtt, base_topic, device_id, cmd, False, "unknown")
                    elif cmd == "pause":
                        try:
                            await api.async_send_command(device_id, MowerCommand.PAUSE)
                            LOGOK(f"pause({device_id})")
                            await _publish_command_result(lbmqtt, base_topic, device_id, "pause", True)
                        except MowerAPIError as e:
                            reason = e.error_code or "unknown"
                            LOGERR(f"pause({device_id}) failed: {e}")
                            await _publish_command_result(lbmqtt, base_topic, device_id, "pause", False, reason)
                        except Exception as e:
                            LOGERR(f"pause({device_id}) failed: {e}")
                            await _publish_command_result(lbmqtt, base_topic, device_id, "pause", False, "unknown")
                    elif cmd in ("dock", "return", "home"):
                        try:
                            await api.async_send_command(device_id, MowerCommand.DOCK)
                            LOGOK(f"dock({device_id})")
                            await _publish_command_result(lbmqtt, base_topic, device_id, "dock", True)
                        except MowerAPIError as e:
                            reason = e.error_code or "unknown"
                            LOGERR(f"dock({device_id}) failed: {e}")
                            await _publish_command_result(lbmqtt, base_topic, device_id, "dock", False, reason)
                        except Exception as e:
                            LOGERR(f"dock({device_id}) failed: {e}")
                            await _publish_command_result(lbmqtt, base_topic, device_id, "dock", False, "unknown")
                    else:
                        LOGWARN(f"Unknown command: {payload}")

        except Exception as e:
            if not shutdown.is_set():
                LOGERR(f"Command MQTT error: {e} — reconnecting in 10s")
                await asyncio.sleep(10)


# ── Task 9: Token Refresh Watchdog ────────────────────────────────────────────
async def _do_token_refresh(plugin_cfg: dict, session: aiohttp.ClientSession) -> bool:
    """Exchange refresh_token for a new access_token. Updates plugin_cfg and saves. Returns True on success."""
    refresh_token = plugin_cfg.get("refresh_token", "")
    if not refresh_token:
        LOGERR("No refresh_token available — re-authentication required")
        return False

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
                return False
            raw = await resp.json(content_type=None)

        data        = raw.get("data", raw) if isinstance(raw.get("data"), dict) else raw
        new_token   = data.get("access_token", "")
        new_refresh = data.get("refresh_token", refresh_token)
        expires_in  = int(data.get("expires_in", 3600))

        if not new_token:
            LOGERR("Token refresh: empty access_token in response")
            return False

        plugin_cfg["access_token"]  = new_token
        plugin_cfg["refresh_token"] = new_refresh
        plugin_cfg["expires_at"]    = int(time.time()) + expires_in
        save_plugin_config(plugin_cfg)
        LOGOK(f"Token refreshed — valid for {expires_in}s")
        return True

    except Exception as e:
        LOGERR(f"Token refresh error: {e}")
        return False


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
        ok = await _do_token_refresh(plugin_cfg, session)
        if ok:
            new_token = plugin_cfg["access_token"]
            if sdk:
                sdk.update_mqtt_credentials(
                    auth_headers={"Authorization": f"Bearer {new_token}"}
                )
            if api:
                api.set_token(new_token)


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

    mqtt_kwargs = _build_mqtt_kwargs(broker)

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
                    state_str = status.status.value
                    error_str = status.error_code.value
                    data: dict = {
                        "state":     state_str,
                        "state_num": _STATE_CODES.get(state_str, 99),
                        "battery":   status.battery,
                        "error":     error_str,
                        "error_num": _ERROR_CODES.get(error_str, 99),
                    }
                    if status.signal_strength is not None:
                        data["signal_strength"] = status.signal_strength
                    if status.position is not None:
                        data["position"] = status.position
                    await lbmqtt.publish(
                        f"{base_topic}/{device_id}/state", json.dumps(data), retain=True
                    )
                    LOGDEB(f"REST fallback published {device_id}: {state_str} / error={error_str}")
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

    LOGINF(f"LoxBerry MQTT broker: {broker['host']}:{broker['port']} tls={broker['tls']} user={'set' if broker['username'] else 'none'}")
    LOGINF(f"Base topic: {plugin_cfg['base_topic']}")
    LOGINF(f"Devices cached: {len(plugin_cfg['devices'])}")

    if not plugin_cfg["access_token"]:
        LOGWARN("No access token configured — gateway will wait for authentication")

    async with aiohttp.ClientSession() as session:
        # Refresh token immediately at startup if expired or expiring within 60s
        if plugin_cfg.get("access_token"):
            expires_at = plugin_cfg.get("expires_at", 0)
            if time.time() >= expires_at - 60:
                LOGINF("Token expired at startup — attempting immediate refresh")
                await _do_token_refresh(plugin_cfg, session)

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
            navimow_sdk.on_attributes(_on_navimow_attributes)
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

        if api:
            tasks.append(asyncio.create_task(
                task_mqtt_to_navimow(api, base_topic, broker, _shutdown_event)
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

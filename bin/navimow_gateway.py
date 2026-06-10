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
import uuid
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import paho.mqtt.client as _paho
import aiomqtt

# ── CLI args ──────────────────────────────────────────────────────────────────
_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument("--logfile",   default="")
_ap.add_argument("--logdbkey",  default="")
_ap.add_argument("--configdir", default="")
_ap.add_argument("--lbsconfig", default="/opt/loxberry/config/system")
_ap.add_argument("--loglevel",  type=int, default=6)
_args, _ = _ap.parse_known_args()

# ── Paths ─────────────────────────────────────────────────────────────────────
LBHOMEDIR    = os.environ.get("LBHOMEDIR", "/opt/loxberry")
LBSCONFIG    = Path(_args.lbsconfig)
CONFIGDIR    = Path(_args.configdir) if _args.configdir else Path(LBHOMEDIR) / "config/plugins/navimow"
GENERAL_JSON = LBSCONFIG / "general.json"
PLUGIN_CFG   = CONFIGDIR / "pluginconfig.json"
PID_FILE     = Path("/dev/shm/navimow_gateway.pid")

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
        LOGWARN("_logend: invalid dbkey value, skipping LOGEND call")
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


_EPHEMERAL_FIELDS = frozenset(("access_token", "expires_at", "token_type"))


def load_plugin_config() -> dict:
    cfg = _load_json(PLUGIN_CFG)
    # Remove stale ephemeral fields written by older plugin versions
    if any(k in cfg for k in _EPHEMERAL_FIELDS):
        for k in _EPHEMERAL_FIELDS:
            cfg.pop(k, None)
        _save_json_atomic(PLUGIN_CFG, cfg)
    cfg.setdefault("base_topic",    "navimow")
    cfg.setdefault("refresh_token", "")
    cfg.setdefault("devices",       [])
    # These live in memory only — never written to SD card
    cfg["access_token"] = ""
    cfg["expires_at"]   = 0
    return cfg


def save_plugin_config(cfg: dict) -> None:
    on_disk = {k: v for k, v in cfg.items() if k not in _EPHEMERAL_FIELDS}
    _save_json_atomic(PLUGIN_CFG, on_disk)


def _is_enabled(val) -> bool:
    return str(val).strip().lower() in ("true", "1", "yes", "on")


def _str_or_none(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def get_mqtt_broker_config(general: dict) -> dict:
    mqtt = general.get("Mqtt", {})
    host     = mqtt.get("Brokerhost", "localhost")
    port     = int(mqtt.get("Brokerport", 1883))
    username = _str_or_none(mqtt.get("Brokeruser"))
    password = _str_or_none(mqtt.get("Brokerpass"))
    use_local = _is_enabled(mqtt.get("Uselocalbroker", "true"))
    tls = tls_verify = False
    tls_cafile = None
    if use_local and _is_enabled(mqtt.get("Tlsenabled", "false")):
        tls       = True
        tls_cafile = "/etc/mosquitto/tls/ca.crt"
        port       = int(mqtt.get("Tlsport", 8883))
    elif not use_local and _is_enabled(mqtt.get("TlsExternalEnabled", "false")):
        tls        = True
        tls_verify = _is_enabled(mqtt.get("TlsExternalValidatecert", "false"))
    return {"host": host, "port": port, "username": username, "password": password,
            "tls": tls, "tls_verify": tls_verify, "tls_cafile": tls_cafile}


def _build_mqtt_kwargs(broker: dict) -> dict:
    kwargs: dict = {"hostname": broker["host"], "port": broker["port"]}
    if broker["username"]:
        kwargs["username"] = broker["username"]
    if broker["password"]:
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


# ── Vehicle state normalisation ───────────────────────────────────────────────
_VEHICLE_STATE_TEXT_MAP: dict = {
    "isRunning":         "mowing",
    "isPaused":          "paused",
    "isDocked":          "docked",
    "isDocking":         "returning",
    "isIdle":            "idle",
    "isIdel":            "idle",      # firmware typo
    "isMapping":         "mapping",
    "isLifted":          "error",
    "inSoftwareUpdate":  "update",
    "Self-Checking":     "selfcheck",
    "Self-checking":     "selfcheck",
    "Error":             "error",
    "error":             "error",
    "Offline":           "offline",
    "offline":           "offline",
    "mowing":            "mowing",
    "paused":            "paused",
    "docked":            "docked",
    "charging":          "charging",
    "returning":         "returning",
    "idle":              "idle",
    "mapping":           "mapping",
    "update":            "update",
    "selfcheck":         "selfcheck",
    "offline":           "offline",
}

_STATE_CODES: dict = {
    "idle":       0,
    "mowing":     1,
    "paused":     2,
    "docked":     3,
    "charging":   4,
    "error":      5,
    "returning":  6,
    "mapping":    7,
    "update":     8,
    "selfcheck":  9,
    "offline":   10,
    "unknown":   99,
}


def _normalize_vehicle_state(raw: str) -> tuple:
    text = _VEHICLE_STATE_TEXT_MAP.get(str(raw).strip(), "unknown")
    return text, _STATE_CODES.get(text, 99)


# ── REST constants & helpers ──────────────────────────────────────────────────
API_BASE  = "https://navimow-fra.ninebot.com"
TOKEN_URL = f"{API_BASE}/openapi/oauth/getAccessToken"
CLIENT_ID     = "homeassistant"
CLIENT_SECRET = "57056e15-722e-42be-bbaa-b0cbfb208a52"


def _rest_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "requestId":     str(uuid.uuid4()),
    }


async def _rest_get_auth_list(session: aiohttp.ClientSession, token: str) -> list:
    """GET /openapi/smarthome/authList → device list with name, model, firmware."""
    try:
        async with session.get(f"{API_BASE}/openapi/smarthome/authList",
                               headers=_rest_headers(token)) as resp:
            data = await resp.json(content_type=None)
        if not isinstance(data, dict) or data.get("code") != 1:
            LOGWARN(f"authList failed: {data.get('desc') if isinstance(data, dict) else data}")
            return []
        return (((data.get("data") or {}).get("payload") or {}).get("devices")) or []
    except Exception as e:
        LOGERR(f"authList error: {e}")
        return []


async def _rest_get_mqtt_info(session: aiohttp.ClientSession, token: str) -> dict:
    """GET /openapi/mqtt/userInfo/get/v2 → mqttUrl, mqttHost, userName, pwdInfo."""
    try:
        async with session.get(f"{API_BASE}/openapi/mqtt/userInfo/get/v2",
                               headers=_rest_headers(token)) as resp:
            data = await resp.json(content_type=None)
        if not isinstance(data, dict) or data.get("code") != 1:
            LOGWARN(f"MQTT userInfo failed: {data.get('desc') if isinstance(data, dict) else data}")
            return {}
        return data.get("data") or {}
    except Exception as e:
        LOGERR(f"MQTT userInfo error: {e}")
        return {}


async def _rest_get_vehicle_status(session: aiohttp.ClientSession, token: str,
                                   device_ids: list) -> list:
    """POST /openapi/smarthome/getVehicleStatus → raw device list."""
    try:
        async with session.post(
            f"{API_BASE}/openapi/smarthome/getVehicleStatus",
            headers=_rest_headers(token),
            json={"devices": [{"id": did} for did in device_ids]},
        ) as resp:
            data = await resp.json(content_type=None)
        if not isinstance(data, dict) or data.get("code") != 1:
            LOGWARN(f"getVehicleStatus failed: {data.get('desc') if isinstance(data, dict) else data}")
            return []
        return (((data.get("data") or {}).get("payload") or {}).get("devices")) or []
    except Exception as e:
        LOGERR(f"getVehicleStatus error: {e}")
        return []


# Command map verified against TA2k/ioBroker.navimow main.js
_COMMAND_MAP: dict = {
    "start":  ("action.devices.commands.StartStop",    {"on": True}),
    "stop":   ("action.devices.commands.StartStop",    {"on": False}),
    "pause":  ("action.devices.commands.PauseUnpause", {"on": False}),
    "resume": ("action.devices.commands.PauseUnpause", {"on": True}),
    "dock":   ("action.devices.commands.Dock",          None),
}
_COMMAND_ALIASES: dict = {
    "mow": "start", "go": "start", "run": "start",
    "home": "dock", "return": "dock",
}


async def _rest_send_command(session: aiohttp.ClientSession, token: str,
                             device_id: str, command: str) -> tuple:
    """POST /openapi/smarthome/sendCommands. Returns (ok, reason)."""
    canonical = _COMMAND_ALIASES.get(command, command)
    if canonical not in _COMMAND_MAP:
        return False, f"unknown command: {command}"
    cmd_str, params = _COMMAND_MAP[canonical]
    execution: dict = {"command": cmd_str}
    if params is not None:
        execution["params"] = params
    body = {"commands": [{"devices": [{"id": device_id}], "execution": execution}]}
    try:
        async with session.post(
            f"{API_BASE}/openapi/smarthome/sendCommands",
            headers=_rest_headers(token),
            json=body,
        ) as resp:
            if resp.status == 401:
                return False, "401 unauthorized"
            data = await resp.json(content_type=None)
        if not isinstance(data, dict) or data.get("code") != 1:
            return False, str(data.get("desc") if isinstance(data, dict) else data)
        results = (((data.get("data") or {}).get("payload") or {}).get("commands")) or []
        for r in results:
            if (isinstance(r, dict) and r.get("status") == "ERROR"
                    and r.get("errorCode") != "alreadyInState"):
                return False, r.get("errorCode") or "error"
        return True, "ok"
    except Exception as e:
        return False, str(e)


def _extract_vehicle_status_fields(dev: dict) -> dict:
    """Extract all useful fields from a raw getVehicleStatus / MQTT state payload."""
    fields: dict = {}

    for key in ("vehicleState", "state", "status"):
        raw = dev.get(key)
        if raw not in (None, "") and not str(raw).lstrip("-").isdigit():
            text, code = _normalize_vehicle_state(str(raw))
            fields["vehicleState_desc"] = text
            fields["state_code"] = code
            break

    cap = dev.get("capacityRemaining")
    bat_val = None
    if isinstance(cap, list) and cap:
        first = cap[0]
        bat_val = first.get("rawValue") if isinstance(first, dict) else first
    elif isinstance(cap, dict):
        bat_val = cap.get("rawValue")
    elif isinstance(cap, (int, float)):
        bat_val = cap
    if bat_val is None:
        bat_val = dev.get("battery")
    try:
        fields["battery"] = int(round(float(bat_val))) if bat_val is not None else None
    except (TypeError, ValueError):
        pass

    desc = dev.get("descriptiveCapacityRemaining") or dev.get("battery_desc")
    if desc:
        fields["battery_desc"] = str(desc)

    err = dev.get("errorCode") or dev.get("error_code")
    if err not in (None, "", "none"):
        fields["error_code"] = str(err)

    if dev.get("action") is not None:
        fields["action"] = dev["action"]

    for key in ("mowingWeekArea", "subtotalArea", "currentMowProgress",
                "currentMowBoundary", "mowStartType", "mapWorkPosition"):
        if dev.get(key) is not None:
            fields[key] = dev[key]

    return {k: v for k, v in fields.items() if v is not None}


# ── Shared device state ───────────────────────────────────────────────────────
_device_state:        dict           = {}
_state_publish_queue: asyncio.Queue  = asyncio.Queue(maxsize=64)
_location_queue:      asyncio.Queue  = asyncio.Queue(maxsize=64)
_event_queue:         asyncio.Queue  = asyncio.Queue(maxsize=64)

# Auth status — published retained to {base_topic}/gateway, read by WebUI via mqtt_get
_auth_payload: dict = {}
_auth_dirty:   bool = False


def _update_auth_status(plugin_cfg: dict, base_topic: str) -> None:
    global _auth_dirty
    token      = plugin_cfg.get("access_token", "")
    expires_at = plugin_cfg.get("expires_at", 0)
    _auth_payload.clear()
    _auth_payload.update({
        "topic":         f"{base_topic}/gateway",
        "state":         "running",
        "authenticated": bool(token and expires_at > time.time()),
        "expires_at":    expires_at,
        "token":         token,
    })
    _auth_dirty = True

_last_cloud_msg_time: float = 0.0
_last_activity:       float = 0.0
_activity_refresh_due: bool = False


def _update_state(device_id: str, updates: dict) -> None:
    if device_id not in _device_state:
        _device_state[device_id] = {}
    _device_state[device_id].update(
        {k: v for k, v in updates.items() if v is not None}
    )
    try:
        _state_publish_queue.put_nowait(device_id)
    except asyncio.QueueFull:
        pass


def _touch_cloud_msg_time() -> None:
    global _last_cloud_msg_time
    _last_cloud_msg_time = time.time()


# ── Cloud MQTT message handler ────────────────────────────────────────────────
def _on_cloud_message(device_id: str, channel: str, payload: bytes) -> None:
    """Synchronous handler — scheduled into the asyncio loop via call_soon_threadsafe."""
    global _activity_refresh_due, _last_activity
    _touch_cloud_msg_time()

    now = time.time()
    if (now - _last_activity) > 30:
        _activity_refresh_due = True
    _last_activity = now

    if channel in ("state", "attributes"):
        try:
            raw = json.loads(payload.decode("utf-8", "replace"))
            if isinstance(raw, list) and raw:
                raw = raw[-1]
            if isinstance(raw, dict) and raw:
                fields = _extract_vehicle_status_fields(raw)
                if fields:
                    _update_state(device_id, fields)
                    LOGDEB(f"MQTT {channel} for {device_id}: {list(fields.keys())}")
        except Exception as e:
            LOGWARN(f"MQTT {channel} parse error: {e}")

    elif channel == "location":
        # The cloud sends two location message types:
        #   type=1 — GPS position: postureX/Y/Theta, vehicleState
        #   type=2 — Mowing statistics: action, mowingWeekArea, subtotalArea,
        #            currentMowProgress, currentMowBoundary, mowStartType, mapWorkPosition
        try:
            raw = json.loads(payload.decode("utf-8", "replace"))
            entry = (raw[-1] if isinstance(raw, list) and raw
                     else raw if isinstance(raw, dict) else {})

            msg_type = entry.get("type", 1)

            if msg_type == 2:
                # Mowing statistics — merge into state
                state_upd: dict = {}
                for key in ("action", "currentMowBoundary", "currentMowProgress",
                            "mapWorkPosition", "mowStartType"):
                    if entry.get(key) is not None:
                        state_upd[key] = entry[key]
                for key in ("mowingWeekArea", "subtotalArea"):
                    v = entry.get(key)
                    if v is not None:
                        try:
                            state_upd[key] = float(v)
                        except (TypeError, ValueError):
                            state_upd[key] = v
                pct = entry.get("mowingPercentage")
                if pct is not None:
                    try:
                        state_upd["mowingPercentage"] = int(pct)
                    except (TypeError, ValueError):
                        state_upd["mowingPercentage"] = pct
                if state_upd:
                    _update_state(device_id, state_upd)
                    LOGDEB(f"Location type=2 → state for {device_id}: {list(state_upd.keys())}")
            else:
                # type=1 — GPS position
                state_upd = {}
                vs = entry.get("vehicleState")
                if vs is not None:
                    try:
                        state_upd["vehicleState"] = int(vs)
                    except (TypeError, ValueError):
                        state_upd["vehicleState"] = vs
                pct = entry.get("mowingPercentage")
                if pct is not None:
                    try:
                        state_upd["mowingPercentage"] = int(pct)
                    except (TypeError, ValueError):
                        state_upd["mowingPercentage"] = pct
                if state_upd:
                    _update_state(device_id, state_upd)

                loc: dict = {}
                for key in ("postureX", "postureY", "postureTheta"):
                    v = entry.get(key)
                    if v is not None:
                        try:
                            loc[key] = float(v)
                        except (TypeError, ValueError):
                            loc[key] = v
                if pct is not None:
                    loc["mowingPercentage"] = state_upd.get("mowingPercentage", pct)
                if entry.get("time") is not None:
                    loc["time"] = entry["time"]
                if loc:
                    _location_queue.put_nowait({"device_id": device_id, "data": loc})
                    LOGDEB(f"Location queued for {device_id}")
                else:
                    LOGDEB(f"Location skipped for {device_id} — empty payload")
        except asyncio.QueueFull:
            pass
        except Exception as e:
            LOGWARN(f"Location parse error: {e}")

    elif channel == "event":
        try:
            evt = json.loads(payload.decode("utf-8", "replace"))
            _event_queue.put_nowait({"device_id": device_id, "data": evt})
            LOGINF(f"Event queued for {device_id}")
        except asyncio.QueueFull:
            pass
        except Exception as e:
            LOGWARN(f"Event parse error: {e}")


# ── Navimow Cloud MQTT client ─────────────────────────────────────────────────
class NavimowCloudMQTT:
    """Manages the WSS paho-MQTT connection to the Navimow cloud broker.

    Replaces NavimowSDK. Uses paho directly with WebSocket/TLS transport.
    The Authorization: Bearer token is injected on every WS upgrade.
    """

    KEEPALIVE = 2400  # seconds — matches TA2k/ioBroker.navimow

    def __init__(self, mqtt_host: str, mqtt_url: str,
                 username: str, password: str, token: str, device_ids: list):
        self._host, self._ws_path = self._parse_endpoint(mqtt_host, mqtt_url)
        self._username   = username
        self._password   = password
        self._token      = token
        self._device_ids = list(device_ids)
        self._client     = None
        self._loop       = None
        self._token_ref  = [token]  # mutable list so the WS-headers closure picks up updates

    @staticmethod
    def _parse_endpoint(mqtt_host: str, mqtt_url: str) -> tuple:
        host = mqtt_host or ""
        if "://" in host:
            host = urlparse(host).hostname or host
        ws_path = "/"
        if mqtt_url:
            parsed = urlparse(mqtt_url)
            if parsed.hostname and not host:
                host = parsed.hostname
            path = parsed.path or "/"
            ws_path = (path + "?" + parsed.query) if parsed.query else path
        return (host or "mqtt-fra.navimow.com"), ws_path

    def _make_client(self, client_id: str):
        try:
            client = _paho.Client(
                callback_api_version=_paho.CallbackAPIVersion.VERSION1,
                client_id=client_id,
                transport="websockets",
            )
        except (TypeError, AttributeError):
            client = _paho.Client(client_id=client_id, transport="websockets")

        if self._username and self._password:
            client.username_pw_set(self._username, self._password)

        token_ref = self._token_ref

        def _ws_headers(headers):
            h = dict(headers)
            h["Authorization"] = "Bearer " + token_ref[0]
            h.pop("Origin", None)
            return h

        client.ws_set_options(path=self._ws_path, headers=_ws_headers)
        client.tls_set()
        client.reconnect_delay_set(min_delay=5, max_delay=60)
        client.on_connect    = self._cb_connect
        client.on_message    = self._cb_message
        client.on_disconnect = self._cb_disconnect
        return client

    def _cb_connect(self, client, userdata, flags, rc):
        if rc != 0:
            LOGWARN(f"Cloud MQTT connect failed rc={rc}")
            return
        LOGOK("Cloud MQTT connected")
        for did in self._device_ids:
            for ch in ("state", "event", "attributes", "location"):
                client.subscribe(f"/downlink/vehicle/{did}/realtimeDate/{ch}")
            client.subscribe(f"/downlink/vehicle/{did}/#")
        LOGINF(f"Subscribed to cloud MQTT topics for {len(self._device_ids)} device(s)")

    def _cb_disconnect(self, client, userdata, rc):
        LOGINF(f"Cloud MQTT disconnected rc={rc}")

    def _cb_message(self, client, userdata, msg):
        parts = [p for p in msg.topic.split("/") if p]
        if len(parts) < 3 or parts[0] != "downlink" or parts[1] != "vehicle":
            return
        device_id = parts[2]
        channel   = parts[4] if len(parts) >= 5 else None
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                _on_cloud_message, device_id, channel, msg.payload
            )

    def connect(self, loop) -> None:
        self._loop = loop
        self.disconnect()
        client_id = "navimow_loxberry_" + uuid.uuid4().hex[:10]
        client = self._make_client(client_id)
        self._client = client
        try:
            client.connect(self._host, 443, keepalive=self.KEEPALIVE)
            client.loop_start()
            LOGINF(f"Cloud MQTT connecting to {self._host}:443")
        except Exception as e:
            LOGERR(f"Cloud MQTT connect error: {e}")
            client.loop_stop()
            self._client = None

    def disconnect(self) -> None:
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def update_token(self, token: str) -> None:
        self._token = token
        self._token_ref[0] = token  # picked up by WS-headers closure on next connect


# ── REST init ─────────────────────────────────────────────────────────────────
async def rest_init(plugin_cfg: dict, session: aiohttp.ClientSession) -> dict:
    """Fetch device list and MQTT credentials. Updates plugin_cfg in place."""
    token = plugin_cfg.get("access_token", "")
    if not token:
        LOGWARN("No access token — skipping REST init")
        return {}

    auth_devices = await _rest_get_auth_list(session, token)
    if auth_devices:
        LOGOK(f"Found {len(auth_devices)} device(s) on account")
        new_devices = [
            {"device_id": d["id"], "name": d.get("name") or d.get("deviceName") or d["id"]}
            for d in auth_devices if d.get("id")
        ]
        if new_devices != plugin_cfg.get("devices", []):
            plugin_cfg["devices"] = new_devices
            save_plugin_config(plugin_cfg)
            LOGINF("Device list changed — persisted to config")
        else:
            plugin_cfg["devices"] = new_devices
    else:
        LOGWARN("No devices found via authList")

    mqtt_info = await _rest_get_mqtt_info(session, token)
    if mqtt_info:
        LOGINF(f"Navimow MQTT host: {mqtt_info.get('mqttHost', '?')}")
    return mqtt_info


# ── Task 7: Navimow cloud → LoxBerry MQTT ────────────────────────────────────
async def task_navimow_to_mqtt(
    base_topic: str,
    broker: dict,
    shutdown: asyncio.Event,
) -> None:
    mqtt_kwargs = _build_mqtt_kwargs(broker)
    gw_topic    = f"{base_topic}/gateway"
    lwt_payload = json.dumps({"state": "stopped"})
    will = aiomqtt.Will(topic=gw_topic, payload=lwt_payload, qos=1, retain=True)
    while not shutdown.is_set():
        try:
            async with aiomqtt.Client(**mqtt_kwargs, will=will) as lbmqtt:
                LOGOK(f"Connected to LoxBerry MQTT {broker['host']}:{broker['port']}")
                while not shutdown.is_set():
                    try:
                        device_id = await asyncio.wait_for(
                            _state_publish_queue.get(), timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        device_id = None

                    to_publish: set = set()
                    if device_id:
                        to_publish.add(device_id)
                    while not _state_publish_queue.empty():
                        try:
                            to_publish.add(_state_publish_queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break

                    for did in to_publish:
                        state = _device_state.get(did)
                        if state:
                            await lbmqtt.publish(
                                f"{base_topic}/{did}/state",
                                json.dumps(state), retain=True
                            )
                            LOGDEB(f"Published state for {did}: "
                                   f"{state.get('vehicleState_desc', '?')}")

                    while not _location_queue.empty():
                        try:
                            loc = _location_queue.get_nowait()
                            await lbmqtt.publish(
                                f"{base_topic}/{loc['device_id']}/location",
                                json.dumps(loc["data"]), retain=True
                            )
                            LOGDEB(f"Published location for {loc['device_id']}")
                        except asyncio.QueueEmpty:
                            break
                        except Exception as e:
                            LOGWARN(f"Location publish error: {e}")

                    while not _event_queue.empty():
                        try:
                            evt = _event_queue.get_nowait()
                            await lbmqtt.publish(
                                f"{base_topic}/{evt['device_id']}/event",
                                json.dumps(evt["data"]), retain=False
                            )
                            LOGINF(f"Published event for {evt['device_id']}")
                        except asyncio.QueueEmpty:
                            break
                        except Exception as e:
                            LOGWARN(f"Event publish error: {e}")

                    global _auth_dirty
                    if _auth_dirty and _auth_payload:
                        _auth_dirty = False
                        topic = _auth_payload["topic"]
                        payload = {k: v for k, v in _auth_payload.items() if k != "topic"}
                        await lbmqtt.publish(topic, json.dumps(payload), retain=True)
                        LOGDEB(f"Published auth status: authenticated={payload.get('authenticated')}")

        except Exception as e:
            if not shutdown.is_set():
                LOGERR(f"LoxBerry MQTT error: {e} — reconnecting in 10s")
                await asyncio.sleep(10)


async def _publish_command_result(lbmqtt, base_topic, device_id, cmd, ok, reason="none"):
    payload = json.dumps({
        "command":    cmd,
        "result":     "ok" if ok else "error",
        "result_num": 0 if ok else 1,
        "reason":     reason,
    })
    try:
        await lbmqtt.publish(f"{base_topic}/{device_id}/command_result",
                             payload, retain=False)
    except Exception as e:
        LOGWARN(f"Could not publish command_result: {e}")


# ── Task 8: LoxBerry MQTT → Navimow commands ─────────────────────────────────
async def task_mqtt_to_navimow(
    session: aiohttp.ClientSession,
    plugin_cfg: dict,
    base_topic: str,
    broker: dict,
    shutdown: asyncio.Event,
) -> None:
    mqtt_kwargs = _build_mqtt_kwargs(broker)
    while not shutdown.is_set():
        try:
            async with aiomqtt.Client(**mqtt_kwargs) as lbmqtt:
                await lbmqtt.subscribe(f"{base_topic}/+/set")
                LOGINF(f"Subscribed to {base_topic}/+/set")
                async for message in lbmqtt.messages:
                    if shutdown.is_set():
                        break
                    parts = str(message.topic).split("/")
                    if len(parts) < 3:
                        continue
                    device_id = parts[-2]
                    cmd = message.payload.decode("utf-8", errors="replace").strip().lower()
                    token = plugin_cfg.get("access_token", "")
                    if not token:
                        LOGWARN(f"Command ignored — no token (device {device_id})")
                        continue
                    canonical = _COMMAND_ALIASES.get(cmd, cmd)
                    if canonical not in _COMMAND_MAP:
                        LOGWARN(f"Unknown command: {cmd}")
                        continue
                    ok, reason = await _rest_send_command(session, token, device_id, canonical)
                    if ok:
                        LOGOK(f"{canonical}({device_id})")
                    else:
                        LOGERR(f"{canonical}({device_id}) failed: {reason}")
                    await _publish_command_result(lbmqtt, base_topic, device_id,
                                                  canonical, ok, reason)
        except Exception as e:
            if not shutdown.is_set():
                LOGERR(f"Command MQTT error: {e} — reconnecting in 10s")
                await asyncio.sleep(10)


# ── Task 9: Token Refresh ─────────────────────────────────────────────────────
async def _do_token_refresh(plugin_cfg: dict, session: aiohttp.ClientSession) -> bool:
    refresh_token = plugin_cfg.get("refresh_token", "")
    if not refresh_token:
        LOGERR("No refresh_token — re-authentication required")
        return False
    try:
        async with session.post(
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token,
                  "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            if resp.status != 200:
                LOGERR(f"Token refresh HTTP {resp.status}: {(await resp.text())[:200]}")
                return False
            raw = await resp.json(content_type=None)
        data        = raw.get("data", raw) if isinstance(raw.get("data"), dict) else raw
        new_token   = data.get("access_token", "")
        new_refresh = data.get("refresh_token", refresh_token)
        expires_in  = int(data.get("expires_in", 3600))
        if not new_token:
            LOGERR("Token refresh: empty access_token in response")
            return False
        plugin_cfg["access_token"] = new_token
        plugin_cfg["expires_at"]   = int(time.time()) + expires_in
        if new_refresh != refresh_token:
            plugin_cfg["refresh_token"] = new_refresh
            save_plugin_config(plugin_cfg)
            LOGOK(f"Token refreshed, new refresh_token persisted — valid for {expires_in}s")
        else:
            LOGOK(f"Token refreshed (memory only) — valid for {expires_in}s")
        return True
    except Exception as e:
        LOGERR(f"Token refresh error: {e}")
        return False


async def task_token_refresh(
    plugin_cfg: dict,
    session: aiohttp.ClientSession,
    cloud_mqtt,
    base_topic: str,
    shutdown: asyncio.Event,
) -> None:
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
            if cloud_mqtt:
                cloud_mqtt.update_token(plugin_cfg["access_token"])
            _update_auth_status(plugin_cfg, base_topic)


# ── Task 10: REST Poll ────────────────────────────────────────────────────────
_REST_POLL_INTERVAL = 300  # seconds


async def task_rest_poll(
    session: aiohttp.ClientSession,
    plugin_cfg: dict,
    shutdown: asyncio.Event,
) -> None:
    global _activity_refresh_due

    if not plugin_cfg.get("access_token"):
        LOGINF("REST poll disabled — no access token")
        return

    async def _do_poll(reason: str) -> None:
        device_ids = [d["device_id"] for d in plugin_cfg.get("devices", [])]
        if not device_ids:
            return
        token = plugin_cfg.get("access_token", "")
        LOGINF(f"REST poll ({reason}): querying {len(device_ids)} device(s)")
        for dev in await _rest_get_vehicle_status(session, token, device_ids):
            did = dev.get("id") or dev.get("device_id")
            if not did:
                continue
            fields = _extract_vehicle_status_fields(dev)
            if fields:
                _update_state(did, fields)
                LOGDEB(f"REST poll updated {did}: {list(fields.keys())}")

    await _do_poll("startup")
    last_poll = time.time()

    while not shutdown.is_set():
        await asyncio.sleep(10)
        if shutdown.is_set():
            break
        now = time.time()
        if _activity_refresh_due:
            _activity_refresh_due = False
            await _do_poll("activity")
            last_poll = now
        elif (now - last_poll) >= _REST_POLL_INTERVAL:
            await _do_poll("interval")
            last_poll = now


# ── Task 11: Cloud MQTT Watchdog ──────────────────────────────────────────────
async def task_cloud_mqtt_watchdog(
    cloud_mqtt: "NavimowCloudMQTT",
    session: aiohttp.ClientSession,
    plugin_cfg: dict,
    shutdown: asyncio.Event,
) -> None:
    if cloud_mqtt is None:
        return
    while not shutdown.is_set():
        await asyncio.sleep(60)
        if shutdown.is_set():
            break
        silence = time.time() - _last_cloud_msg_time
        if silence < 120:
            continue

        device_ids = [d["device_id"] for d in plugin_cfg.get("devices", [])]
        token = plugin_cfg.get("access_token", "")
        if not device_ids or not token:
            continue

        active = False
        try:
            for dev in await _rest_get_vehicle_status(session, token, device_ids):
                for key in ("vehicleState", "state"):
                    raw = dev.get(key)
                    if raw and not str(raw).lstrip("-").isdigit():
                        text, _ = _normalize_vehicle_state(str(raw))
                        if text not in ("docked", "charging", "offline", "unknown"):
                            active = True
                        break
                if active:
                    break
        except Exception:
            pass

        if active:
            LOGWARN(f"Cloud MQTT silent for {int(silence)}s while mower active — reconnecting")
            cloud_mqtt.disconnect()
            await asyncio.sleep(2)
            cloud_mqtt.connect(asyncio.get_event_loop())
            LOGOK("Cloud MQTT reconnected by watchdog")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    LOGSTART("Navimow Gateway starting")
    write_pid()

    loop = asyncio.get_event_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
        loop.add_signal_handler(signal.SIGINT,  _handle_sigterm)
    except NotImplementedError:
        pass

    general    = load_general_config()
    plugin_cfg = load_plugin_config()
    broker     = get_mqtt_broker_config(general)

    LOGINF(f"LoxBerry MQTT broker: {broker['host']}:{broker['port']} "
           f"tls={broker['tls']} user={'set' if broker['username'] else 'none'}")
    LOGINF(f"Base topic: {plugin_cfg['base_topic']}")
    LOGINF(f"Devices cached: {len(plugin_cfg['devices'])}")

    base_topic = plugin_cfg["base_topic"]

    if not plugin_cfg.get("refresh_token"):
        LOGWARN("No refresh_token — authentication required")

    async with aiohttp.ClientSession() as session:
        if plugin_cfg.get("refresh_token"):
            LOGINF("Refreshing access token at startup")
            await _do_token_refresh(plugin_cfg, session)
        _update_auth_status(plugin_cfg, base_topic)

        mqtt_info = await rest_init(plugin_cfg, session)

        # Publish static mower info (model, firmware) — retain=True, persists across restarts
        if plugin_cfg.get("access_token") and plugin_cfg.get("devices"):
            auth_devices = await _rest_get_auth_list(session, plugin_cfg["access_token"])
            if auth_devices:
                try:
                    async with aiomqtt.Client(**_build_mqtt_kwargs(broker)) as lbmqtt:
                        for dev in auth_devices:
                            did = dev.get("id")
                            if not did:
                                continue
                            mower_info = {k: v for k, v in {
                                "id":       did,
                                "name":     dev.get("name") or dev.get("deviceName"),
                                "model":    dev.get("model") or dev.get("productName"),
                                "firmware": (dev.get("firmware_version")
                                             or dev.get("firmwareVersion")
                                             or dev.get("fwVersion")
                                             or dev.get("firmware")),
                            }.items() if v is not None}
                            await lbmqtt.publish(
                                f"{base_topic}/{did}/mower",
                                json.dumps(mower_info), retain=True
                            )
                            LOGOK(f"Published mower info for {did}: "
                                  f"model={mower_info.get('model')} "
                                  f"fw={mower_info.get('firmware')}")
                except Exception as e:
                    LOGWARN(f"Could not publish mower info: {e}")

        # Create cloud MQTT client (replaces NavimowSDK)
        cloud_mqtt = None
        if mqtt_info and plugin_cfg.get("access_token"):
            device_ids = [d["device_id"] for d in plugin_cfg.get("devices", [])]
            cloud_mqtt = NavimowCloudMQTT(
                mqtt_host  = mqtt_info.get("mqttHost", ""),
                mqtt_url   = mqtt_info.get("mqttUrl",  ""),
                username   = mqtt_info.get("userName"),
                password   = mqtt_info.get("pwdInfo"),
                token      = plugin_cfg["access_token"],
                device_ids = device_ids,
            )
            cloud_mqtt.connect(loop)
        else:
            LOGWARN("Cloud MQTT not started — missing token or MQTT info")

        tasks = [
            asyncio.create_task(
                task_navimow_to_mqtt(base_topic, broker, _shutdown_event)
            ),
            asyncio.create_task(
                task_mqtt_to_navimow(session, plugin_cfg, base_topic, broker, _shutdown_event)
            ),
            asyncio.create_task(
                task_token_refresh(plugin_cfg, session, cloud_mqtt, base_topic, _shutdown_event)
            ),
            asyncio.create_task(
                task_rest_poll(session, plugin_cfg, _shutdown_event)
            ),
            asyncio.create_task(
                task_cloud_mqtt_watchdog(cloud_mqtt, session, plugin_cfg, _shutdown_event)
            ),
        ]

        await _shutdown_event.wait()

        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if cloud_mqtt:
            cloud_mqtt.disconnect()

        # Publish stopped state on clean shutdown (LWT covers unexpected disconnect)
        gw_topic = f"{base_topic}/gateway"
        try:
            async with aiomqtt.Client(**_build_mqtt_kwargs(broker)) as lbmqtt:
                await lbmqtt.publish(gw_topic, json.dumps({"state": "stopped"}), retain=True)
            LOGINF("Published gateway stopped state")
        except Exception as e:
            LOGWARN(f"Could not publish stopped state: {e}")

    LOGINF("Gateway stopped")
    remove_pid()
    _logend()


if __name__ == "__main__":
    asyncio.run(main())

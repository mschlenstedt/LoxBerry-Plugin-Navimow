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

        # Tasks 7–10 will be added here
        await _shutdown_event.wait()

    LOGINF("Gateway stopped")
    remove_pid()
    _logend()


if __name__ == "__main__":
    asyncio.run(main())

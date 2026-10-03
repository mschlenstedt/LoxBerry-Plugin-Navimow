#!/usr/bin/env python3
"""Einmaliger Login-Helfer für die inoffizielle Navimow-API.

Von ajax.cgi als Subprozess aufgerufen: E-Mail/Passwort kommen als JSON über
stdin (nie als argv -- landen sonst im Klartext in der Prozessliste), werden
nur transient verwendet und nirgends persistiert. Ergebnis (refresh_token,
uid, Geräte-Zuordnung) wird direkt in pluginconfig.json geschrieben.

Eigenständiges Config-Laden statt Import von navimow_gateway.py -- dasselbe
Muster wie navimow_probe.py, um den Daemon-Code (asyncio-Tasks, MQTT-Client-
Aufbau) nicht als Nebeneffekt eines Login-Aufrufs mitzuimportieren.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import aiohttp

import navimow_unofficial_auth as auth
from navimow_unofficial_client import NavimowUnofficialClient, NavimowError
from navimow_unofficial_const import mower_hosts


def _load_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


def _match_devices(official: list, unofficial: list) -> list:
    """Ordnet offizielle device_id und inoffizielle vehicle_sn einander zu.

    Automatisch nur im eindeutigen Fall (genau ein Gerät auf jeder Seite) --
    bei mehreren Geräten gibt es serverseitig kein gemeinsames Feld, an dem
    sich das zweifelsfrei zuordnen liesse, also lieber leer zurückgeben und
    manuelles Eintragen verlangen als falsch zuordnen.
    """
    if len(official) == 1 and len(unofficial) == 1:
        return [{
            "device_id": official[0]["device_id"],
            "vehicle_sn": str(unofficial[0].get("vehicle_sn", "")),
            "vehicle_type": int(unofficial[0].get("vehicle_type", 0) or 0),
        }]
    return []


def _vehicle_list(unofficial: list) -> list:
    return [{
        "vehicle_sn": str(v.get("vehicle_sn", "")),
        "vehicle_type": int(v.get("vehicle_type", 0) or 0),
        "name": str(v.get("vehicle_name") or v.get("name") or ""),
    } for v in unofficial if v.get("vehicle_sn")]


def _resolve_mapping(official: list, unofficial: list, existing: list) -> list:
    """Automatische Zuordnung, sonst eine frühere manuelle, solange ihre Mäher noch im Konto sind."""
    matched = _match_devices(official, unofficial)
    if matched:
        return matched
    known = {str(v.get("vehicle_sn", "")) for v in unofficial}
    kept = [m for m in existing if isinstance(m, dict) and m.get("vehicle_sn") in known]
    return kept


async def _do_login(configdir: Path, email: str, password: str) -> dict:
    plugin_cfg_path = configdir / "pluginconfig.json"
    if plugin_cfg_path.exists():
        try:
            with open(plugin_cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            return {"ok": False, "error": "pluginconfig.json unreadable"}
        if not isinstance(cfg, dict):
            return {"ok": False, "error": "pluginconfig.json unreadable"}
    else:
        cfg = {}
    cfg.setdefault("unofficial_client_device_id", uuid.uuid4().hex)

    async with aiohttp.ClientSession() as session:
        tokens = await auth.login(session, email, password)
        host = mower_hosts(tokens.region)[0]
        client = NavimowUnofficialClient(
            session, cfg["unofficial_client_device_id"],
            tokens=tokens, region=tokens.region or "fra", host=host,
        )
        await client.mower_login()
        unofficial_devices = await client.auth_list()

    official_devices = cfg.get("devices", [])
    mapping = _resolve_mapping(official_devices, unofficial_devices, cfg.get("unofficial_devices", []))

    cfg["unofficial_region"] = tokens.region or ""
    cfg["unofficial_uuid"] = tokens.uuid
    cfg["unofficial_access_token"] = tokens.access_token
    cfg["unofficial_refresh_token"] = tokens.refresh_token
    cfg["unofficial_uid"] = client.uid
    cfg["unofficial_host"] = host
    cfg["unofficial_enabled"] = True
    cfg["unofficial_vehicles"] = _vehicle_list(unofficial_devices)
    cfg["unofficial_devices"] = mapping
    _save_json_atomic(plugin_cfg_path, cfg)

    return {
        "ok": True,
        "devices_total_official": len(official_devices),
        "devices_total_unofficial": len(unofficial_devices),
        "devices_matched": len(mapping),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configdir", required=True)
    args = ap.parse_args()

    try:
        payload = json.loads(sys.stdin.read())
        email = str(payload["email"])
        password = str(payload["password"])
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"invalid stdin payload: {e}"}))
        return 1

    try:
        result = asyncio.run(_do_login(Path(args.configdir), email, password))
    except (auth.PassportError, NavimowError) as e:
        print(json.dumps({"ok": False, "code": str(e.code), "error": str(e.desc or e)}))
        return 1
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(json.dumps({"ok": False, "code": "network", "error": str(e) or type(e).__name__}))
        return 1
    except Exception as e:
        print(json.dumps({"ok": False, "code": "unexpected", "error": str(e)}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

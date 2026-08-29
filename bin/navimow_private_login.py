#!/usr/bin/env python3
"""Einmaliger Login-Helfer fuer die private Navimow-API.

Von ajax.cgi als Subprozess aufgerufen: E-Mail/Passwort kommen als JSON ueber
stdin (nie als argv -- landen sonst im Klartext in der Prozessliste), werden
nur transient verwendet und nirgends persistiert. Ergebnis (refresh_token,
uid, Geraete-Zuordnung) wird direkt in pluginconfig.json geschrieben.

Eigenstaendiges Config-Laden statt Import von navimow_gateway.py -- dasselbe
Muster wie navimow_probe.py, um den Daemon-Code (asyncio-Tasks, MQTT-Client-
Aufbau) nicht als Nebeneffekt eines Login-Aufrufs mitzuimportieren.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

import aiohttp

import navimow_private_auth as auth
from navimow_private_client import NavimowPrivateClient, NavimowError
from navimow_private_const import mower_hosts


def _load_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


def _match_devices(official: list, private: list) -> list:
    """Ordnet offizielle device_id und private vehicle_sn einander zu.

    Automatisch nur im eindeutigen Fall (genau ein Geraet auf jeder Seite) --
    bei mehreren Geraeten gibt es serverseitig kein gemeinsames Feld, an dem
    sich das zweifelsfrei zuordnen liesse, also lieber leer zurueckgeben und
    manuelles Eintragen verlangen als falsch zuordnen.
    """
    if len(official) == 1 and len(private) == 1:
        return [{
            "device_id": official[0]["device_id"],
            "vehicle_sn": str(private[0].get("vehicle_sn", "")),
            "vehicle_type": int(private[0].get("vehicle_type", 0) or 0),
        }]
    return []


async def _do_login(configdir: Path, email: str, password: str) -> dict:
    plugin_cfg_path = configdir / "pluginconfig.json"
    cfg = _load_json(plugin_cfg_path)
    cfg.setdefault("private_client_device_id", uuid.uuid4().hex)

    async with aiohttp.ClientSession() as session:
        tokens = await auth.login(session, email, password)
        host = mower_hosts(tokens.region)[0]
        client = NavimowPrivateClient(
            session, cfg["private_client_device_id"],
            tokens=tokens, region=tokens.region or "fra", host=host,
        )
        await client.mower_login()
        private_devices = await client.auth_list()

    official_devices = cfg.get("devices", [])
    matched = _match_devices(official_devices, private_devices)

    cfg["private_region"] = tokens.region or ""
    cfg["private_uuid"] = tokens.uuid
    cfg["private_refresh_token"] = tokens.refresh_token
    cfg["private_uid"] = client.uid
    cfg["private_host"] = host
    cfg["private_enabled"] = True
    if matched:
        cfg["private_devices"] = matched
    _save_json_atomic(plugin_cfg_path, cfg)

    return {
        "ok": True,
        "devices_total_official": len(official_devices),
        "devices_total_private": len(private_devices),
        "devices_matched": len(matched),
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
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"unexpected error: {e}"}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

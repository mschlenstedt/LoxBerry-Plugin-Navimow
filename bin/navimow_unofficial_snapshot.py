"""Liest Zonen, Wochenplan, Einstellungen, Fähigkeiten und Fehlerzustand eines Mähers über die inoffizielle API."""
from __future__ import annotations

import navimow_unofficial_fault as fault_mod
import navimow_unofficial_plan as plan
import navimow_unofficial_settings as settings_mod
from navimow_unofficial_client import NavimowError


async def fetch_zones(client, sn: str, vehicle_type: int, cache: plan.ZoneCache) -> list[dict]:
    """Zonen aus der Karte; geladen wird nur, wenn sich die Kartenversion geändert hat."""
    try:
        location = await client.location(sn, vehicle_type)
    except NavimowError:
        location = {}
    ids = plan.pick_map_ids(location, None)
    if ids is None:
        try:
            map_list = await client.map_list(sn)
        except NavimowError:
            map_list = None
        ids = plan.pick_map_ids(None, map_list)
    if ids is None or (ids == cache.key and cache.zones):
        return cache.zones
    zones = plan.extract_zones(await client.map_detail(sn, ids[0], ids[1]))
    if zones:
        cache.key, cache.zones = ids, zones
    return cache.zones


async def fetch_settings_and_schedule(client, sn: str, zones: list[dict]) -> tuple[dict, dict]:
    """Einstellungen und Wochenplan aus einer einzigen set-list-Antwort."""
    set_list = await client.set_list(sn)
    return (settings_mod.parse_settings(set_list),
            plan.parse_schedule(set_list, {z["id"]: z["name"] for z in zones}))


async def fetch_device(client, sn: str, model: str = "") -> dict:
    return settings_mod.parse_device(await client.device_info(sn), model)


async def fetch_fault(client, sn: str, vehicle_type: int) -> dict:
    """Zustand aus index2; Fehlerdetails nur bei Verdacht (sonst unnötige Abfrage je Runde)."""
    index2 = await client.index2(sn)
    errors: object = {}
    if fault_mod.needs_fault_detail(index2):
        try:
            errors = await client.errors(sn, vehicle_type)
        except NavimowError:
            errors = {}
    return fault_mod.parse_fault(index2, errors)

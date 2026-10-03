"""Liest Zonen und Wochenplan eines Mähers über die inoffizielle API."""
from __future__ import annotations

import navimow_unofficial_plan as plan
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


async def fetch_schedule(client, sn: str, zones: list[dict]) -> dict:
    return plan.parse_schedule(await client.set_list(sn), {z["id"]: z["name"] for z in zones})

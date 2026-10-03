"""Zonen, Mähbefehl und Wochenplan der inoffiziellen Navimow-API.

Reine Funktionen ohne I/O. Byte-Formate und Semantik aus ilguala/navimow_pro
(const.py, api/client.py, services.py, coordinator.py), dort live verifiziert.
"""
from __future__ import annotations

import json
from typing import Any

# Navimow zählt die Wochentage ab Sonntag: 1 = Sonntag ... 7 = Samstag.
WEEKDAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
SLOT_MINUTES = 15


class PlanError(ValueError):
    """Ein Befehl lässt sich so nicht senden; die Meldung geht an den Nutzer."""


class ZoneCache:
    """Zonen eines Mähers, gemerkt zum Schlüssel (map_id, map_base_id, edit_time)."""

    def __init__(self) -> None:
        self.key: tuple | None = None
        self.zones: list[dict] = []


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "01", "true", "on", "yes", "ja", "an"):
        return True
    if text in ("0", "00", "false", "off", "no", "nein", "aus"):
        return False
    raise PlanError(f"Ungültiger Wahrheitswert: {value!r}")


def encode_partition_ids(zone_ids: list[int]) -> str:
    """Zonen-IDs als aneinandergereihte little-endian uint16, z. B. 1 -> "0100"."""
    return "".join(f"{z & 0xFF:02x}{(z >> 8) & 0xFF:02x}" for z in zone_ids)


def mow_setup(*, reset: bool, ordered: bool) -> int:
    """partitionSetup: hoch 1 = fortsetzen, 2 = neu beginnen; niedrig 1 = Mäher-Route, 2 = unsere Reihenfolge."""
    return (0x20 if reset else 0x10) | (0x02 if ordered else 0x01)


def parse_zone_ids(value: Any) -> list[int]:
    if value is None or value == "":
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).replace(";", ",").split(",")
    out: list[int] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        number = _as_int(text)
        if number is None:
            raise PlanError(f"Ungültige Zonen-ID: {text!r}")
        out.append(number)
    return out


def check_zones(zone_ids: list[int], known_ids: list[int]) -> None:
    """Unbekannte Zonen ablehnen -- aber nur, wenn die Karte überhaupt gelesen ist."""
    if not known_ids:
        return
    unknown = sorted(set(zone_ids) - set(known_ids))
    if unknown:
        raise PlanError(
            "Unbekannte Zone(n): " + ", ".join(map(str, unknown))
            + ". Der Mäher kennt: " + ", ".join(map(str, sorted(known_ids))) + "."
        )


def build_mow(payload: dict, known_ids: list[int]) -> tuple[str, int]:
    """(partitionIds-Hex, partitionSetup) für {"cmd": "mow", "zones": ..., "reset": ...}.

    Eine Zonenliste legt auch die Reihenfolge fest; ohne Liste werden alle
    bekannten Zonen gemäht und der Mäher wählt die Route selbst.
    """
    zones = parse_zone_ids(payload.get("zones"))
    ordered = bool(zones)
    check_zones(zones, known_ids)
    if not zones:
        zones = sorted(known_ids)
    if not zones:
        raise PlanError(
            "Noch keine Zonen bekannt. Der Gateway liest die Karte kurz nach dem Start; "
            "bitte kurz warten oder Zonen-IDs angeben."
        )
    reset = as_bool(payload.get("reset"), True)
    return encode_partition_ids(zones), mow_setup(reset=reset, ordered=ordered)


def valid_map_id(value: Any) -> bool:
    """Eine brauchbare Karten-ID: vorhanden und nicht die 0, die manche Mäher melden."""
    return value is not None and str(value).strip() not in ("", "0")


def pick_map_ids(location: Any, map_list: Any) -> tuple[str, str, str] | None:
    """(map_id, map_base_id, edit_time) aus get-location, sonst aus map-list."""
    loc = location if isinstance(location, dict) else {}
    if valid_map_id(loc.get("map_id")) and valid_map_id(loc.get("map_base_id")):
        return str(loc["map_id"]), str(loc["map_base_id"]), str(loc.get("map_edit_time") or "")
    for item in map_list if isinstance(map_list, list) else []:
        if isinstance(item, dict) and valid_map_id(item.get("map_id")) and valid_map_id(item.get("map_base_id")):
            return str(item["map_id"]), str(item["map_base_id"]), str(item.get("edittime") or "")
    return None


def extract_zones(map_detail: Any) -> list[dict]:
    """Zonen aus der unkomprimierten map-detail-Antwort (Feld map_detail ist ein JSON-String)."""
    data = map_detail
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (TypeError, ValueError):
            return []
    if not isinstance(data, dict):
        return []
    geom = data.get("map_detail")
    if isinstance(geom, str):
        try:
            geom = json.loads(geom)
        except (TypeError, ValueError):
            return []
    if not isinstance(geom, dict):
        return []
    zones = []
    for sub in geom.get("sub_maps") or []:
        if not isinstance(sub, dict):
            continue
        zid = _as_int(sub.get("id"))
        if zid is None:
            continue
        zones.append({"id": zid, "name": str(sub.get("name") or f"Zone {zid}"), "area": _as_float(sub.get("area"))})
    return sorted(zones, key=lambda z: z["id"])


def zones_payload(zones: list[dict]) -> dict:
    return {
        "count": len(zones),
        "ids": ",".join(str(z["id"]) for z in zones),
        "text": ", ".join(f"{z['id']} {z['name']}" for z in zones),
        "list": zones,
    }

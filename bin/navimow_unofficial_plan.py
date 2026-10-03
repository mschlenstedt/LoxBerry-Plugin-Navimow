"""Zonen, Mähbefehl und Wochenplan der inoffiziellen Navimow-API.

Reine Funktionen ohne I/O. Byte-Formate und Semantik aus ilguala/navimow_pro
(const.py, api/client.py, services.py, coordinator.py), dort live verifiziert.
"""
from __future__ import annotations

import json
import math
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
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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
    seen: set[int] = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        number = _as_int(text)
        if number is None:
            raise PlanError(f"Ungültige Zonen-ID: {text!r}")
        if not 1 <= number <= 65535:
            raise PlanError(f"Ungültige Zonen-ID: {text!r} (erlaubt 1 bis 65535)")
        if number in seen:
            raise PlanError(f"Zone {number} ist doppelt angegeben")
        seen.add(number)
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


_DAY_ALIASES = {
    "sonntag": "sunday", "montag": "monday", "dienstag": "tuesday", "mittwoch": "wednesday",
    "donnerstag": "thursday", "freitag": "friday", "samstag": "saturday",
    "so": "sunday", "mo": "monday", "di": "tuesday", "mi": "wednesday",
    "do": "thursday", "fr": "friday", "sa": "saturday",
    "sun": "sunday", "mon": "monday", "tue": "tuesday", "wed": "wednesday",
    "thu": "thursday", "fri": "friday", "sat": "saturday",
}


def parse_day(value: Any) -> int:
    text = str(value or "").strip().lower()
    name = _DAY_ALIASES.get(text, text)
    if name not in WEEKDAYS:
        raise PlanError(f"Unbekannter Wochentag: {value!r} (z. B. monday oder montag)")
    return WEEKDAYS.index(name) + 1


def hhmm_to_slot(value: Any, end: bool = False) -> int:
    """'HH:MM' -> 15-Minuten-Slot. Zeiten außerhalb des Rasters würden sonst still abgerundet.

    Als Ende gilt Mitternacht (24:00 oder 00:00) als Tagesende, Slot 96.
    """
    parts = str(value or "").strip().split(":")
    hours = _as_int(parts[0]) if parts and parts[0] else None
    minutes = _as_int(parts[1]) if len(parts) > 1 else 0
    if end and hours in (0, 24) and minutes == 0:
        return 24 * 60 // SLOT_MINUTES
    if hours is None or minutes is None or not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise PlanError(f"Ungültige Uhrzeit {value!r} (Format HH:MM)")
    if minutes % SLOT_MINUTES:
        raise PlanError(
            f"Ungültige Uhrzeit {value!r}: der Mäher plant in 15-Minuten-Schritten, "
            "Minuten nur 00, 15, 30 oder 45"
        )
    return (hours * 60 + minutes) // SLOT_MINUTES


def slot_to_hhmm(slot: int) -> str:
    minutes = int(slot) * SLOT_MINUTES
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def build_schedule(payload: dict, known_ids: list[int],
                   current_day: dict | None = None) -> tuple[int, bool, list[dict]]:
    """(Tag 1-7, an/aus, Perioden in Slots) für {"cmd": "schedule", "day", "enabled", "periods"}.

    Fehlt "periods", bleiben die Zeitfenster aus current_day (Eintrag dieses Wochentags aus
    parse_schedule) erhalten; ein ausdrücklich leeres "periods": [] löscht sie.
    """
    day = parse_day(payload.get("day"))
    enabled = as_bool(payload.get("enabled"), True)
    if "periods" in payload:
        raw = payload.get("periods") or []
    elif current_day is None:
        raise PlanError("Der aktuelle Plan ist noch nicht gelesen. Bitte periods mitschicken.")
    else:
        raw = [{"start": p["start"], "end": p["end"], "zones": p.get("zones") or []}
               for p in current_day.get("periods") or []]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise PlanError("periods ist kein gültiges JSON") from None
    if not isinstance(raw, list):
        raise PlanError("periods muss eine Liste sein")
    periods = []
    for item in raw:
        if not isinstance(item, dict):
            raise PlanError("Jedes Zeitfenster braucht start und end")
        start, end = hhmm_to_slot(item.get("start")), hhmm_to_slot(item.get("end"), end=True)
        if end <= start:
            raise PlanError(
                f"Zeitfenster {slot_to_hhmm(start)}–{slot_to_hhmm(end)}: das Ende muss nach dem Beginn liegen"
            )
        zones = parse_zone_ids(item.get("zones"))
        if zones and not known_ids:
            raise PlanError(
                "Die Karte ist noch nicht gelesen – Zeitfenster mit Zonen sind erst danach möglich. "
                "Ohne zones gilt das Fenster für alle Zonen."
            )
        check_zones(zones, known_ids)
        periods.append({"start_time": start, "end_time": end, "partition_ids": zones})
    periods.sort(key=lambda p: p["start_time"])
    for first, second in zip(periods, periods[1:]) if enabled else ():
        if second["start_time"] < first["end_time"]:
            raise PlanError(
                f"Zeitfenster überlappen: {slot_to_hhmm(first['start_time'])}–{slot_to_hhmm(first['end_time'])} "
                f"und {slot_to_hhmm(second['start_time'])}–{slot_to_hhmm(second['end_time'])}"
            )
    return day, enabled, periods


def partition_plan_hex(day: int, enabled: bool, periods: list[dict]) -> str:
    """Tagesplan für den s:mower-Gerätebefehl.

    01 <Tag> <an> <Anzahl Perioden> [<Start> <Ende> <Anzahl Zonen> <Zonen-ID>...]...
    Einzelbytes außer den Zonen-IDs (little-endian uint16). Eine Zonen-ID als ein
    Byte verschiebt alle folgenden Bytes, der Mäher liest das als zusätzliche
    Phantom-Periode, die sich in der App nicht mehr löschen lässt.
    """
    out = ["%02X" % (x & 0xFF) for x in (1, int(day), 1 if enabled else 0, len(periods))]
    for period in periods:
        ids = [int(z) for z in (period.get("partition_ids") or [])]
        out.append("%02X%02X%02X" % (int(period["start_time"]) & 0xFF, int(period["end_time"]) & 0xFF, len(ids)))
        out.append(encode_partition_ids(ids).upper())
    return "".join(out)


def _schedule_source(set_list: Any) -> Any:
    """Der gültige Plan steht in workPlanV2/plan_v2; das alte Feld plan bleibt eingefroren."""
    if not isinstance(set_list, dict):
        return None
    if "plan_v2" in set_list and set_list["plan_v2"] is not None:
        return set_list["plan_v2"]
    if "workPlanV2" in set_list and set_list["workPlanV2"] is not None:
        return set_list["workPlanV2"]
    return set_list.get("plan")


def parse_schedule(set_list: Any, zone_names: dict) -> dict:
    out = {day: {"enabled": False, "periods": [], "text": "aus"} for day in WEEKDAYS}
    source = _schedule_source(set_list)
    for entry in source if isinstance(source, list) else []:
        if not isinstance(entry, dict):
            continue
        day = _as_int(entry.get("day"))
        if day is None or not 1 <= day <= 7:
            continue
        periods = []
        for item in entry.get("period") or []:
            if isinstance(item, dict):
                start, end, raw_ids = _as_int(item.get("start_time")), _as_int(item.get("end_time")), item.get("partition_ids") or []
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                start, end, raw_ids = _as_int(item[0]), _as_int(item[1]), []
            else:
                continue
            if start is None or end is None:
                continue
            if not isinstance(raw_ids, (list, tuple)):
                raw_ids = []
            ids = [z for z in (_as_int(x) for x in raw_ids) if z is not None]
            periods.append({"start": slot_to_hhmm(start), "end": slot_to_hhmm(end), "zones": ids})
        try:
            enabled = as_bool(entry.get("open"), False)
        except PlanError:
            enabled = False
        if not enabled:
            text = "aus"
        elif not periods:
            text = "an, ohne Zeitfenster"
        else:
            text = ", ".join(
                f"{p['start']}–{p['end']} "
                + (" + ".join(zone_names.get(z, f"Zone {z}") for z in p["zones"]) if p["zones"] else "alle Zonen")
                for p in periods
            )
        out[WEEKDAYS[day - 1]] = {"enabled": enabled, "periods": periods, "text": text}
    return out

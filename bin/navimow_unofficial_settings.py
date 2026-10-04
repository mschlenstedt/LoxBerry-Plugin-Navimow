"""Einstellungen des Mähers über die inoffizielle API: lesen, prüfen, kodieren.

Schlüssel, Lesefelder und Kodierung je Kanal aus ilguala/navimow_pro
(switch.py, number.py, select.py, coordinator.py, const.py) Stand 75fea65.
Reines Modul ohne I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class SettingError(ValueError):
    """Eine Einstellung lässt sich so nicht setzen; die Meldung geht an den Nutzer."""


@dataclass(frozen=True)
class Setting:
    name: str                 # Name im MQTT-Topic und im Befehl
    write_key: str            # Cloud-Schlüssel (save-set-data)
    read_keys: tuple          # Felder in set-list, in dieser Reihenfolge gesucht
    kind: str                 # "bool", "number" oder "select"
    iot: bool = True          # False: alter Weg, nur Cloud, Wert "01"/"00"
    cloud_numeric: bool = True
    robot_numeric: bool = True
    robot_key: str | None = None
    gate: str | None = None   # schreibbar, wenn diese (lesbare) Einstellung gemeldet ist
    minimum: int = 0
    maximum: int = 0
    step: int = 1
    scale: int = 1            # Draht = Wert × scale
    robot_hex: bool = True    # Zahl: Gerät als hex "%02X", sonst Dezimal-String
    cloud_hex: bool = False
    options: tuple = ()       # Auswahl: ((name, zahl, deutscher Text), ...)


def _b(name, key, read, **kw):
    return Setting(name, key, read, "bool", **kw)


SETTINGS: tuple[Setting, ...] = (
    _b("schedule_enabled", "startPlan", ("startPlan", "start_plan"), cloud_numeric=False, robot_numeric=False),
    _b("night_mow", "nightMowSwitch", ("night_mow_switch", "nightMowSwitch")),
    _b("rain_sensor", "rainSensor", ("rainSensor", "rain_sensor"), iot=False),
    _b("rain_detection", "rainDetectionSwitch", ("rainDetectionSwitch", "rain_detection_switch"), iot=False),
    _b("sound", "soundSwitch", ("soundSwitch", "sound_switch"), cloud_numeric=False),
    _b("power_saving", "lowPowerSet", ("lowPowerSet", "low_power_set")),
    _b("child_lock", "childLock", ("childLock", "child_lock"), cloud_numeric=False),
    _b("lift_alarm", "liftSwitch", ("liftSwitch", "lift_switch"), cloud_numeric=False),
    _b("mowing_cycle", "mowingCycle", ("mowingCycle", "mowing_cycle"), cloud_numeric=False, robot_numeric=False),
    _b("frost_delay", "frostSwitch", ("frostSwitch", "frost_switch")),
    _b("snow_delay", "snowSwitch", ("snowSwitch", "snow_switch")),
    _b("storm_delay", "stormSwitch", ("stormSwitch", "storm_switch")),
    _b("high_temp_delay", "highTempSwitch", ("highTempSwitch", "high_temp_switch")),
    _b("efls", "slamSwitch", ("slamSwitch", "slam_switch")),
    _b("obstacle_avoidance", "cptSwitch", ("cptSwitch", "cpt_switch")),
    _b("traction_control", "tractionControl", ("tractionControl", "traction_control"), robot_key="tcsSwitch"),
    _b("animal_protection", "animalProtection", ("animalProtection",), gate="obstacle_avoidance"),
    _b("night_light", "lightSwitch", ("lightSwitch",), gate="night_light_level"),
    _b("weather_rain", "weatherSwitch", ("weatherSwitch", "weather_switch")),
    _b("rain_delay_mode", "delayedPileSwitch", ("delayedPileSwitch", "delayed_pile_switch")),
    Setting("return_battery_level", "returnBatteryLevel", ("returnBatteryLevel",), "number",
            minimum=5, maximum=50, step=5),
    Setting("charging_limit", "chargingLimit", ("chargingLimit",), "number",
            minimum=50, maximum=100, step=5),
    Setting("rain_delay_hours", "delayedPileSet", ("delayedPileSet", "delayed_pile_set"), "number",
            minimum=1, maximum=12, step=1, scale=4, cloud_hex=True),
    Setting("cut_height_mm", "height", ("height",), "number",
            minimum=50, maximum=100, step=5, robot_hex=False),
    Setting("night_light_level", "nightLightLevel", ("nightLightLevel", "night_light_level"), "select",
            robot_numeric=False, options=(("dim", 0, "gedimmt"), ("very_dim", 1, "stark gedimmt"))),
    Setting("weather_sensitivity", "weatherSensitivity", ("weatherSensitivity", "weather_sensitivity"), "select",
            options=(("drizzle", 0, "Nieselregen"), ("light", 1, "leichter Regen"), ("moderate", 2, "mäßiger Regen"))),
)

BY_NAME: dict[str, Setting] = {s.name: s for s in SETTINGS}


def find(obj: Any, *keys: str) -> Any:
    """Erster Wert zu einem der Schlüssel, Tiefensuche wie navimow_pro._find."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys:
                return value
        for value in obj.values():
            found = find(value, *keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find(value, *keys)
            if found is not None:
                return found
    return None


def _read_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in ("1", "01", "true", "on", "yes"):
        return True
    if text in ("0", "00", "false", "off", "no", ""):
        return False
    return None


def _read_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _read_wire(value: Any) -> int | None:
    """delayedPileSet: set-list meldet dezimal, manche Wege hex."""
    if value is None:
        return None
    text = str(value).strip()
    for base in (10, 16):
        try:
            return int(text, base)
        except ValueError:
            continue
    return None


def parse_settings(set_list: Any) -> dict:
    out: dict = {}
    for s in SETTINGS:
        raw = find(set_list, *s.read_keys)
        if s.kind == "bool":
            value = _read_bool(raw)
        elif s.kind == "select":
            number = _read_int(raw)
            value = next((name for name, num, _ in s.options if num == number), None)
        elif s.scale != 1:
            wire = _read_wire(raw)
            value = None if wire is None else (wire // s.scale if wire % s.scale == 0 else wire / s.scale)
        else:
            value = _read_int(raw)
        if value is not None:
            out[s.name] = value
    return out


def settings_payload(settings: dict) -> dict:
    out: dict = {}
    for name, value in settings.items():
        s = BY_NAME[name]
        if s.kind == "bool":
            out[name] = 1 if value else 0
        elif s.kind == "select":
            option = next(o for o in s.options if o[0] == value)
            out[name] = option[1]
            out[f"{name}_text"] = option[2]
        else:
            out[name] = value
    return out


# Was eine Modellfamilie trotz gemeldetem Feld nachweislich nicht hat
# (navimow_pro const.FAMILY_LACKS, jeweils im Feld bestätigt). Präfix des Modellnamens.
FAMILY_LACKS = (
    ("I1", frozenset({"cut_height_mm"})),     # i105/i108/i110: Schnitthöhe per Drehknopf am Gerät
    ("X3", frozenset({"charging_limit"})),    # X315…X390: die App bietet keine Ladegrenze an
)


def model_lacks(model: Any, name: str) -> bool:
    text = str(model or "").strip().upper()
    return any(text.startswith(prefix) and name in names for prefix, names in FAMILY_LACKS)


def parse_device(device_info: Any, model: str = "") -> dict:
    """Fähigkeiten, die der Mäher selbst in get-device-info meldet."""
    heights = find(device_info, "mowingHeightList")
    options = sorted({v for v in (_read_int(h) for h in heights) if v is not None}) if isinstance(heights, list) else []
    limits: dict = {}
    for name, lo_key, hi_key in (("return_battery_level", "returnBatteryLevelMin", "returnBatteryLevelMax"),
                                 ("charging_limit", "chargingLimitMin", "chargingLimitMax")):
        lo, hi = _read_int(find(device_info, lo_key)), _read_int(find(device_info, hi_key))
        if lo is not None and hi is not None and lo < hi:   # halbe Bereiche wären schlechter als der feste
            limits[name] = (lo, hi)
    return {
        "model": str(model or find(device_info, "model") or "").strip(),
        "cut_height_options": options,
        "cut_height_flag": _read_int(find(device_info, "isCutterHeight")) == 1,
        "limits": limits,
    }


def cut_height_writable(device: dict | None) -> bool:
    """Wie navimow_pro.cut_height_control: Motor-Flag oder mindestens zwei gemeldete Stufen, nicht bei I1."""
    if not device or model_lacks(device.get("model"), "cut_height_mm"):
        return False
    return bool(device.get("cut_height_flag")) or len(device.get("cut_height_options") or []) >= 2


def device_payload(device: dict) -> dict:
    return {
        "cut_height_writable": 1 if cut_height_writable(device) else 0,
        "cut_height_options": ",".join(str(h) for h in device.get("cut_height_options") or []),
    }


@dataclass(frozen=True)
class SettingWrite:
    name: str
    robot: dict | None   # Gerätebefehl (s:mower); None = alter Weg, nur Cloud
    cloud: dict          # save-set-data data
    iot: bool


def _value_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower() if value is not None else ""
    if text in ("1", "true", "on", "an", "ja", "yes"):
        return True
    if text in ("0", "false", "off", "aus", "nein", "no"):
        return False
    raise SettingError(f"Ungültiger Wert {value!r}: erlaubt sind 1/0, an/aus, true/false")


def _value_number(value: Any, name: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SettingError(f"Ungültiger Wert {value!r} für {name}: eine Zahl wird erwartet") from None
    if number != int(number):
        raise SettingError(f"Ungültiger Wert {value!r} für {name}: eine ganze Zahl wird erwartet")
    return int(number)


def build_setting(payload: dict, current: dict | None, device: dict | None = None) -> SettingWrite:
    """Prüft {"cmd": "setting", "key": ..., "value": ...} und kodiert ihn für Mäher und Cloud."""
    name = str(payload.get("key") or "").strip().lower()
    s = BY_NAME.get(name)
    if s is None:
        raise SettingError(f"Unbekannte Einstellung: {name!r}. Möglich sind: {', '.join(BY_NAME)}")
    if not current:
        raise SettingError("Die Einstellungen sind noch nicht gelesen. Bitte kurz nach dem Gateway-Start erneut senden.")
    reported = current.get(name) is not None or (s.gate is not None and current.get(s.gate) is not None)
    if not reported:
        raise SettingError(f"{name} meldet dieser Mäher nicht, daher wird sie nicht gesetzt")
    if device and name != "cut_height_mm" and model_lacks(device.get("model"), name):   # Schnitthöhe: eigene Meldung unten
        raise SettingError(f"{name} hat dieses Modell nicht")
    value = payload.get("value")
    robot_key = s.robot_key or s.write_key

    if s.kind == "bool":
        on = _value_bool(value)
        if not s.iot:
            return SettingWrite(name, None, {s.write_key: "01" if on else "00"}, False)
        robot = (1 if on else 0) if s.robot_numeric else ("1" if on else "0")
        cloud = (1 if on else 0) if s.cloud_numeric else ("1" if on else "0")
        return SettingWrite(name, {robot_key: robot}, {s.write_key: cloud}, True)

    if s.kind == "select":
        text = str(value).strip().lower() if value is not None else ""
        number = next((num for opt, num, label in s.options if text in (opt, str(num), label.lower())), None)
        if number is None:
            names = ", ".join(f"{opt} ({num})" for opt, num, _ in s.options)
            raise SettingError(f"Ungültiger Wert {value!r} für {name}: erlaubt sind {names}")
        robot = number if s.robot_numeric else f"{number:02d}"
        return SettingWrite(name, {robot_key: robot}, {s.write_key: number}, True)

    number = _value_number(value, name)
    if name == "cut_height_mm":
        if device is None:
            raise SettingError("Die Gerätedaten sind noch nicht gelesen. Bitte kurz nach dem Gateway-Start erneut senden.")
        if not cut_height_writable(device):
            raise SettingError("Die Schnitthöhe lässt sich bei diesem Mäher nicht per Befehl setzen (z. B. Drehknopf am Gerät)")
        options = device.get("cut_height_options") or []
        if options and number not in options:
            raise SettingError(f"cut_height_mm: erlaubt sind {', '.join(map(str, options))} mm")
    if name != "cut_height_mm" or not (device or {}).get("cut_height_options"):
        lo, hi = (device or {}).get("limits", {}).get(name, (s.minimum, s.maximum))
        if not lo <= number <= hi or (number - lo) % s.step:
            raise SettingError(f"{name}: erlaubt sind {lo} bis {hi} in Schritten von {s.step}")
    wire = number * s.scale
    robot = f"{wire:02X}" if s.robot_hex else str(wire)
    cloud = f"{wire:02X}" if s.cloud_hex else wire
    return SettingWrite(name, {robot_key: robot}, {s.write_key: cloud}, True)

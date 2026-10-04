"""Zustand und Fehlercode des Mähers im Klartext (inoffizielle API).

Codes und Bedeutungen nach ilguala/navimow_pro const.ERROR_CODES (dort eigene
englische Kurzbeschreibungen), hier eigene deutsche Texte. Wo genau der Code in
der Antwort steht, ist nicht dokumentiert und in navimow_pro nie mit einem
echten Fehler beobachtet: deshalb wird die Antwort nach allem durchsucht, was
wie ein Code aussieht, und ein unbekannter Code bleibt als Nummer sichtbar.
"""
from __future__ import annotations

import re
from typing import Any

from navimow_unofficial_settings import find

# Zustandscode: erstes Byte Familie (01 Station, 02 unterwegs, 03 gestoppt mit Fehler).
KNOWN_STATES = frozenset({"0101", "0102", "0210", "0211", "0220"})
STATE_TEXT = {
    "0101": "In der Station", "0102": "In der Station (fertig)", "0210": "Mäht",
    "0211": "Pausiert", "0220": "Fährt zur Station",
}
FAMILY_TEXT = {"01": "In der Station", "02": "Unterwegs", "03": "Gestoppt (Fehler)"}
FAULT_FAMILY = "03"
RESUME_HINT = "am Mäher STOP drücken, danach MOW und OK zum Fortsetzen"

ERROR_CODES = {
    "1001": "Messermotor startet nicht", "1002": "Überspannung am Messermotor",
    "1003": "Unterspannung am Messermotor", "1004": "Überstrom am Messermotor",
    "1005": "Messermotor blockiert – Messerteller auf Fremdkörper prüfen",
    "1008": "Höhenverstellung blockiert", "1009": "Überstrom an der Höhenverstellung",
    "1010": "Selbsttest der Steuerung fehlgeschlagen", "1018": "Steuerung der Höhenverstellung gestört",
    "1020": "Akku: Überspannung", "1021": "Akku: Unterspannung", "1022": "Akku: Entladeschutz aktiv",
    "1023": "Akku: Ladeschutz aktiv", "1024": "Akku zu heiß", "1025": "Akku zu kalt",
    "2010": "Selbsttest der Sensoren fehlgeschlagen",
    "3001": "Radmotor blockiert – Räder auf Fremdkörper prüfen", "3002": "Radmotor überdreht",
    "3003": "Lagesensor (IMU) driftet", "3004": "Kalibrierfehler am Radmotor",
    "3005": "Kurzschluss am Radmotor", "3006": "Kalibrierung des Radmotors beschädigt",
    "3007": "Radmotor antwortet nicht", "3008": "Radmotor überhitzt",
    "3010": "Selbsttest des Antriebs fehlgeschlagen",
    "4001": "Speicherfehler", "4003": "Steuerelektronik überhitzt", "4004": "Antriebselektronik überhitzt",
    "4007": "Bluetooth-Verbindung gestört", "4008": "Cloud-Verbindung gestört",
    "4010": "Messermotor antwortet nicht", "4011": "Ladestation antwortet nicht",
    "4012": "Sensoren antworten nicht", "4013": "Ultraschallmodul antwortet nicht",
    "4014": "Ladestation antwortet nicht", "4020": "Selbsttest der Elektronik fehlgeschlagen",
    "5001": "Antenne der Ladestation gestört", "5002": "Leitdraht der Ladestation gestört",
    "5003": "Ladestation: Überstrom oder Überspannung",
    "6002": "Mäher steht außerhalb der Begrenzung", "6003": "Mäher ist umgekippt",
    "6004": "Findet den Weg zur Ladestation nicht", "6005": "Findet den Weg zur Ladestation nicht",
    "6006": "Stoßsensor dauerhaft ausgelöst", "6007": "Mäher wurde angehoben",
    "6008": "Stoßsensor zu oft ausgelöst",
    "6010": "Kann keine Route planen – auf ebenen Boden innerhalb der Begrenzung stellen",
    "6011": "Mäher steckt fest – bitte befreien",
    "6012": "Ladestation oder Antenne seit dem Kartieren verschoben",
    "6014": "Mäher steht außerhalb der Begrenzung – bitte zurückstellen",
    "6015": "Mäher hängt an einem Hindernis – befreien und auf ebenen Boden stellen",
    "6016": "Mäher hängt an einem Hindernis – befreien und auf ebenen Boden stellen",
    "6017": "Mäher hängt an einem Hindernis – befreien und auf ebenen Boden stellen",
    "6018": "Kann keine Route planen – auf ebenen Boden innerhalb der Begrenzung stellen",
    "6020": "Mäher konnte nicht starten", "6021": "Mäher hat sein Ziel nicht erreicht",
    "6022": "Mäher kommt nicht durch den Verbindungsweg", "6023": "Mäher kommt nicht durch",
    "7001": "Daten des Lagesensors fehlerhaft", "7002": "Version des Antriebs nicht lesbar",
    "7003": "GPS-Daten fehlerhaft", "7004": "Kompassdaten fehlerhaft",
    "7005": "Positionsdaten gestört", "7006": "Konnte seine Position nicht wiederfinden",
    "8001": "VisionFence-Kamera antwortet nicht", "8002": "VisionFence-Karte fehlerhaft",
    "8003": "Kamera verschmutzt – Linse reinigen", "8005": "VisionFence-Kamera getrennt",
    "8006": "Systemfehler der VisionFence-Kamera",
}

_CODE_KEY = re.compile(r"(?i)(error|fault|hint)?_?code")


def state_code(index2: Any) -> str:
    if not isinstance(index2, dict):
        return ""
    return str(index2.get("vehicle_state") or index2.get("vehicleState") or "").strip()


def _inline_errors(index2: Any) -> Any:
    if not isinstance(index2, dict):
        return None
    return index2.get("error_data") or find(index2, "errorData", "error_list")


def needs_fault_detail(index2: Any) -> bool:
    """Fehlerdetails nur abfragen, wenn index2 Fehlerdaten oder einen unbekannten Zustand meldet."""
    code = state_code(index2)
    return bool(_inline_errors(index2)) or bool(code and code not in KNOWN_STATES)


def collect_codes(obj: Any, out: list, depth: int = 0) -> None:
    """Alles einsammeln, was wie ein Fehlercode aussieht (Schlüssel code/errorCode/hint_code …)."""
    if depth > 6 or obj is None:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (str, int)) and not isinstance(value, bool) and _CODE_KEY.fullmatch(str(key)):
                code = str(value).strip()
                if code and code not in out:
                    out.append(code)
            else:
                collect_codes(value, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            collect_codes(item, out, depth + 1)


def parse_fault(index2: Any, errors: Any) -> dict:
    code = state_code(index2)
    codes: list = []
    collect_codes(errors, codes)
    if not codes:
        collect_codes(_inline_errors(index2), codes)
    active = bool(codes) or code[:2] == FAULT_FAMILY
    if codes:
        text = "; ".join(ERROR_CODES.get(c, f"Fehler {c}") for c in codes[:3])
        if any(c in ERROR_CODES for c in codes):
            text = f"{text} ({RESUME_HINT})"
    elif active:
        text = "Gestoppt mit Fehler, der Mäher nennt keinen Code"
    else:
        text = ""
    return {"active": active, "codes": codes, "text": text, "state_code": code,
            "state_text": STATE_TEXT.get(code) or FAMILY_TEXT.get(code[:2], "")}


def fault_payload(fault: dict) -> dict:
    return {"active": 1 if fault["active"] else 0, "codes": ",".join(fault["codes"]), "text": fault["text"],
            "state_code": fault["state_code"], "state_text": fault["state_text"]}

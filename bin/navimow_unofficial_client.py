"""Authentifizierter Call-Wrapper für die inoffizielle Navimow-Cloud (async, aiohttp).

Port aus ilguala/navimow_pro (api/client.py), auf aiohttp statt http.client
umgestellt und auf den Phase-1-Befehlsumfang (Pause/Dock/Resume + Geräteliste)
beschränkt. Weitere Calls (Zonen, Zeitplan, Settings) kommen in späteren
Phasen dazu, ohne dass sich diese Struktur ändert -- neue Methoden auf
NavimowUnofficialClient, alle über dieselbe call()/_raw()-Kette.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import aiohttp

import navimow_unofficial_crypto as crypto
import navimow_unofficial_plan as plan
from navimow_unofficial_auth import Tokens

_HEADERS = {
    "Content-Type": "text/html",
    "ninebot-version": "1",
    # Byte-identisch mit dem, was der geprüft funktionierende Referenzclient
    # sendet -- der Server erwartet exakt diesen Wert; dass wir aiohttp statt
    # urllib benutzen, ändert daran nichts.
    "User-Agent": "Python-urllib/3.13",
}

CODE_OK = 1
AUTH_ERROR_CODES = {90015, 90016, 401900, 401901, 401902, 401903, 401905, 1005}
_AUTH_CODE_FAMILY = "4019"


def is_auth_error(code: Any) -> bool:
    if code in AUTH_ERROR_CODES:
        return True
    text = str(code)
    return len(text) == 6 and text.startswith(_AUTH_CODE_FAMILY) and text.isdigit()


class NavimowError(Exception):
    def __init__(self, code: Any, desc: str = "") -> None:
        super().__init__(f"{code}: {desc}")
        self.code = code
        self.desc = desc


class NavimowAuthError(NavimowError):
    """Auth-/Session-Problem (Token abgelaufen, falsche uid, andernorts angemeldet)."""


class NavimowUnofficialClient:
    """Eine Kontositzung gegen die inoffizielle Navimow-Cloud für ein Gerät."""

    def __init__(self, session, client_device_id: str, *, tokens: Tokens, uid: str = "",
                 region: str = "fra", language: str = "en", host: str) -> None:
        self._session = session
        self._client_device_id = client_device_id
        self._tokens = tokens
        self._uid = uid
        self._region = region
        self._language = language
        self._host = host

    @property
    def tokens(self) -> Tokens:
        return self._tokens

    @property
    def uid(self) -> str:
        return self._uid

    def _common_params(self, access_token: str = "") -> dict:
        return {
            "manufacturer": "samsung_samsung_SM-G930F",
            "systemVersion": "13",
            "platform": "and",
            "uid": self._uid,
            "device_id": self._client_device_id,
            "client_ver": "402000003",
            "language": self._language,
            "access_token": access_token,
        }

    @staticmethod
    def _add_checkcode(body: dict) -> dict:
        b = dict(body)
        b["serviceTime"] = int(time.time() * 1000)
        b["nonce"] = hashlib.sha256(os.urandom(16)).hexdigest()[:32]
        b["checkcode"] = (
            hashlib.md5(json.dumps(b, separators=(",", ":")).encode()).hexdigest().upper()
        )
        return b

    async def _post(self, path: str, envelope: dict) -> dict:
        url = f"https://{self._host}{path}"
        async with self._session.post(
            url, json=envelope, headers=_HEADERS,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            return await resp.json(content_type=None)

    async def _raw(self, path: str, business: dict) -> dict:
        return crypto.decode_response(await self._post(path, crypto.pack(business)))

    async def mower_login(self) -> str:
        """POST /user/user/login -- registriert dieses Gerät, liefert die uid.

        Versucht zuerst ohne Checkcode-Signatur (bewährt funktionierend);
        fällt bei Ablehnung auf die signierte Variante zurück.
        """
        field4 = {
            "uuid": self._tokens.uuid,
            "token": self._tokens.access_token,
            "refresh_token": self._tokens.refresh_token,
            "region": self._tokens.region or self._region,
        }
        body_a = {**field4, **self._common_params(access_token="")}
        result = await self._raw("/user/user/login", body_a)
        uid = self._extract_uid(result)
        if not uid:
            body_b = self._add_checkcode({**field4, **self._common_params(access_token="")})
            result = await self._raw("/user/user/login", body_b)
            uid = self._extract_uid(result)
        if not uid:
            code = result.get("code") if isinstance(result, dict) else None
            desc = str(result.get("desc", "")) if isinstance(result, dict) else str(result)
            raise NavimowAuthError(code, f"mower login returned no uid: {desc}")
        self._uid = str(uid)
        return self._uid

    @staticmethod
    def _extract_uid(result: Any):
        if isinstance(result, dict) and isinstance(result.get("data"), dict):
            uid = result["data"].get("uid")
            return str(uid) if uid else None
        return None

    async def call(self, path: str, extra: dict | None = None, *, auth: bool = True) -> Any:
        """Verschlüsselter Call, liefert die ``data``-Payload bei Erfolg.

        Bei Auth-/Ablauf-Code wird einmal neu angemeldet und wiederholt.
        """
        if auth and not self._uid:
            await self.mower_login()
        body = self._common_params(access_token=self._tokens.access_token)
        if extra:
            body.update(extra)
        result = await self._raw(path, body)
        code = result.get("code") if isinstance(result, dict) else None
        if code == CODE_OK:
            return result.get("data")

        if auth and is_auth_error(code):
            await self.mower_login()
            body = self._common_params(access_token=self._tokens.access_token)
            if extra:
                body.update(extra)
            result = await self._raw(path, body)
            code = result.get("code") if isinstance(result, dict) else None
            if code == CODE_OK:
                return result.get("data")

        desc = str(result.get("desc", "")) if isinstance(result, dict) else str(result)
        if is_auth_error(code):
            raise NavimowAuthError(code, desc)
        raise NavimowError(code, desc)

    async def auth_list(self) -> list:
        """Geräte auf diesem Account. Lernt die uid, falls noch nicht gesetzt."""
        data = await self.call("/vehicle/vehicle/auth-list", {})
        items = data if isinstance(data, list) else (data or {}).get("list") or []
        if items and not self._uid:
            uid = items[0].get("auth_uid")
            if uid:
                self._uid = str(uid)
        return items

    async def _behavior(self, sn: str, type_int: int) -> dict:
        # Erprobt: SOWOHL der String-Typ auf oberster Ebene ALS AUCH der
        # verschachtelte Int-Typ in data werden verlangt.
        return await self.call(
            "/vehicle/set/send",
            {"vehicle_sn": sn, "cmdCode": "c:behavior", "type": str(type_int),
             "data": {"type": type_int}},
        )

    async def pause(self, sn: str) -> dict:
        return await self._behavior(sn, 1)

    async def dock(self, sn: str) -> dict:
        return await self._behavior(sn, 2)

    async def resume(self, sn: str) -> dict:
        return await self._behavior(sn, 3)

    async def location(self, sn: str, vehicle_type: int) -> dict:
        return await self.call("/vehicle/vehicle/get-location",
                               {"vehicle_sn": sn, "vehicle_type": vehicle_type}) or {}

    async def map_list(self, sn: str) -> Any:
        return await self.call("/map/index/map-list", {"vehicle_sn": sn})

    async def map_detail(self, sn: str, map_id: str, map_base_id: str) -> Any:
        """Unkomprimierte Kartendaten: map_detail ist ein JSON-String, kein zstd nötig."""
        return await self.call("/map/index/map-detail",
                               {"vehicle_sn": sn, "map_id": map_id, "map_base_id": map_base_id})

    async def set_list(self, sn: str) -> dict:
        return await self.call("/vehicle/vehicle/set-list", {"vehicle_sn": sn}) or {}

    async def mow_zones(self, sn: str, partition_ids_hex: str, partition_setup: int) -> Any:
        return await self.call(
            "/vehicle/set/send",
            {"vehicle_sn": sn, "cmdCode": "s:mower",
             "data": {"partitionSetup": partition_setup, "partitionIds": partition_ids_hex}},
        )

    async def set_day_schedule(self, sn: str, vehicle_type: int, day: int, enabled: bool,
                               periods: list[dict]) -> Any:
        """Einen Wochentag schreiben, wie die App: erst an den Mäher, dann die Cloud-Kopie.

        Mäht der Mäher gerade, lehnt er den Gerätebefehl ab (5001); dann wird die
        Cloud-Kopie gar nicht erst geschrieben, sonst zeigt die App einen Plan,
        den der Mäher nicht hat.
        """
        key = f"partitionPlan{int(day) - 1}"
        await self.call(
            "/vehicle/set/send",
            {"vehicle_sn": sn, "cmdCode": "s:mower",
             "data": json.dumps({key: plan.partition_plan_hex(day, enabled, periods)}, separators=(",", ":"))},
        )
        try:
            return await self.call(
                "/vehicle/set/save-set-data",
                {"vehicle_sn": sn, "vehicle_type": str(vehicle_type),
                 "data": {key: {"day": int(day), "open": 1 if enabled else 0, "period": periods}},
                 "operation_type": "iot_set"},
            )
        except NavimowError as err:
            raise NavimowError(
                err.code,
                "Mäher hat den Plan übernommen, die Cloud-Kopie ist fehlgeschlagen – bitte erneut senden ("
                + str(getattr(err, "desc", "") or err) + ")",
            ) from err

    async def device_info(self, sn: str) -> dict:
        return await self.call("/vehicle/vehicle/get-device-info", {"vehicle_sn": sn}) or {}

    async def index2(self, sn: str) -> dict:
        return await self.call("/vehicle/vehicle/index2", {"vehicle_sn": sn}) or {}

    async def errors(self, sn: str, vehicle_type: int) -> Any:
        return await self.call("/vehicle/vehicle/get-hint-error-compress",
                               {"vehicle_sn": sn, "vehicle_type": vehicle_type}) or {}

    async def send_setting_device(self, sn: str, data: dict) -> Any:
        """Gerätebefehl: erst er lässt den Mäher eine Einstellung übernehmen (die Cloud-Kopie allein wird zurückgesetzt)."""
        return await self.call(
            "/vehicle/set/send",
            {"vehicle_sn": sn, "cmdCode": "s:mower", "data": json.dumps(data, separators=(",", ":"))},
        )

    async def save_setting(self, sn: str, vehicle_type: int, data: dict, *, iot: bool) -> Any:
        extra: dict = {"vehicle_sn": sn, "data": data}
        if iot:
            extra["vehicle_type"] = str(vehicle_type)
            extra["operation_type"] = "iot_set"
        return await self.call("/vehicle/set/save-set-data", extra)

    async def write_setting(self, sn: str, vehicle_type: int, write: Any) -> Any:
        """Wie die App: Gerät zuerst, dann Cloud-Kopie. Lehnt der Mäher ab, bleibt die Cloud unberührt."""
        if write.robot is not None:
            await self.send_setting_device(sn, write.robot)
        try:
            return await self.save_setting(sn, vehicle_type, write.cloud, iot=write.iot)
        except NavimowError as err:
            if write.robot is None:
                raise
            raise NavimowError(
                err.code,
                f"Mäher hat die Einstellung übernommen, die Cloud-Kopie ist fehlgeschlagen – bitte erneut senden ({err.desc})",
            ) from err

    async def path_info_time(self, sn: str) -> list:
        """Abdeckung je Zone für den laufenden bzw. letzten Mähauftrag (auch in der Station gefüllt)."""
        data = await self.call("/vehicle/trail/get-path-info-time", {"vehicle_sn": sn})
        return data if isinstance(data, list) else []

"""Segway/Ninebot-Passport-Login für die inoffizielle Navimow-Cloud (async, aiohttp).

Port aus ilguala/navimow_pro (api/passport.py), von urllib (synchron) auf
aiohttp umgestellt, damit derselbe ClientSession-Pool wie beim offiziellen
REST-Pfad genutzt wird (kein zweiter TLS-Verbindungsaufbau je Login).
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass

import aiohttp

from navimow_unofficial_const import (
    ALL_PASSPORT_HOSTS,
    DEFAULT_REGION,
    canonical_region,
    passport_hosts,
)

CLIENT_ID = "mowerbot_app_prod"
CLIENT_KEY = "830247f0-da96-5c21-8cf0-ca09299795f9"  # app-weit, nur im Sign, nicht im Header
APP_VERSION = "402000003"
OS_NAME = "Android"
OS_VERSION = "13"
OS_LANGUAGE = "en"
DEVICE = "ANDROID"

_RESULT_OK = "90000"
RESULT_ACCOUNT_NOT_EXISTS = "00002"


class PassportError(Exception):
    def __init__(self, code, desc: str = "") -> None:
        super().__init__(f"{code}: {desc}")
        self.code = str(code)
        self.desc = desc


class PassportAuthError(PassportError):
    """Falsche Zugangsdaten oder abgelaufene Session -- Neuanmeldung nötig."""


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    uuid: str = ""
    region: str = "fra"


def _sign(m: dict) -> str:
    return hashlib.sha256(
        "&".join(f"{k}={m[k]}" for k in sorted(m)).encode("utf-8")
    ).hexdigest()


def _signed_headers(url: str, req_params: dict) -> dict:
    ts = str(int(time.time() * 1000))
    sign_map = {
        "app_version": APP_VERSION,
        "clientKey": CLIENT_KEY,
        "os": OS_NAME,
        "os_language": OS_LANGUAGE,
        "os_version": OS_VERSION,
        "timestamp": ts,
        "url": url,
    }
    sign_map.update(req_params)
    return {
        "app_version": APP_VERSION,
        "clientId": CLIENT_ID,
        "os": OS_NAME,
        "os_language": OS_LANGUAGE,
        "os_version": OS_VERSION,
        "timestamp": ts,
        "sign": _sign(sign_map),
        "Content-Type": "application/json",
        "User-Agent": "Segway_Mowerbot/4.02.0 (android)",
    }


async def _request(session: aiohttp.ClientSession, host: str, path: str,
                    params: dict, *, method: str, timeout: int = 20) -> dict:
    """Signierter Passport-Call gegen einen konkreten Regional-Host.

    Der Sign deckt exakt die Request-Params ab (GET: Query, POST: JSON-Body) --
    jedes zusätzliche Feld liefert serverseitig resultCode 90031 "sign invalid".
    """
    headers = _signed_headers(path, params)
    url = f"https://{host}{path}"
    kwargs: dict = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=timeout)}
    if method == "POST":
        kwargs["json"] = params
    elif params:
        kwargs["params"] = params
    async with session.request(method, url, **kwargs) as resp:
        return await resp.json(content_type=None)


async def lookup_region(session: aiohttp.ClientSession, email: str,
                         hosts: tuple[str, ...] | None = None) -> str | None:
    """Welcher Regional-Server besitzt diesen Account? ``None`` wenn keiner.

    Braucht nur die E-Mail -- das Passwort geht nie an einen Server, der den
    Account gar nicht kennt. Antwortet kein einziger Server, wird das nicht als
    "Frankfurt" geraten, sonst schickt ein kurzer Netzwerkfehler das Passwort an
    die falsche Region (navimow_pro 9e5a814).
    """
    answered = False
    for host in hosts or ALL_PASSPORT_HOSTS:
        params = {"account": email, "device": DEVICE}
        try:
            j = await _request(session, host, "/v3/region", params, method="GET", timeout=15)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            continue
        answered = True
        code = str(j.get("resultCode"))
        if code == _RESULT_OK:
            return (j.get("data") or {}).get("region")
    if not answered:
        raise PassportError("network", "no passport directory answered; account region unknown")
    return None


def _extract_tokens(data: dict) -> Tokens:
    raw_region = data.get("region")
    return Tokens(
        access_token=str(data.get("access_token", "")),
        refresh_token=str(data.get("refresh_token", "")),
        uuid=str(data.get("uuid") or ""),
        region=str(raw_region) if raw_region else "",
    )


async def login(session: aiohttp.ClientSession, username: str, password: str,
                 region: str | None = None) -> Tokens:
    """POST /v3/user/login -> Tokens. Wirft PassportAuthError bei falschen Zugangsdaten."""
    discovered = False
    if not region:
        region = await lookup_region(session, username) or DEFAULT_REGION
        discovered = True
    params = {"username": username, "password": password, "device": DEVICE}
    last: PassportAuthError | None = None
    for host in passport_hosts(region):
        j = await _request(session, host, "/v3/user/login", params, method="POST")
        code = str(j.get("resultCode"))
        if code == _RESULT_OK:
            tokens = _extract_tokens(j.get("data") or {})
            tokens.region = tokens.region or str(region or "")
            return tokens
        last = PassportAuthError(code, str(j.get("resultDesc", "")))
        if code != RESULT_ACCOUNT_NOT_EXISTS:
            raise last

    if not discovered:
        found = await lookup_region(session, username)
        if found and canonical_region(found) != canonical_region(region):
            return await login(session, username, password, found)
    raise last or PassportAuthError("unknown", "login failed")


async def refresh(session: aiohttp.ClientSession, tokens: Tokens,
                   region: str | None = None) -> Tokens:
    """POST /v3/user/refresh -> neue Tokens.

    Probiert alle Hosts der Region wie der Login. Ein Host, der antwortet und
    ablehnt, ist endgültig; nur ein unerreichbarer Host wird übersprungen.
    """
    params = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "device": DEVICE,
    }
    unreachable: Exception | None = None
    for host in passport_hosts(region or tokens.region):
        try:
            j = await _request(session, host, "/v3/user/refresh", params, method="POST")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            unreachable = err
            continue
        code = str(j.get("resultCode"))
        if code != _RESULT_OK:
            raise PassportAuthError(code, str(j.get("resultDesc", "")))
        new = _extract_tokens(j.get("data") or {})
        if not new.uuid:
            new.uuid = tokens.uuid
        if not new.region:
            new.region = tokens.region
        return new
    raise PassportError("network", f"no passport host could be reached ({unreachable})")

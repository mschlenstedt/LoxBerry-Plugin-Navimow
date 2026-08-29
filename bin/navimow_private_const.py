"""Regionen- und Host-Tabellen fuer die private Navimow-Cloud.

Port aus ilguala/navimow_pro (const.py), beschraenkt auf das, was Auth- und
Login-Code brauchen. Jede Region hat ihren eigenen Passport-Server; die
falsche Region antwortet beim Login mit "account not exists" statt die
Anfrage weiterzuleiten.
"""
from __future__ import annotations

DEFAULT_REGION = "fra"

_REGION_ALIASES = {"eu": "fra", "sea": "sg", "ore": "us"}

PASSPORT_HOSTS = {
    "fra": ("api-passport-fra.willand.com", "api-passport-fra.ninebot.com"),
    "sg": ("api-passport-sg.willand.com", "api-passport-sg.ninebot.com"),
    "us": (
        "api-passport-us.ninebot.com",
        "api-passport-ore.ninebot.com",
        "api-passport-ore.willand.com",
    ),
    "bj": ("api-passport-bj.willand.com", "api-passport-bj.ninebot.com"),
}

MOWER_HOSTS = {
    "fra": ("navimow-fra.ninebot.com", "navimow-fra.willand.com"),
    "sg": ("navimow-sg.willand.com",),
    "bj": ("navimow-bj.ninebot.com", "navimow-bj.willand.com"),
    # Kein eigener US-Host: ein US-Account wird ueber den Frankfurt-Host bedient.
    "us": ("navimow-fra.ninebot.com", "navimow-ore.willand.com"),
}

_ALL_MOWER_HOSTS = tuple(dict.fromkeys(h for hosts in MOWER_HOSTS.values() for h in hosts))

ALL_PASSPORT_HOSTS = tuple(dict.fromkeys(
    [hosts[0] for hosts in PASSPORT_HOSTS.values() if hosts]
    + [h for hosts in PASSPORT_HOSTS.values() for h in hosts[1:]]
))


def canonical_region(region: str | None) -> str:
    code = str(region or "").strip().lower()
    if not code:
        return DEFAULT_REGION
    return _REGION_ALIASES.get(code, code)


def passport_hosts(region: str | None) -> tuple[str, ...]:
    return PASSPORT_HOSTS.get(canonical_region(region)) or ALL_PASSPORT_HOSTS


def mower_hosts(region: str | None) -> tuple[str, ...]:
    hosts = MOWER_HOSTS.get(canonical_region(region)) or ()
    extra = tuple(h for h in _ALL_MOWER_HOSTS if h not in hosts)
    return hosts + extra

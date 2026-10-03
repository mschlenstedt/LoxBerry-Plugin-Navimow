import pytest

import aiohttp

import navimow_unofficial_auth as auth_mod
from navimow_unofficial_auth import Tokens, _sign, _signed_headers


def test_sign_known_vector():
    # Von Hand mit hashlib.sha256 nachgerechnet, unabhängig von _sign().
    vector = {"a": "1", "b": "2", "c": "x"}
    expected = "bd2ca1cba8d25bd1e5abaf6961680e0dde59957db76c1588aba3eac707a70bb6"
    assert _sign(vector) == expected


def test_signed_headers_structure():
    h = _signed_headers("/v3/user/login", {"username": "a@b.c", "password": "x", "device": "ANDROID"})
    assert h["clientId"] == "mowerbot_app_prod"
    assert len(h["sign"]) == 64
    int(h["sign"], 16)


def test_tokens_defaults():
    t = Tokens(access_token="AT", refresh_token="RT")
    assert t.uuid == ""
    assert t.region == "fra"


async def _unreachable(*args, **kwargs):
    raise aiohttp.ClientConnectionError("down")


async def test_lookup_region_raises_network_when_no_host_answers(monkeypatch):
    monkeypatch.setattr(auth_mod, "_request", _unreachable)
    with pytest.raises(auth_mod.PassportError) as err:
        await auth_mod.lookup_region(None, "benutzer@example.com")
    assert err.value.code == "network"


async def test_lookup_region_returns_none_when_answered_but_unclaimed(monkeypatch):
    async def not_here(*args, **kwargs):
        return {"resultCode": "00002"}
    monkeypatch.setattr(auth_mod, "_request", not_here)
    assert await auth_mod.lookup_region(None, "benutzer@example.com") is None


async def test_refresh_moves_on_from_unreachable_host(monkeypatch):
    hosts = []

    async def fake(session, host, path, params, *, method, timeout=20):
        hosts.append(host)
        if len(hosts) == 1:
            raise aiohttp.ClientConnectionError("down")
        return {"resultCode": "90000", "data": {"access_token": "AT2", "refresh_token": "RT2"}}

    monkeypatch.setattr(auth_mod, "_request", fake)
    new = await auth_mod.refresh(None, auth_mod.Tokens("AT", "RT", "U", "fra"))
    assert (new.access_token, new.refresh_token, new.uuid, new.region) == ("AT2", "RT2", "U", "fra")
    assert len(hosts) == 2


async def test_refresh_refusal_is_final(monkeypatch):
    hosts = []

    async def refused(session, host, path, params, *, method, timeout=20):
        hosts.append(host)
        return {"resultCode": "90016", "resultDesc": "token expired"}

    monkeypatch.setattr(auth_mod, "_request", refused)
    with pytest.raises(auth_mod.PassportAuthError):
        await auth_mod.refresh(None, auth_mod.Tokens("AT", "RT", "U", "fra"))
    assert len(hosts) == 1


async def test_refresh_all_hosts_down_raises_network(monkeypatch):
    monkeypatch.setattr(auth_mod, "_request", _unreachable)
    with pytest.raises(auth_mod.PassportError) as err:
        await auth_mod.refresh(None, auth_mod.Tokens("AT", "RT", "U", "fra"))
    assert err.value.code == "network"

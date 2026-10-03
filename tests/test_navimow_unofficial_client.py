import pytest

import navimow_unofficial_auth as auth
import navimow_unofficial_client as client_module
from navimow_unofficial_client import NavimowAuthError, NavimowError, NavimowUnofficialClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, **kwargs):
        self.calls.append((url, json))
        return _FakeResponse(self._responses.pop(0))


@pytest.fixture(autouse=True)
def _identity_crypto(monkeypatch):
    # Crypto ist in Task 3 separat getestet -- hier wird die HTTP-/Retry-Logik
    # isoliert geprüft, ohne echte Verschlüsselung im Weg.
    monkeypatch.setattr(client_module.crypto, "pack", lambda business: business)
    monkeypatch.setattr(client_module.crypto, "decode_response", lambda resp: resp)


@pytest.mark.asyncio
async def test_call_reauths_once_on_auth_error():
    responses = [
        {"code": 401903, "desc": "token expired"},   # 1. call() -> Auth-Fehler
        {"code": 1, "data": {"uid": "42"}},            # 2. mower_login() Re-Auth
        {"code": 1, "data": {"battery": 88}},          # 3. call()-Retry -> ok
    ]
    session = _FakeSession(responses)
    tokens = auth.Tokens(access_token="AT", refresh_token="RT", uuid="U", region="fra")
    c = NavimowUnofficialClient(session, "clientdev", tokens=tokens, uid="99",
                              host="navimow-fra.ninebot.com")

    data = await c.call("/vehicle/vehicle/index2", {"vehicle_sn": "SN1"})

    assert data == {"battery": 88}
    assert c.uid == "42"
    assert len(session.calls) == 3


@pytest.mark.asyncio
async def test_pause_sends_c_behavior_envelope():
    session = _FakeSession([{"code": 1, "data": {"cmd_num": "abc"}}])
    tokens = auth.Tokens(access_token="AT", refresh_token="RT", uuid="U", region="fra")
    c = NavimowUnofficialClient(session, "clientdev", tokens=tokens, uid="42",
                              host="navimow-fra.ninebot.com")

    result = await c.pause("SN1")

    assert result == {"cmd_num": "abc"}
    _, sent_body = session.calls[0]
    assert sent_body["cmdCode"] == "c:behavior"
    assert sent_body["type"] == "1"
    assert sent_body["data"] == {"type": 1}


@pytest.mark.asyncio
async def test_call_raises_navimow_error_on_business_failure():
    from navimow_unofficial_client import NavimowError
    session = _FakeSession([{"code": 5001, "desc": "refused while running"}])
    tokens = auth.Tokens(access_token="AT", refresh_token="RT", uuid="U", region="fra")
    c = NavimowUnofficialClient(session, "clientdev", tokens=tokens, uid="42",
                              host="navimow-fra.ninebot.com")

    with pytest.raises(NavimowError):
        await c.dock("SN1")


@pytest.mark.asyncio
async def test_call_reports_retry_code_after_reauth():
    responses = [
        {"code": 401903, "desc": "token expired"},   # 1. Auth-Fehler
        {"code": 1, "data": {"uid": "42"}},            # 2. mower_login ok
        {"code": 5001, "desc": "refused"},             # 3. Retry: anderer Fehler
    ]
    session = _FakeSession(responses)
    tokens = auth.Tokens(access_token="AT", refresh_token="RT", uuid="U", region="fra")
    c = NavimowUnofficialClient(session, "clientdev", tokens=tokens, uid="99",
                              host="navimow-fra.ninebot.com")

    with pytest.raises(NavimowError) as exc:
        await c.call("/vehicle/vehicle/index2", {"vehicle_sn": "SN1"})

    assert not isinstance(exc.value, NavimowAuthError)
    assert exc.value.code == 5001

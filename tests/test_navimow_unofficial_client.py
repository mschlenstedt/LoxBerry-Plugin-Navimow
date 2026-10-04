import json as _json
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


def _client(session):
    tokens = auth.Tokens(access_token="AT", refresh_token="RT", uuid="U", region="fra")
    return NavimowUnofficialClient(session, "clientdev", tokens=tokens, uid="42", host="navimow-fra.ninebot.com")


async def test_read_calls_use_expected_paths():
    session = _FakeSession([{"code": 1, "data": {"map_id": 1}}, {"code": 1, "data": []},
                            {"code": 1, "data": {"map_detail": "{}"}}, {"code": 1, "data": {"workPlanV2": []}}])
    c = _client(session)
    await c.location("SN1", 160000001)
    await c.map_list("SN1")
    await c.map_detail("SN1", "11", "22")
    await c.set_list("SN1")
    paths = [url.split("navimow-fra.ninebot.com")[1] for url, _ in session.calls]
    assert paths == ["/vehicle/vehicle/get-location", "/map/index/map-list",
                     "/map/index/map-detail", "/vehicle/vehicle/set-list"]
    assert session.calls[0][1]["vehicle_type"] == 160000001
    assert session.calls[2][1]["map_id"] == "11" and session.calls[2][1]["map_base_id"] == "22"


async def test_mow_zones_envelope():
    session = _FakeSession([{"code": 1, "data": {"cmd_num": "x"}}])
    await _client(session).mow_zones("SN1", "02000100", 0x12)
    body = session.calls[0][1]
    assert body["cmdCode"] == "s:mower"
    assert body["data"] == {"partitionSetup": 0x12, "partitionIds": "02000100"}


async def test_set_day_schedule_sends_device_command_then_cloud_copy():
    session = _FakeSession([{"code": 1, "data": {}}, {"code": 1, "data": {}}])
    periods = [{"start_time": 36, "end_time": 48, "partition_ids": [1]}]
    await _client(session).set_day_schedule("SN1", 160000001, 2, True, periods)
    (url1, first), (url2, second) = session.calls
    assert url1.endswith("/vehicle/set/send") and first["cmdCode"] == "s:mower"
    assert _json.loads(first["data"]) == {"partitionPlan1": "010201012430010100"}
    assert url2.endswith("/vehicle/set/save-set-data")
    assert second["operation_type"] == "iot_set" and second["vehicle_type"] == "160000001"
    assert second["data"] == {"partitionPlan1": {"day": 2, "open": 1, "period": periods}}


async def test_set_day_schedule_stops_when_mower_refuses():
    from navimow_unofficial_client import NavimowError
    session = _FakeSession([{"code": 5001, "desc": "running"}])
    with pytest.raises(NavimowError):
        await _client(session).set_day_schedule("SN1", 160000001, 2, True, [])
    assert len(session.calls) == 1


async def test_set_day_schedule_cloud_copy_failure_is_distinct():
    session = _FakeSession([{"code": 1, "data": {}}, {"code": 9999, "desc": "boom"}])
    with pytest.raises(NavimowError, match="Cloud-Kopie") as exc:
        await _client(session).set_day_schedule("SN1", 160000001, 2, True, [])
    assert exc.value.code == 9999 and "boom" in str(exc.value)
    assert len(session.calls) == 2


from types import SimpleNamespace as _NS


@pytest.mark.asyncio
async def test_read_calls_for_device_state_and_faults():
    session = _FakeSession([{"code": 1, "data": {"model": "i215"}}, {"code": 1, "data": {"vehicle_state": "0101"}},
                            {"code": 1, "data": "blob"}])
    c = _client(session)
    assert await c.device_info("SN1") == {"model": "i215"}
    assert await c.index2("SN1") == {"vehicle_state": "0101"}
    assert await c.errors("SN1", 160000001) == "blob"
    paths = [url.split("navimow-fra.ninebot.com")[1] for url, _ in session.calls]
    assert paths == ["/vehicle/vehicle/get-device-info", "/vehicle/vehicle/index2",
                     "/vehicle/vehicle/get-hint-error-compress"]
    assert session.calls[2][1]["vehicle_type"] == 160000001


@pytest.mark.asyncio
async def test_write_setting_device_first_then_cloud_iot():
    session = _FakeSession([{"code": 1, "data": {}}, {"code": 1, "data": {}}])
    w = _NS(robot={"tcsSwitch": 1}, cloud={"tractionControl": 1}, iot=True)
    await _client(session).write_setting("SN1", 160000001, w)
    (u1, first), (u2, second) = session.calls
    assert u1.endswith("/vehicle/set/send") and first["cmdCode"] == "s:mower"
    assert _json.loads(first["data"]) == {"tcsSwitch": 1}
    assert u2.endswith("/vehicle/set/save-set-data")
    assert second["data"] == {"tractionControl": 1}
    assert second["operation_type"] == "iot_set" and second["vehicle_type"] == "160000001"


@pytest.mark.asyncio
async def test_write_setting_legacy_is_cloud_only_without_iot_fields():
    session = _FakeSession([{"code": 1, "data": {}}])
    await _client(session).write_setting("SN1", 160000001, _NS(robot=None, cloud={"rainSensor": "00"}, iot=False))
    (url, body), = session.calls
    assert url.endswith("/vehicle/set/save-set-data") and body["data"] == {"rainSensor": "00"}
    assert "operation_type" not in body and "vehicle_type" not in body


@pytest.mark.asyncio
async def test_write_setting_stops_when_mower_refuses():
    session = _FakeSession([{"code": 5001, "desc": "running"}])
    with pytest.raises(NavimowError):
        await _client(session).write_setting("SN1", 1, _NS(robot={"soundSwitch": 0}, cloud={"soundSwitch": "0"}, iot=True))
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_write_setting_reports_failed_cloud_copy():
    session = _FakeSession([{"code": 1, "data": {}}, {"code": 9999, "desc": "x"}])
    with pytest.raises(NavimowError) as err:
        await _client(session).write_setting("SN1", 1, _NS(robot={"soundSwitch": 0}, cloud={"soundSwitch": "0"}, iot=True))
    assert "Cloud-Kopie" in str(err.value)

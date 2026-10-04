import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import navimow_gateway as gw  # noqa: E402
import navimow_unofficial_plan as plan  # noqa: E402
from navimow_unofficial_client import NavimowError  # noqa: E402

CFG = {"unofficial_devices": [{"device_id": "D1", "vehicle_sn": "SN1", "vehicle_type": 160000001}]}


class FakeMqtt:
    def __init__(self):
        self.results = []

    async def publish(self, topic, payload, retain=False):
        self.results.append(json.loads(payload))


class FakeClient:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    async def mow_zones(self, sn, ids_hex, setup):
        self.calls.append(("mow", sn, ids_hex, setup))

    async def set_day_schedule(self, sn, vt, day, enabled, periods):
        if self.fail:
            raise self.fail
        self.calls.append(("schedule", sn, vt, day, enabled, periods))

    async def dock(self, sn):
        if self.fail:
            raise self.fail
        self.calls.append(("dock", sn))


def _msg(payload):
    return SimpleNamespace(payload=json.dumps(payload).encode())


def _known(*ids):
    cache = plan.ZoneCache()
    cache.zones = [{"id": i, "name": f"Zone {i}", "area": None} for i in ids]
    gw._unofficial_zone_cache["D1"] = cache


async def test_mow_all_zones_uses_known_zones():
    _known(2, 1)
    mqtt, client = FakeMqtt(), FakeClient()
    await gw._handle_unofficial_command(mqtt, _msg({"cmd": "mow"}), "D1", "navimow", CFG, client)
    assert client.calls == [("mow", "SN1", "01000200", 0x21)]
    assert mqtt.results[-1]["result"] == "ok" and mqtt.results[-1]["source"] == "unofficial"


async def test_schedule_writes_and_triggers_refresh():
    _known(1)
    gw._unofficial_refresh.clear()
    mqtt, client = FakeMqtt(), FakeClient()
    payload = {"cmd": "schedule", "day": "montag", "periods": [{"start": "09:00", "end": "12:00", "zones": [1]}]}
    await gw._handle_unofficial_command(mqtt, _msg(payload), "D1", "navimow", CFG, client)
    assert client.calls == [("schedule", "SN1", 160000001, 2, True,
                             [{"start_time": 36, "end_time": 48, "partition_ids": [1]}])]
    assert gw._unofficial_refresh.is_set()


async def test_schedule_off_grid_is_refused_without_cloud_call():
    _known(1)
    mqtt, client = FakeMqtt(), FakeClient()
    payload = {"cmd": "schedule", "day": "monday", "periods": [{"start": "09:10", "end": "12:00"}]}
    await gw._handle_unofficial_command(mqtt, _msg(payload), "D1", "navimow", CFG, client)
    assert client.calls == []
    assert mqtt.results[-1]["result"] == "error" and "15-Minuten" in mqtt.results[-1]["reason"]


async def test_schedule_refused_while_mowing_explains():
    _known(1)
    mqtt, client = FakeMqtt(), FakeClient(fail=NavimowError(5001, "running"))
    payload = {"cmd": "schedule", "day": "monday", "periods": []}
    await gw._handle_unofficial_command(mqtt, _msg(payload), "D1", "navimow", CFG, client)
    assert "mäht" in mqtt.results[-1]["reason"]


async def test_dock_calls_client_and_reports_ok():
    mqtt, client = FakeMqtt(), FakeClient()
    await gw._handle_unofficial_command(mqtt, _msg({"cmd": "dock"}), "D1", "navimow", CFG, client)
    assert client.calls == [("dock", "SN1")]
    assert mqtt.results[-1]["result"] == "ok"


async def test_5001_explanation_only_for_mow_and_schedule():
    for cmd, expect in (("mow", True), ("dock", False)):
        _known(1)
        mqtt, client = FakeMqtt(), FakeClient(fail=NavimowError(5001, "running"))
        client.mow_zones = lambda *a, _c=client: (_ for _ in ()).throw(_c.fail)
        await gw._handle_unofficial_command(mqtt, _msg({"cmd": cmd}), "D1", "navimow", CFG, client)
        reason = mqtt.results[-1]["reason"]
        assert ("mäht" in reason) is expect
        assert "5001" in reason


async def test_schedule_without_periods_sends_remembered_windows():
    _known(1)
    gw._unofficial_schedule["D1"] = {"monday": {"enabled": True, "text": "x", "periods": [
        {"start": "09:00", "end": "12:00", "zones": [1]}]}}
    mqtt, client = FakeMqtt(), FakeClient()
    await gw._handle_unofficial_command(
        mqtt, _msg({"cmd": "schedule", "day": "montag", "enabled": False}), "D1", "navimow", CFG, client)
    assert client.calls == [("schedule", "SN1", 160000001, 2, False,
                             [{"start_time": 36, "end_time": 48, "partition_ids": [1]}])]


async def test_schedule_without_periods_and_no_plan_read_is_refused():
    _known(1)
    gw._unofficial_schedule.pop("D1", None)
    mqtt, client = FakeMqtt(), FakeClient()
    await gw._handle_unofficial_command(
        mqtt, _msg({"cmd": "schedule", "day": "montag", "enabled": False}), "D1", "navimow", CFG, client)
    assert client.calls == [] and "noch nicht gelesen" in mqtt.results[-1]["reason"]


async def test_schedule_failure_still_triggers_refresh():
    _known(1)
    gw._unofficial_refresh.clear()
    mqtt, client = FakeMqtt(), FakeClient(fail=NavimowError(9999, "Cloud-Kopie"))
    await gw._handle_unofficial_command(
        mqtt, _msg({"cmd": "schedule", "day": "monday", "periods": []}), "D1", "navimow", CFG, client)
    assert mqtt.results[-1]["result"] == "error" and gw._unofficial_refresh.is_set()


async def test_broken_vehicle_type_gives_error_result():
    _known(1)
    cfg = {"unofficial_devices": [{"device_id": "D1", "vehicle_sn": "SN1", "vehicle_type": "abc"}]}
    mqtt, client = FakeMqtt(), FakeClient()
    await gw._handle_unofficial_command(mqtt, _msg({"cmd": "dock"}), "D1", "navimow", cfg, client)
    assert mqtt.results[-1]["result"] == "error"


async def test_poll_isolates_failures_and_backs_off(monkeypatch):
    import asyncio
    import types
    snap = types.ModuleType("navimow_unofficial_snapshot")

    async def fetch_zones(client, sn, vt, cache):
        if sn == "BAD":
            raise RuntimeError("boom")
        return [{"id": 1, "name": "Z", "area": None}]

    async def fetch_settings_and_schedule(client, sn, zones):
        return {"sound": True}, {"monday": {"enabled": True, "periods": [], "text": "x"}}

    async def fetch_device(client, sn, model=""):
        return {}

    async def fetch_fault(client, sn, vt):
        return {"active": False, "codes": [], "text": "", "state_code": "0101", "state_text": ""}

    snap.fetch_zones, snap.fetch_settings_and_schedule = fetch_zones, fetch_settings_and_schedule
    snap.fetch_device, snap.fetch_fault = fetch_device, fetch_fault
    monkeypatch.setitem(sys.modules, "navimow_unofficial_snapshot", snap)
    queued = []
    monkeypatch.setattr(gw, "_queue_retained", lambda topic, payload: queued.append(topic))
    gw._unofficial_schedule.clear()
    shutdown, timeouts = asyncio.Event(), []

    async def fake_wait_for(coro, timeout):
        coro.close()
        timeouts.append(timeout)
        if len(timeouts) >= 3:
            shutdown.set()
        raise asyncio.TimeoutError

    monkeypatch.setattr(gw.asyncio, "wait_for", fake_wait_for)
    cfg = {"unofficial_devices": [{"device_id": "B", "vehicle_sn": "BAD"}, {"device_id": "G", "vehicle_sn": "OK"}]}
    await gw.task_unofficial_poll(cfg, object(), "navimow", shutdown)
    assert "navimow/G/zones" in queued and "G" in gw._unofficial_schedule
    assert timeouts == [60, 120, 240]


DEVICE = {"model": "i215", "cut_height_options": [30, 40, 50], "cut_height_flag": True, "limits": {}}


async def test_setting_writes_and_triggers_refresh():
    gw._unofficial_settings["D1"] = {"sound": True, "cut_height_mm": 40}
    gw._unofficial_device["D1"] = DEVICE
    gw._unofficial_refresh.clear()
    calls = []

    class Client(FakeClient):
        async def write_setting(self, sn, vt, write):
            calls.append((sn, vt, write.robot, write.cloud, write.iot))

    mqtt = FakeMqtt()
    await gw._handle_unofficial_command(mqtt, _msg({"cmd": "setting", "key": "sound", "value": "aus"}), "D1", "navimow", CFG, Client())
    await gw._handle_unofficial_command(mqtt, _msg({"cmd": "setting", "key": "cut_height_mm", "value": 50}), "D1", "navimow", CFG, Client())
    assert calls == [("SN1", 160000001, {"soundSwitch": 0}, {"soundSwitch": "0"}, True),
                     ("SN1", 160000001, {"height": "50"}, {"height": 50}, True)]
    assert mqtt.results[-1]["result"] == "ok" and gw._unofficial_refresh.is_set()


async def test_setting_refused_before_settings_are_read():
    gw._unofficial_settings.pop("D1", None)
    mqtt = FakeMqtt()
    await gw._handle_unofficial_command(mqtt, _msg({"cmd": "setting", "key": "sound", "value": 1}), "D1", "navimow", CFG, FakeClient())
    assert mqtt.results[-1]["result"] == "error" and "noch nicht gelesen" in mqtt.results[-1]["reason"]


async def test_setting_refused_while_mowing_explains():
    gw._unofficial_settings["D1"] = {"sound": True}

    class Client(FakeClient):
        async def write_setting(self, sn, vt, write):
            raise NavimowError(5001, "running")

    mqtt = FakeMqtt()
    await gw._handle_unofficial_command(mqtt, _msg({"cmd": "setting", "key": "sound", "value": 0}), "D1", "navimow", CFG, Client())
    assert "mäht" in mqtt.results[-1]["reason"]

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

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


@pytest.fixture(autouse=True)
def _isolate_unofficial_state(monkeypatch):
    for name in ("_unofficial_settings", "_unofficial_device", "_unofficial_fault", "_official_model",
                 "_unofficial_schedule", "_device_state"):
        monkeypatch.setattr(gw, name, {})
    gw._unofficial_refresh.clear()


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
        return {"model": model, "cut_height_options": [], "cut_height_flag": False, "limits": {}}, True

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
    assert "navimow/G/settings" in queued and "navimow/G/fault" in queued
    assert timeouts == [120, 120, 240]          # Backoff 60/120/240, mindestens der Ruhetakt 120 s


# ── Hilfen für die Poll-Tests unten ──────────────────────────────────────────
OK_FAULT = {"active": False, "codes": [], "text": "", "state_code": "0101", "state_text": ""}


def _poll_env(monkeypatch, **overrides):
    """Snapshot-Attrappe + abgefangenes wait_for; liefert (calls, queued, payloads, timeouts, shutdown, run)."""
    import asyncio
    import types
    calls, queued, payloads, timeouts = [], [], {}, []
    snap = types.ModuleType("navimow_unofficial_snapshot")

    async def fetch_zones(client, sn, vt, cache):
        calls.append("zones")
        return [{"id": 1, "name": "Z", "area": None}]

    async def fetch_settings_and_schedule(client, sn, zones):
        calls.append("settings")
        return {"cut_height_mm": 60}, {"monday": {"enabled": True, "periods": [], "text": "x"}}

    async def fetch_device(client, sn, model=""):
        calls.append("device")
        return {"model": model, "cut_height_options": [], "cut_height_flag": True, "limits": {}}, True

    async def fetch_fault(client, sn, vt):
        calls.append("fault")
        return dict(OK_FAULT)

    async def fetch_coverage(client, sn, zones):
        calls.append("coverage")
        return {"overall_pct": 50, "total_area": 10.0, "finished_area": 5.0, "start": 1, "end": 2,
                "zones": [{"id": 1, "name": "Z", "area": 10.0, "finished": 5.0, "pct": 50, "start": 1, "end": 2}]}

    snap.fetch_coverage = fetch_coverage
    snap.fetch_zones, snap.fetch_settings_and_schedule = fetch_zones, fetch_settings_and_schedule
    snap.fetch_device, snap.fetch_fault = fetch_device, fetch_fault
    for k, v in overrides.items():
        setattr(snap, k, v)
    monkeypatch.setitem(sys.modules, "navimow_unofficial_snapshot", snap)

    def queue(topic, payload):
        queued.append(topic)
        payloads[topic] = payload

    monkeypatch.setattr(gw, "_queue_retained", queue)
    shutdown = asyncio.Event()

    def run(rounds, cfg=None):
        async def fake_wait_for(coro, timeout):
            coro.close()
            timeouts.append(timeout)
            if len(timeouts) >= rounds:
                shutdown.set()
            raise asyncio.TimeoutError

        monkeypatch.setattr(gw.asyncio, "wait_for", fake_wait_for)
        return gw.task_unofficial_poll(cfg or CFG, object(), "navimow", shutdown)

    return calls, queued, payloads, timeouts, run


async def test_poll_new_reads_failing_keep_zones_plan_and_settings(monkeypatch):
    async def boom_device(client, sn, model=""):
        raise RuntimeError("device boom")

    async def boom_fault(client, sn, vt):
        raise RuntimeError("fault boom")

    calls, queued, payloads, timeouts, run = _poll_env(monkeypatch, fetch_device=boom_device, fetch_fault=boom_fault)
    await run(1)
    assert {"navimow/D1/zones", "navimow/D1/schedule", "navimow/D1/settings"} <= set(queued)
    assert "navimow/D1/fault" not in queued
    assert "D1" not in gw._unofficial_device and "D1" not in gw._unofficial_fault
    assert timeouts == [120]                        # Ruhetakt; Backoff 60 s liegt darunter


async def test_poll_does_not_cache_empty_device_and_passes_official_model(monkeypatch):
    async def empty_device(client, sn, model=""):
        models.append(model)
        return {"model": model, "cut_height_options": [], "cut_height_flag": False, "limits": {}}, False

    models = []
    calls, queued, payloads, timeouts, run = _poll_env(monkeypatch, fetch_device=empty_device)
    gw._official_model["D1"] = "i215"
    await run(7)                                    # Runde 1 und 7 sind voll
    assert models == ["i215", "i215"] and "D1" not in gw._unofficial_device


async def test_poll_fills_in_model_from_official_api_later(monkeypatch):
    calls, queued, payloads, timeouts, run = _poll_env(monkeypatch)
    gw._unofficial_device["D1"] = {"model": "", "cut_height_options": [], "cut_height_flag": True, "limits": {}}
    gw._official_model["D1"] = "i215"
    await run(1)
    assert gw._unofficial_device["D1"]["model"] == "i215"
    assert payloads["navimow/D1/settings"]["cut_height_writable"] == 1


async def test_poll_cut_height_not_writable_without_reported_height(monkeypatch):
    async def settings_no_height(client, sn, zones):
        return {"sound": True}, {}

    calls, queued, payloads, timeouts, run = _poll_env(monkeypatch, fetch_settings_and_schedule=settings_no_height)
    gw._official_model["D1"] = "i215"
    await run(1)
    assert payloads["navimow/D1/settings"]["cut_height_writable"] == 0


async def test_poll_active_fault_uses_30s_and_short_rounds_read_only_state_and_coverage(monkeypatch):
    async def active_fault(client, sn, vt):
        calls.append("fault")
        return {**OK_FAULT, "active": True, "codes": ["6004"], "text": "x"}

    calls, queued, payloads, timeouts, run = _poll_env(monkeypatch, fetch_fault=active_fault)
    await run(3)
    assert timeouts == [30, 30, 30]
    assert calls.count("zones") == 1 and calls.count("settings") == 1 and calls.count("fault") == 3
    assert queued.count("navimow/D1/fault") == 3 and queued.count("navimow/D1/zones") == 1


async def test_update_state_sets_refresh_on_error_mowing_and_returning_transitions():
    gw._update_state("D1", {"vehicleState_desc": "docked"})
    assert not gw._unofficial_refresh.is_set()
    gw._update_state("D1", {"vehicleState_desc": "paused"})
    assert not gw._unofficial_refresh.is_set()
    for desc in ("mowing", "returning", "docked", "error", "docked"):
        gw._update_state("D1", {"vehicleState_desc": desc})
        assert gw._unofficial_refresh.is_set(), desc
        gw._unofficial_refresh.clear()
    gw._update_state("D1", {"vehicleState_desc": "docked", "battery": 50})
    assert not gw._unofficial_refresh.is_set()


async def test_poll_publishes_coverage_every_round(monkeypatch):
    calls, queued, payloads, timeouts, run = _poll_env(monkeypatch)
    await run(1)
    p = payloads["navimow/D1/coverage"]
    assert p["zone_1_pct"] == 50 and p["count"] == 1 and "ts" in p


async def test_poll_while_mowing_uses_3s_and_reads_coverage_in_short_rounds(monkeypatch):
    calls, queued, payloads, timeouts, run = _poll_env(monkeypatch)
    gw._device_state["D1"] = {"vehicleState_desc": "mowing"}
    await run(3)
    assert timeouts == [3, 3, 3]
    assert calls.count("zones") == 1 and calls.count("coverage") == 3 and calls.count("fault") == 3


async def test_poll_coverage_failure_or_empty_keeps_rest(monkeypatch):
    async def boom(client, sn, zones):
        raise RuntimeError("coverage boom")

    calls, queued, payloads, timeouts, run = _poll_env(monkeypatch, fetch_coverage=boom)
    await run(1)
    assert "navimow/D1/coverage" not in queued and "navimow/D1/fault" in queued
    assert timeouts == [120]

    async def empty(client, sn, zones):
        return None

    calls, queued, payloads, timeouts, run = _poll_env(monkeypatch, fetch_coverage=empty)
    await run(1)
    assert "navimow/D1/coverage" not in queued


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


def _interval(desc=None, fault=None, schedule=None, settings=None):
    if desc:
        gw._device_state["D1"] = {"vehicleState_desc": desc}
    if fault:
        gw._unofficial_fault["D1"] = {**OK_FAULT, **fault}
    if schedule is not None:
        gw._unofficial_schedule["D1"] = schedule
    if settings is not None:
        gw._unofficial_settings["D1"] = settings
    return gw._unofficial_poll_interval(CFG)


async def test_poll_interval_follows_navimow_pro():
    assert _interval() == 120
    assert _interval(desc="mowing") == 3


async def test_poll_interval_returning_fault_and_unknown_state():
    assert _interval(fault={"state_code": "0220"}) == 12
    gw._unofficial_fault.clear()
    assert _interval(fault={"active": True, "state_code": "0399"}) == 30
    gw._unofficial_fault.clear()
    assert _interval(fault={"state_code": "0599"}) == 30
    gw._unofficial_fault.clear()
    assert _interval(desc="error") == 30


async def test_poll_interval_attentive_shortly_before_scheduled_start(monkeypatch):
    from datetime import datetime as real_datetime

    class FixedNow(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 10, 5, 10, 50)          # Montag 10:50

    monkeypatch.setattr(gw, "datetime", FixedNow)
    plan_ = {"monday": {"enabled": True, "periods": [{"start": "11:00", "end": "15:00", "zones": []}], "text": ""}}
    assert _interval(schedule=plan_) == 30
    assert _interval(settings={"schedule_enabled": False}) == 120


async def test_poll_full_round_every_sixth_round(monkeypatch):
    calls, queued, payloads, timeouts, run = _poll_env(monkeypatch)
    await run(7)
    assert timeouts == [120] * 7
    assert calls.count("zones") == 2 and calls.count("fault") == 7     # Runde 1 und 7 voll
    assert queued.count("navimow/D1/coverage") == 7 and queued.count("navimow/D1/zones") == 2

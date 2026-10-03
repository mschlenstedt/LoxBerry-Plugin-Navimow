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

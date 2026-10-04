import json

import navimow_unofficial_plan as plan
import navimow_unofficial_snapshot as snap
from navimow_unofficial_client import NavimowError


class FakeClient:
    def __init__(self, location, map_list=None, detail=None, set_list=None):
        self._location, self._map_list, self._detail, self._set_list = location, map_list, detail, set_list
        self.detail_calls = 0

    async def location(self, sn, vt):
        if isinstance(self._location, Exception):
            raise self._location
        return self._location

    async def map_list(self, sn):
        return self._map_list

    async def map_detail(self, sn, map_id, base_id):
        self.detail_calls += 1
        return self._detail

    async def set_list(self, sn):
        return self._set_list


DETAIL = {"map_detail": json.dumps({"sub_maps": [{"id": 1, "name": "Vorgarten", "area": 20}]})}


async def test_fetch_zones_reads_map_once_per_version():
    client = FakeClient({"map_id": 1, "map_base_id": 2, "map_edit_time": 7}, detail=DETAIL)
    cache = plan.ZoneCache()
    first = await snap.fetch_zones(client, "SN1", 1, cache)
    second = await snap.fetch_zones(client, "SN1", 1, cache)
    assert first == second == [{"id": 1, "name": "Vorgarten", "area": 20.0}]
    assert client.detail_calls == 1


async def test_fetch_zones_falls_back_to_map_list_and_survives_location_error():
    client = FakeClient(NavimowError(500, "x"), map_list=[{"map_id": 3, "map_base_id": 4}], detail=DETAIL)
    assert [z["id"] for z in await snap.fetch_zones(client, "SN1", 1, plan.ZoneCache())] == [1]


async def test_fetch_zones_keeps_last_known_when_no_map():
    cache = plan.ZoneCache()
    cache.zones = [{"id": 9, "name": "Alt", "area": None}]
    client = FakeClient({}, map_list=[])
    assert await snap.fetch_zones(client, "SN1", 1, cache) == cache.zones


async def test_fetch_settings_and_schedule_reads_set_list_once():
    calls = []

    class Client(FakeClient):
        async def set_list(self, sn):
            calls.append(sn)
            return {"startPlan": "1", "soundSwitch": 0,
                    "workPlanV2": [{"day": 2, "open": 1, "period": [{"start_time": 36, "end_time": 48, "partition_ids": [1]}]}]}

    settings, schedule = await snap.fetch_settings_and_schedule(Client({}), "SN1", [{"id": 1, "name": "Vorgarten", "area": None}])
    assert calls == ["SN1"]
    assert settings == {"schedule_enabled": True, "sound": False}
    assert schedule["monday"]["text"] == "09:00–12:00 Vorgarten"


async def test_fetch_device_prefers_stored_model():
    class Client(FakeClient):
        async def device_info(self, sn):
            return {"model": "anders", "mowingHeightList": [30, 40], "isCutterHeight": 0}

    d, ok = await snap.fetch_device(Client({}), "SN1", "i215")
    assert ok and d["model"] == "i215" and d["cut_height_options"] == [30, 40]


async def test_fetch_device_reports_empty_answer_as_not_ok():
    class Client(FakeClient):
        async def device_info(self, sn):
            return {}

    d, ok = await snap.fetch_device(Client({}), "SN1", "i215")
    assert not ok and d["model"] == "i215"


async def test_fetch_fault_asks_details_only_when_needed():
    asked = []

    class Client(FakeClient):
        def __init__(self, state):
            super().__init__({})
            self.state = state

        async def index2(self, sn):
            return {"vehicle_state": self.state}

        async def errors(self, sn, vt):
            asked.append(sn)
            return {"list": [{"errorCode": "6007"}]}

    ok = await snap.fetch_fault(Client("0101"), "SN1", 1)
    bad = await snap.fetch_fault(Client("0310"), "SN1", 1)
    assert ok["active"] is False and asked == ["SN1"]
    assert bad["codes"] == ["6007"] and bad["text"].startswith("Mäher wurde angehoben")


async def test_fetch_fault_survives_failing_detail_call():
    class Client(FakeClient):
        async def index2(self, sn):
            return {"vehicle_state": "0310"}

        async def errors(self, sn, vt):
            raise NavimowError(500, "x")

    f = await snap.fetch_fault(Client({}), "SN1", 1)
    assert f["active"] is True and f["codes"] == []



async def test_fetch_coverage_uses_zone_names():
    class Client(FakeClient):
        async def path_info_time(self, sn):
            return [{"partitionId": 4, "area": 10, "finishedArea": 5, "partitionPercentage": 50}]

    c = await snap.fetch_coverage(Client({}), "SN1", [{"id": 4, "name": "Beet", "area": None}])
    assert c["zones"][0]["name"] == "Beet" and c["overall_pct"] == 50

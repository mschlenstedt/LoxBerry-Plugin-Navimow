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


async def test_fetch_schedule_uses_zone_names():
    client = FakeClient({}, set_list={"workPlanV2": [{"day": 2, "open": 1, "period": [{"start_time": 36, "end_time": 48, "partition_ids": [1]}]}]})
    out = await snap.fetch_schedule(client, "SN1", [{"id": 1, "name": "Vorgarten", "area": None}])
    assert out["monday"]["text"] == "09:00–12:00 Vorgarten"

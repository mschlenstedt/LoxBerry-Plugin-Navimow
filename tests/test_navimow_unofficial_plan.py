import json

import pytest

import navimow_unofficial_plan as plan


def test_encode_partition_ids_little_endian():
    assert plan.encode_partition_ids([1]) == "0100"
    assert plan.encode_partition_ids([1, 5]) == "01000500"
    assert plan.encode_partition_ids([258]) == "0201"


def test_mow_setup_nibbles():
    assert plan.mow_setup(reset=False, ordered=False) == 0x11
    assert plan.mow_setup(reset=False, ordered=True) == 0x12
    assert plan.mow_setup(reset=True, ordered=False) == 0x21
    assert plan.mow_setup(reset=True, ordered=True) == 0x22


@pytest.mark.parametrize("value,expected", [
    (None, []), ("", []), ([2, 1], [2, 1]), ("2,1", [2, 1]), ("2; 1", [2, 1]), (["3"], [3]),
])
def test_parse_zone_ids_accepts_lists_and_text(value, expected):
    assert plan.parse_zone_ids(value) == expected


def test_parse_zone_ids_rejects_garbage():
    with pytest.raises(plan.PlanError):
        plan.parse_zone_ids("1,vorne")


def test_check_zones_names_unknown_and_known():
    with pytest.raises(plan.PlanError) as err:
        plan.check_zones([1, 9], [1, 2])
    assert "9" in str(err.value) and "1, 2" in str(err.value)


def test_check_zones_accepts_anything_while_map_unknown():
    plan.check_zones([7], [])


def test_build_mow_all_zones_lets_mower_route():
    ids, setup = plan.build_mow({"cmd": "mow"}, [2, 1])
    assert ids == "01000200"
    assert setup == 0x21


def test_build_mow_explicit_order_and_continue():
    ids, setup = plan.build_mow({"cmd": "mow", "zones": "2,1", "reset": "0"}, [1, 2])
    assert ids == "02000100"
    assert setup == 0x12


def test_build_mow_without_known_zones_refuses():
    with pytest.raises(plan.PlanError) as err:
        plan.build_mow({"cmd": "mow"}, [])
    assert "Zonen" in str(err.value)


@pytest.mark.parametrize("value,expected", [
    (True, True), ("1", True), ("ja", True), ("off", False), (0, False), (None, True),
])
def test_as_bool(value, expected):
    assert plan.as_bool(value, True) is expected


def test_pick_map_ids_falls_back_to_map_list_when_location_reports_zero():
    loc = {"map_id": 0, "map_base_id": "0"}
    lst = [{"map_id": 0, "map_base_id": 0}, {"map_id": 11, "map_base_id": 22, "edittime": 5}]
    assert plan.pick_map_ids(loc, lst) == ("11", "22", "5")
    assert plan.pick_map_ids({"map_id": 3, "map_base_id": 4, "map_edit_time": 9}, None) == ("3", "4", "9")
    assert plan.pick_map_ids({}, []) is None


def test_extract_zones_from_plain_map_detail():
    geom = {"sub_maps": [
        {"id": 2, "name": "Garten", "area": "80.5", "elements": []},
        {"id": 1, "name": "", "area": 20, "elements": []},
        {"name": "ohne id"},
    ]}
    zones = plan.extract_zones({"map_detail": json.dumps(geom)})
    assert zones == [
        {"id": 1, "name": "Zone 1", "area": 20.0},
        {"id": 2, "name": "Garten", "area": 80.5},
    ]
    assert plan.extract_zones("kaputt") == []
    assert plan.extract_zones({"map_detail": "{}"}) == []


def test_zones_payload_for_loxone():
    p = plan.zones_payload([{"id": 1, "name": "Vorgarten", "area": 20.0}, {"id": 2, "name": "Garten", "area": None}])
    assert p["count"] == 2 and p["ids"] == "1,2" and p["text"] == "1 Vorgarten, 2 Garten"

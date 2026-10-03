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


def test_parse_zone_ids_rejects_invalid_range():
    with pytest.raises(plan.PlanError) as err:
        plan.parse_zone_ids("0")
    assert "Ungültige Zonen-ID" in str(err.value) and "erlaubt 1 bis 65535" in str(err.value)
    with pytest.raises(plan.PlanError) as err:
        plan.parse_zone_ids("-3")
    assert "erlaubt 1 bis 65535" in str(err.value)
    with pytest.raises(plan.PlanError) as err:
        plan.parse_zone_ids("65536")
    assert "erlaubt 1 bis 65535" in str(err.value)


def test_parse_zone_ids_rejects_duplicates():
    with pytest.raises(plan.PlanError) as err:
        plan.parse_zone_ids("1,1")
    assert "Zone 1 ist doppelt angegeben" in str(err.value)


def test_parse_zone_ids_accepts_boundary():
    assert plan.parse_zone_ids("65535") == [65535]
    assert plan.parse_zone_ids("1") == [1]


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


@pytest.mark.parametrize("value,expected", [
    ("sunday", 1), ("Monday", 2), ("montag", 2), ("Mo", 2), ("sa", 7), ("Samstag", 7),
])
def test_parse_day_accepts_english_and_german(value, expected):
    assert plan.parse_day(value) == expected


def test_parse_day_rejects_unknown():
    with pytest.raises(plan.PlanError):
        plan.parse_day("feiertag")


def test_hhmm_to_slot_on_grid_only():
    assert plan.hhmm_to_slot("09:00") == 36
    assert plan.hhmm_to_slot("23:45") == 95
    assert plan.slot_to_hhmm(36) == "09:00"
    for bad in ("09:47", "25:00", "9h", ""):
        with pytest.raises(plan.PlanError):
            plan.hhmm_to_slot(bad)


def test_build_schedule_sorts_and_validates():
    day, enabled, periods = plan.build_schedule({
        "day": "monday", "enabled": True,
        "periods": [{"start": "14:00", "end": "16:00"}, {"start": "09:00", "end": "12:00", "zones": "1"}],
    }, [1, 2])
    assert (day, enabled) == (2, True)
    assert periods == [
        {"start_time": 36, "end_time": 48, "partition_ids": [1]},
        {"start_time": 56, "end_time": 64, "partition_ids": []},
    ]


def test_build_schedule_accepts_periods_as_json_text():
    _, _, periods = plan.build_schedule({"day": "mo", "periods": '[{"start":"09:00","end":"10:00"}]'}, [])
    assert periods == [{"start_time": 36, "end_time": 40, "partition_ids": []}]


@pytest.mark.parametrize("periods,needle", [
    ([{"start": "12:00", "end": "09:00"}], "Ende"),
    ([{"start": "09:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}], "überlappen"),
    ([{"start": "09:10", "end": "12:00"}], "15-Minuten"),
])
def test_build_schedule_refuses_bad_periods(periods, needle):
    with pytest.raises(plan.PlanError) as err:
        plan.build_schedule({"day": "monday", "periods": periods}, [])
    assert needle in str(err.value)


def test_partition_plan_hex_known_vectors():
    assert plan.partition_plan_hex(2, True, [{"start_time": 36, "end_time": 48, "partition_ids": [1]}]) == "010201012430010100"
    assert plan.partition_plan_hex(2, True, [{"start_time": 36, "end_time": 48, "partition_ids": []}]) == "01020101243000"
    assert plan.partition_plan_hex(2, False, []) == "01020000"


def test_parse_schedule_prefers_plan_v2_and_names_zones():
    set_list = {
        "plan": [{"day": 2, "open": 1, "period": [[0, 4]]}],
        "workPlanV2": [
            {"day": 2, "open": "01", "period": [{"start_time": 36, "end_time": 48, "partition_ids": [1]},
                                                {"start_time": 56, "end_time": 64, "partition_ids": []}]},
            {"day": 3, "open": 0, "period": []},
        ],
    }
    out = plan.parse_schedule(set_list, {1: "Vorgarten"})
    assert out["monday"]["enabled"] is True
    assert out["monday"]["periods"][0] == {"start": "09:00", "end": "12:00", "zones": [1]}
    assert out["monday"]["text"] == "09:00–12:00 Vorgarten, 14:00–16:00 alle Zonen"
    assert out["tuesday"] == {"enabled": False, "periods": [], "text": "aus"}
    assert set(out) == set(plan.WEEKDAYS)
    assert plan.parse_schedule(None, {})["sunday"]["text"] == "aus"


def test_parse_schedule_empty_v2_list_does_not_fall_back_to_plan():
    set_list = {"workPlanV2": [], "plan": [{"day": 2, "open": 1, "period": [[36, 48]]}]}
    out = plan.parse_schedule(set_list, {})
    assert out["monday"]["enabled"] is False

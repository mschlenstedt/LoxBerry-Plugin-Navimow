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


# --- Final-Review-Fixwelle ---------------------------------------------------

def test_hhmm_to_slot_end_midnight():
    assert plan.hhmm_to_slot("24:00", end=True) == 96
    assert plan.hhmm_to_slot("00:00", end=True) == 96
    assert plan.hhmm_to_slot("00:00") == 0
    with pytest.raises(plan.PlanError):
        plan.hhmm_to_slot("24:00")
    with pytest.raises(plan.PlanError):
        plan.hhmm_to_slot("24:15", end=True)


def test_build_schedule_end_midnight():
    payload = {"day": "monday", "periods": [{"start": "22:00", "end": "00:00"}]}
    assert plan.build_schedule(payload, []) == (
        2, True, [{"start_time": 88, "end_time": 96, "partition_ids": []}])


CURRENT = {"enabled": True, "text": "x",
           "periods": [{"start": "09:00", "end": "12:00", "zones": [1]}, {"start": "22:00", "end": "24:00", "zones": []}]}


def test_build_schedule_without_periods_keeps_current_windows():
    day, enabled, periods = plan.build_schedule({"day": "monday", "enabled": False}, [1], current_day=CURRENT)
    assert (day, enabled) == (2, False)
    assert periods == [{"start_time": 36, "end_time": 48, "partition_ids": [1]},
                       {"start_time": 88, "end_time": 96, "partition_ids": []}]


def test_build_schedule_without_periods_needs_current_plan():
    with pytest.raises(plan.PlanError, match="noch nicht gelesen"):
        plan.build_schedule({"day": "monday", "enabled": False}, [1])


def test_build_schedule_explicit_empty_periods_clears():
    assert plan.build_schedule({"day": "monday", "periods": []}, [], current_day=CURRENT) == (2, True, [])


def test_build_schedule_overlap_allowed_when_disabled():
    payload = {"day": "monday", "enabled": False,
               "periods": [{"start": "09:00", "end": "12:00"}, {"start": "10:00", "end": "13:00"}]}
    day, enabled, periods = plan.build_schedule(payload, [])
    assert enabled is False and len(periods) == 2
    with pytest.raises(plan.PlanError, match="überlappen"):
        plan.build_schedule({**payload, "enabled": True}, [])


def test_build_schedule_zones_need_known_map():
    payload = {"day": "monday", "periods": [{"start": "09:00", "end": "12:00", "zones": [1]}]}
    with pytest.raises(plan.PlanError, match="Karte ist noch nicht gelesen"):
        plan.build_schedule(payload, [])
    assert plan.build_schedule({"day": "monday", "periods": [{"start": "09:00", "end": "12:00"}]}, [])[2]


def test_as_float_rejects_non_finite():
    assert plan._as_float("nan") is None
    assert plan._as_float(float("inf")) is None
    assert plan._as_float("12.5") == 12.5


def test_partition_plan_hex_two_periods_two_zones():
    # Tag 1, an, 2 Perioden:
    # 01 01 01 02 | 24 30 02 0500 0100 | 38 40 01 0201
    # (36=09:00, 48=12:00, Zonen 5 und 1 als LE-uint16; 56=14:00, 64=16:00, Zone 258=0x0102 -> 02 01)
    got = plan.partition_plan_hex(1, True, [
        {"start_time": 36, "end_time": 48, "partition_ids": [5, 1]},
        {"start_time": 56, "end_time": 64, "partition_ids": [258]}])
    assert got == "01010102" "243002" "05000100" "384001" "0201"


def test_parse_schedule_non_list_partition_ids():
    parsed = plan.parse_schedule({"plan_v2": [{"day": 2, "open": 1, "period": [
        {"start_time": 36, "end_time": 48, "partition_ids": 5}]}]}, {})
    assert parsed["monday"]["periods"] == [{"start": "09:00", "end": "12:00", "zones": []}]


RAW_COVERAGE = [
    {"area": 40.0, "endTime": 1700003600, "endTimeAlias": 9, "finishedArea": 40.0, "partitionId": 1,
     "partitionPercentage": 100, "startTime": 1700000000},
    {"area": 60.0, "endTime": 1700007200, "finishedArea": 27.0, "partitionId": 2,
     "partitionPercentage": 45, "startTime": 1700003700},
]


def test_parse_coverage_sums_and_names_zones():
    c = plan.parse_coverage(RAW_COVERAGE, {1: "Vorne", 2: "Hinten"})
    assert c["overall_pct"] == 67 and c["total_area"] == 100.0 and c["finished_area"] == 67.0
    assert c["start"] == 1700000000 and c["end"] == 1700007200
    assert c["zones"][1] == {"id": 2, "name": "Hinten", "area": 60.0, "finished": 27.0, "pct": 45,
                             "start": 1700003700, "end": 1700007200}


def test_parse_coverage_tolerates_odd_input():
    assert plan.parse_coverage(None, {}) is None
    assert plan.parse_coverage([], {}) is None
    assert plan.parse_coverage([{"area": 5}, "x"], {}) is None          # ohne partitionId nichts verwertbar
    c = plan.parse_coverage([{"partitionId": "7", "partitionPercentage": "130", "area": "nan"}], {})
    z = c["zones"][0]
    assert z["name"] == "Zone 7" and z["pct"] == 100 and z["area"] is None
    assert c["overall_pct"] is None and c["total_area"] == 0 and c["start"] is None
    assert plan.parse_coverage([{"partitionId": 3, "partitionPercentage": "viel"}], {})["zones"][0]["pct"] is None


def test_coverage_payload_flat_keys_for_loxone():
    p = plan.coverage_payload(plan.parse_coverage(RAW_COVERAGE, {1: "Vorne"}))
    assert p["count"] == 2 and p["zone_1_pct"] == 100 and p["zone_2_pct"] == 45
    assert p["text"] == "Vorne 100 %, Zone 2 45 %"
    assert p["overall_pct"] == 67 and len(p["list"]) == 2 and "zones" not in p


def test_seconds_to_next_start_today_tomorrow_and_disabled():
    from datetime import datetime
    sched = {"monday": {"enabled": True, "periods": [{"start": "11:00"}, {"start": "09:00"}]},
             "tuesday": {"enabled": True, "periods": [{"start": "08:30"}]},
             "sunday": {"enabled": False, "periods": [{"start": "10:00"}]}}
    monday_0850 = datetime(2026, 10, 5, 8, 50)
    assert plan.seconds_to_next_start(sched, monday_0850) == 600
    assert plan.seconds_to_next_start(sched, datetime(2026, 10, 5, 12, 0)) == (20 * 60 + 30) * 60
    assert plan.seconds_to_next_start(sched, datetime(2026, 10, 4, 9, 0)) == 24 * 3600   # Sonntag aus -> Montag 09:00
    assert plan.seconds_to_next_start({"monday": {"enabled": True, "periods": [{"start": "kaputt"}]}}, monday_0850) is None
    assert plan.seconds_to_next_start(None, monday_0850) is None

from navimow_unofficial_login import _match_devices, _resolve_mapping, _vehicle_list


def test_vehicle_list_keeps_name_model_and_skips_entries_without_sn():
    raw = [{"vehicle_sn": "SN1", "vehicle_type": 1, "vehicle_name": "Garten", "subType": "i215"}, {"vehicle_type": 2}]

    assert _vehicle_list(raw) == [{"vehicle_sn": "SN1", "vehicle_type": 1, "name": "Garten", "model": "i215"}]


def test_resolve_mapping_keeps_manual_mapping_when_ambiguous():
    official = [{"device_id": "a"}]
    unofficial = [{"vehicle_sn": "SN1", "vehicle_type": 1}, {"vehicle_sn": "SN2", "vehicle_type": 1}]
    existing = [{"device_id": "a", "vehicle_sn": "SN2", "vehicle_type": 1}]

    assert _resolve_mapping(official, unofficial, existing) == existing


def test_resolve_mapping_drops_mapping_for_vanished_mower():
    official = [{"device_id": "a"}]
    unofficial = [{"vehicle_sn": "SN1", "vehicle_type": 1}, {"vehicle_sn": "SN3", "vehicle_type": 1}]
    existing = [{"device_id": "a", "vehicle_sn": "SN2", "vehicle_type": 1}]

    assert _resolve_mapping(official, unofficial, existing) == []


def test_match_devices_single_on_both_sides():
    official = [{"device_id": "abc123", "name": "Mein Mäher"}]
    unofficial = [{"vehicle_sn": "SN000999", "vehicle_type": 160000001}]

    matched = _match_devices(official, unofficial)

    assert matched == [{"device_id": "abc123", "vehicle_sn": "SN000999", "vehicle_type": 160000001}]


def test_match_devices_ambiguous_returns_empty():
    official = [{"device_id": "a"}, {"device_id": "b"}]
    unofficial = [{"vehicle_sn": "SN1", "vehicle_type": 1}, {"vehicle_sn": "SN2", "vehicle_type": 1}]

    matched = _match_devices(official, unofficial)

    assert matched == []


def test_match_devices_empty_unofficial_list():
    official = [{"device_id": "a"}]
    assert _match_devices(official, []) == []

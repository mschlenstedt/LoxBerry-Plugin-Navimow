from navimow_unofficial_login import _match_devices


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

import navimow_unofficial_fault as fl


def test_state_code_and_detail_trigger():
    assert fl.state_code({"vehicle_state": "0101"}) == "0101"
    assert fl.state_code({"vehicleState": " 0310 "}) == "0310"
    assert fl.state_code(None) == ""
    assert not fl.needs_fault_detail({"vehicle_state": "0210"})
    assert fl.needs_fault_detail({"vehicle_state": "0310"})
    assert fl.needs_fault_detail({"vehicle_state": "0101", "error_data": [{"code": 6007}]})


def test_collect_codes_walks_any_shape():
    out = []
    fl.collect_codes({"list": [{"errorCode": "6004"}, {"hint_code": 6005}, {"x": {"code": "6004"}}], "msg": "y"}, out)
    assert out == ["6004", "6005"]


def test_parse_fault_known_code_in_german_with_hint():
    f = fl.parse_fault({"vehicle_state": "0310"}, {"data": [{"errorCode": "6004"}]})
    assert f["active"] is True and f["codes"] == ["6004"]
    assert f["text"].startswith("Findet den Weg zur Ladestation nicht")
    assert "STOP" in f["text"] and f["state_text"] == "Gestoppt (Fehler)"


def test_parse_fault_unknown_code_stays_visible_and_inline_fallback():
    f = fl.parse_fault({"vehicle_state": "0101", "error_data": [{"code": 9876}]}, "komprimiert")
    assert f["active"] is True and f["codes"] == ["9876"] and f["text"] == "Fehler 9876"


def test_parse_fault_without_code_still_reports_fault():
    f = fl.parse_fault({"vehicle_state": "0399"}, {})
    assert f["active"] is True and f["codes"] == []
    assert f["text"] == "Gestoppt mit Fehler, der Mäher nennt keinen Code"


def test_parse_fault_all_clear():
    f = fl.parse_fault({"vehicle_state": "0101"}, {})
    assert f == {"active": False, "codes": [], "text": "", "state_code": "0101", "state_text": "In der Station"}
    assert fl.fault_payload(f) == {"active": 0, "codes": "", "text": "", "state_code": "0101", "state_text": "In der Station"}


def test_charging_states_are_known():
    assert not fl.needs_fault_detail({"vehicle_state": "0202"})
    assert not fl.needs_fault_detail({"vehicle_state": "0221"})
    assert fl.parse_fault({"vehicle_state": "0202"}, {})["state_text"] == "Lädt in der Station"
    assert fl.parse_fault({"vehicle_state": "0221"}, {})["state_text"] == "Rückfahrt pausiert"


def test_collect_codes_ignores_zero():
    out = []
    fl.collect_codes({"errorCode": 0, "list": [{"code": "0"}, {"code": "0000"}, {"code": "00"}, {"code": "6004"}]}, out)
    assert out == ["6004"]
    assert fl.parse_fault({"vehicle_state": "0101"}, {"errorCode": 0})["active"] is False


def test_resume_hint_only_for_navigation_codes():
    assert "STOP" in fl.parse_fault({"vehicle_state": "0310"}, {"errorCode": "6004"})["text"]
    f = fl.parse_fault({"vehicle_state": "0310"}, {"errorCode": "1024"})
    assert f["text"] == "Akku zu heiß"

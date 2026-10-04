import pytest

import navimow_unofficial_settings as st

SET_LIST = {"data": {"settings": {
    "nightMowSwitch": "01", "rainSensor": "00", "soundSwitch": 1, "startPlan": "1",
    "tractionControl": 0, "returnBatteryLevel": 15, "chargingLimit": 100,
    "delayedPileSet": "0C", "nightLightLevel": 1, "height": "60", "liftSwitch": "kaputt",
}}}


def test_table_is_consistent():
    assert len(st.SETTINGS) == 26
    assert set(st.BY_NAME) == {s.name for s in st.SETTINGS}
    assert st.BY_NAME["traction_control"].robot_key == "tcsSwitch"
    assert st.BY_NAME["cut_height_mm"].robot_hex is False


def test_find_is_depth_first_first_match():
    assert st.find({"a": {"b": 1}, "c": {"b": 2}}, "b") == 1
    assert st.find([{"x": None}, {"x": 3}], "x") == 3
    assert st.find({}, "x") is None


def test_parse_settings_reads_only_reported_values():
    s = st.parse_settings(SET_LIST)
    assert s == {
        "night_mow": True, "rain_sensor": False, "sound": True, "schedule_enabled": True,
        "traction_control": False, "return_battery_level": 15, "charging_limit": 100,
        "rain_delay_hours": 3, "night_light_level": "very_dim", "cut_height_mm": 60,
    }


def test_parse_settings_rain_delay_decimal_and_fraction():
    assert st.parse_settings({"delayedPileSet": "12"})["rain_delay_hours"] == 3
    assert st.parse_settings({"delayedPileSet": 6})["rain_delay_hours"] == 1.5
    assert st.parse_settings(None) == {}


def test_settings_payload_for_loxone():
    p = st.settings_payload(st.parse_settings(SET_LIST))
    assert p["night_mow"] == 1 and p["rain_sensor"] == 0
    assert p["night_light_level"] == 1 and p["night_light_level_text"] == "stark gedimmt"
    assert p["rain_delay_hours"] == 3 and p["cut_height_mm"] == 60
    assert "lift_alarm" not in p


CURRENT = {"sound": True, "schedule_enabled": True, "traction_control": False, "rain_sensor": True,
           "return_battery_level": 15, "charging_limit": 100, "rain_delay_hours": 3,
           "night_light_level": "dim", "weather_sensitivity": "light", "cut_height_mm": 60,
           "obstacle_avoidance": True}
DEVICE = {"model": "i215", "cut_height_options": [30, 40, 50, 60, 70], "cut_height_flag": True,
          "limits": {"return_battery_level": (10, 20), "charging_limit": (70, 100)}}
DEVICE_I1 = {"model": "i105", "cut_height_options": [20, 30, 40, 50, 60], "cut_height_flag": False, "limits": {}}
DEVICE_X3 = {"model": "X315", "cut_height_options": [], "cut_height_flag": True, "limits": {}}


def test_parse_device_reads_capabilities():
    info = {"data": {"model": "i215", "mowingHeightList": ["40", 30, "x", 30], "isCutterHeight": 1,
                     "batteryConfig": {"returnBatteryLevelMin": 10, "returnBatteryLevelMax": 20,
                                       "chargingLimitMin": 70}}}
    assert st.parse_device(info) == {"model": "i215", "cut_height_options": [30, 40], "cut_height_flag": True,
                                     "limits": {"return_battery_level": (10, 20)}}
    assert st.parse_device(None, "i105")["model"] == "i105"
    assert st.parse_device({"mowingHeightList": "30,40"})["cut_height_options"] == []


def test_model_family_rules():
    assert st.model_lacks("i105", "cut_height_mm") and st.model_lacks("I108E", "cut_height_mm")
    assert st.model_lacks("X315", "charging_limit") and not st.model_lacks("i215", "cut_height_mm")
    assert st.cut_height_writable(DEVICE) and not st.cut_height_writable(DEVICE_I1)
    assert st.cut_height_writable({"model": "H500", "cut_height_options": [20, 30], "cut_height_flag": False, "limits": {}})
    assert not st.cut_height_writable({"model": "H500", "cut_height_options": [20], "cut_height_flag": False, "limits": {}})
    assert not st.cut_height_writable(None)


def test_device_payload():
    assert st.device_payload(DEVICE) == {"cut_height_writable": 1, "cut_height_options": "30,40,50,60,70"}
    assert st.device_payload(DEVICE_I1)["cut_height_writable"] == 0


@pytest.mark.parametrize("payload,robot,cloud,iot", [
    ({"key": "sound", "value": 1}, {"soundSwitch": 1}, {"soundSwitch": "1"}, True),
    ({"key": "schedule_enabled", "value": "aus"}, {"startPlan": "0"}, {"startPlan": "0"}, True),
    ({"key": "traction_control", "value": True}, {"tcsSwitch": 1}, {"tractionControl": 1}, True),
    ({"key": "rain_sensor", "value": "0"}, None, {"rainSensor": "00"}, False),
    ({"key": "return_battery_level", "value": 20}, {"returnBatteryLevel": "14"}, {"returnBatteryLevel": 20}, True),
    ({"key": "charging_limit", "value": "85"}, {"chargingLimit": "55"}, {"chargingLimit": 85}, True),
    ({"key": "rain_delay_hours", "value": 3}, {"delayedPileSet": "0C"}, {"delayedPileSet": "0C"}, True),
    ({"key": "cut_height_mm", "value": "50"}, {"height": "50"}, {"height": 50}, True),
    ({"key": "night_light_level", "value": "very_dim"}, {"nightLightLevel": "01"}, {"nightLightLevel": 1}, True),
    ({"key": "weather_sensitivity", "value": 2}, {"weatherSensitivity": 2}, {"weatherSensitivity": 2}, True),
    ({"key": "Animal_Protection", "value": "an"}, {"animalProtection": 1}, {"animalProtection": 1}, True),
])
def test_build_setting_encodes_per_channel(payload, robot, cloud, iot):
    w = st.build_setting(payload, CURRENT, DEVICE)
    assert (w.robot, w.cloud, w.iot) == (robot, cloud, iot)


def test_build_setting_cut_height_without_list_uses_default_range():
    device = {"model": "H500", "cut_height_options": [], "cut_height_flag": True, "limits": {}}
    assert st.build_setting({"key": "cut_height_mm", "value": 65}, CURRENT, device).cloud == {"height": 65}
    with pytest.raises(st.SettingError):
        st.build_setting({"key": "cut_height_mm", "value": 42}, CURRENT, device)


@pytest.mark.parametrize("payload,current,device,needle", [
    ({"key": "turbo", "value": 1}, CURRENT, DEVICE, "Unbekannte Einstellung"),
    ({"key": "frost_delay", "value": 1}, CURRENT, DEVICE, "meldet dieser Mäher nicht"),
    ({"key": "sound", "value": 1}, None, DEVICE, "noch nicht gelesen"),
    ({"key": "sound", "value": 1}, {}, DEVICE, "noch nicht gelesen"),
    ({"key": "return_battery_level", "value": 25}, CURRENT, DEVICE, "10 bis 20"),
    ({"key": "return_battery_level", "value": 55}, CURRENT, None, "5 bis 50"),
    ({"key": "return_battery_level", "value": 17}, CURRENT, None, "Schritten von 5"),
    ({"key": "sound", "value": "vielleicht"}, CURRENT, DEVICE, "Ungültiger Wert"),
    ({"key": "sound"}, CURRENT, DEVICE, "Ungültiger Wert"),
    ({"key": "weather_sensitivity", "value": "sturm"}, CURRENT, DEVICE, "drizzle"),
    ({"key": "animal_protection", "value": 1}, {"sound": True}, DEVICE, "meldet dieser Mäher nicht"),
    ({"key": "cut_height_mm", "value": 50}, CURRENT, DEVICE_I1, "nicht per Befehl"),
    ({"key": "cut_height_mm", "value": 50}, CURRENT, None, "noch nicht gelesen"),
    ({"key": "cut_height_mm", "value": 55}, CURRENT, DEVICE, "30, 40, 50, 60, 70"),
    ({"key": "charging_limit", "value": 80}, CURRENT, DEVICE_X3, "hat dieses Modell nicht"),
])
def test_build_setting_refuses(payload, current, device, needle):
    with pytest.raises(st.SettingError) as err:
        st.build_setting(payload, current, device)
    assert needle in str(err.value)

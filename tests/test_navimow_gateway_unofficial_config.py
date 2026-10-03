import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import navimow_gateway as gw  # noqa: E402


def test_load_plugin_config_has_unofficial_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "PLUGIN_CFG", tmp_path / "pluginconfig.json")

    cfg = gw.load_plugin_config()

    assert cfg["unofficial_enabled"] is False
    assert cfg["unofficial_region"] == ""
    assert cfg["unofficial_uuid"] == ""
    assert cfg["unofficial_refresh_token"] == ""
    assert cfg["unofficial_uid"] == ""
    assert cfg["unofficial_host"] == ""
    assert cfg["unofficial_devices"] == []
    assert cfg["unofficial_vehicles"] == []
    assert cfg["unofficial_access_token"] == ""
    # Stabile Client-Geräte-ID wird beim ersten Laden generiert und persistiert.
    assert len(cfg["unofficial_client_device_id"]) == 32


def test_unofficial_client_device_id_stays_stable_across_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "PLUGIN_CFG", tmp_path / "pluginconfig.json")

    first = gw.load_plugin_config()
    second = gw.load_plugin_config()

    assert first["unofficial_client_device_id"] == second["unofficial_client_device_id"]


def test_unofficial_access_token_survives_restart(tmp_path, monkeypatch):
    # Der Passport-Refresh beim Gateway-Start braucht den Access-Token.
    monkeypatch.setattr(gw, "PLUGIN_CFG", tmp_path / "pluginconfig.json")
    cfg = gw.load_plugin_config()
    cfg["unofficial_access_token"] = "AT"
    cfg["unofficial_refresh_token"] = "RT"
    gw.save_plugin_config(cfg)

    reloaded = gw.load_plugin_config()

    assert reloaded["unofficial_access_token"] == "AT"
    assert reloaded["unofficial_refresh_token"] == "RT"
    # Der offizielle Access-Token bleibt weiterhin nur im RAM.
    assert reloaded["access_token"] == ""


def test_store_unofficial_tokens_writes_only_on_change(tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "PLUGIN_CFG", tmp_path / "pluginconfig.json")
    cfg = gw.load_plugin_config()
    tokens = SimpleNamespace(access_token="AT", refresh_token="RT", uuid="U", region="fra")
    writes = []
    monkeypatch.setattr(gw, "save_plugin_config", lambda c: writes.append(dict(c)))

    gw._store_unofficial_tokens(cfg, tokens)
    gw._store_unofficial_tokens(cfg, tokens)

    assert len(writes) == 1
    assert cfg["unofficial_access_token"] == "AT"


def test_unofficial_status_payload_reports_error_and_since(monkeypatch):
    gw._set_unofficial_session(False, "90002: args missing")
    gw._update_unofficial_auth_status({"unofficial_enabled": True}, "navimow")
    failed = dict(gw._unofficial_auth_payload)

    gw._set_unofficial_session(True)
    gw._update_unofficial_auth_status({"unofficial_enabled": True}, "navimow")
    ok = dict(gw._unofficial_auth_payload)

    assert failed["topic"] == "navimow/gateway_unofficial"
    assert failed["authenticated"] is False and failed["error"] == "90002: args missing"
    assert failed["since"] == 0 and failed["enabled"] is True and failed["ts"] > 0
    assert ok["authenticated"] is True and ok["error"] == "" and ok["since"] > 0

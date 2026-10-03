import json
import sys
from pathlib import Path

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
    # Stabile Client-Geräte-ID wird beim ersten Laden generiert und persistiert.
    assert len(cfg["unofficial_client_device_id"]) == 32
    # Ephemer: nie aus der Datei gelesen, immer leer im frischen Prozess.
    assert cfg["unofficial_access_token"] == ""


def test_unofficial_client_device_id_stays_stable_across_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "PLUGIN_CFG", tmp_path / "pluginconfig.json")

    first = gw.load_plugin_config()
    second = gw.load_plugin_config()

    assert first["unofficial_client_device_id"] == second["unofficial_client_device_id"]


def test_save_plugin_config_never_persists_unofficial_access_token(tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "PLUGIN_CFG", tmp_path / "pluginconfig.json")
    cfg = gw.load_plugin_config()
    cfg["unofficial_access_token"] = "SHOULD-NOT-BE-SAVED"
    cfg["unofficial_refresh_token"] = "keep-me"

    gw.save_plugin_config(cfg)

    on_disk = json.loads((tmp_path / "pluginconfig.json").read_text())
    assert "unofficial_access_token" not in on_disk
    assert on_disk["unofficial_refresh_token"] == "keep-me"

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import navimow_gateway as gw  # noqa: E402


def test_load_plugin_config_has_private_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "PLUGIN_CFG", tmp_path / "pluginconfig.json")

    cfg = gw.load_plugin_config()

    assert cfg["private_enabled"] is False
    assert cfg["private_region"] == ""
    assert cfg["private_uuid"] == ""
    assert cfg["private_refresh_token"] == ""
    assert cfg["private_uid"] == ""
    assert cfg["private_host"] == ""
    assert cfg["private_devices"] == []
    # Stabile Client-Geraete-ID wird beim ersten Laden generiert und persistiert.
    assert len(cfg["private_client_device_id"]) == 32
    # Ephemer: nie aus der Datei gelesen, immer leer im frischen Prozess.
    assert cfg["private_access_token"] == ""


def test_private_client_device_id_stays_stable_across_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "PLUGIN_CFG", tmp_path / "pluginconfig.json")

    first = gw.load_plugin_config()
    second = gw.load_plugin_config()

    assert first["private_client_device_id"] == second["private_client_device_id"]


def test_save_plugin_config_never_persists_private_access_token(tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "PLUGIN_CFG", tmp_path / "pluginconfig.json")
    cfg = gw.load_plugin_config()
    cfg["private_access_token"] = "SHOULD-NOT-BE-SAVED"
    cfg["private_refresh_token"] = "keep-me"

    gw.save_plugin_config(cfg)

    on_disk = json.loads((tmp_path / "pluginconfig.json").read_text())
    assert "private_access_token" not in on_disk
    assert on_disk["private_refresh_token"] == "keep-me"

from gnomilestone import settings


def test_read_settings_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    assert settings.read_settings() == {}


def test_write_then_read_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    settings.write_settings({"language": "en", "dark_mode": True})
    assert settings.read_settings() == {"language": "en", "dark_mode": True}


def test_read_settings_corrupt_file_returns_empty_dict(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    assert settings.read_settings() == {}

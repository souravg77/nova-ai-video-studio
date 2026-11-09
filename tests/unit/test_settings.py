"""Persistent settings: safe defaults, corrupt-file recovery, no secrets on disk."""
import json

from nova_studio import config
from nova_studio.settings import (AppSettings, gemini_api_key, load_settings,
                                  save_settings, settings_path)


def test_defaults_are_private_and_local(tmp_path):
    s = load_settings(tmp_path)
    assert s.first_run_complete is False
    assert s.cloud.gemini_enabled is False
    assert s.cloud.gemini_model == "gemini-omni-1.1-flash"
    assert s.local_video.experimental_preview_enabled is False
    assert s.models_dir is None


def test_roundtrip_is_atomic(tmp_path):
    s = AppSettings(first_run_complete=True, models_dir=str(tmp_path / "m"))
    s.cloud.gemini_enabled = True
    save_settings(tmp_path, s)
    assert not list(tmp_path.glob("*.tmp"))
    assert load_settings(tmp_path) == s


def test_corrupt_file_is_set_aside_not_deleted(tmp_path):
    settings_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert load_settings(tmp_path) == AppSettings()
    kept = tmp_path / "settings.json.corrupt"
    assert kept.read_text(encoding="utf-8") == "{not json"


def test_wrong_shape_is_set_aside(tmp_path):
    settings_path(tmp_path).write_text("[1, 2]", encoding="utf-8")
    assert load_settings(tmp_path) == AppSettings()
    assert (tmp_path / "settings.json.corrupt").exists()


def test_models_dir_setting_moves_models_folder(tmp_path, monkeypatch):
    ws, models = tmp_path / "ws", tmp_path / "big-drive" / "models"
    monkeypatch.setenv("NOVA_STUDIO_HOME", str(ws))
    save_settings(ws, AppSettings(models_dir=str(models)))
    cfg = config.default_config()
    assert cfg.paths.models == models.resolve()
    assert models.is_dir()
    assert cfg.paths.projects == ws.resolve() / "projects"


def test_gemini_key_only_from_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("NOVA_GEMINI_API_KEY", raising=False)
    assert gemini_api_key() is None
    monkeypatch.setenv("NOVA_GEMINI_API_KEY", "  secret-key-123  ")
    assert gemini_api_key() == "secret-key-123"
    s = AppSettings()
    s.cloud.gemini_enabled = True
    save_settings(tmp_path, s)
    raw = settings_path(tmp_path).read_text(encoding="utf-8")
    assert "secret-key-123" not in raw
    assert not any("key" in k for k in json.loads(raw)["cloud"])

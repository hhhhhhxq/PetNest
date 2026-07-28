"""用户设置的持久化和恢复行为。"""

from __future__ import annotations

import json

from petnest.core.settings_manager import SettingsManager
from petnest.models.settings import Settings


def test_defaults_are_available_without_a_file(tmp_path) -> None:
    settings = SettingsManager(tmp_path / "settings.json").load()
    assert settings == Settings()


def test_settings_are_saved_and_loaded_atomically(tmp_path) -> None:
    path = tmp_path / "settings.json"
    manager = SettingsManager(path)
    manager.save(Settings(current_pet_id="sample", window_x=12, scale=1.2))
    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()
    assert SettingsManager(path).load().current_pet_id == "sample"


def test_corrupt_settings_are_backed_up_and_replaced_with_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ broken", encoding="utf-8")
    assert SettingsManager(path).load() == Settings()
    assert list(tmp_path.glob("settings.json.corrupt-*.bak"))


def test_old_settings_are_migrated_to_current_schema(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 1, "current_pet_id": "legacy", "scale": 1.5}), encoding="utf-8")
    settings = SettingsManager(path).load()
    assert settings.schema_version == Settings.SCHEMA_VERSION
    assert settings.current_pet_id == "legacy"
    assert settings.mouse_interaction_enabled is True


def test_saving_settings_removes_legacy_animation_overrides(tmp_path) -> None:
    path = tmp_path / "settings.json"
    manager = SettingsManager(path)
    path.write_text(json.dumps({
        "schema_version": 5,
        "animation_overrides": {"cat": {"idle": {"mode": "per_frame", "frame_durations_ms": [200, 80]}}},
    }), encoding="utf-8")

    manager.save(manager.load())

    assert "animation_overrides" not in json.loads(path.read_text(encoding="utf-8"))


def test_system_idle_thresholds_round_trip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    SettingsManager(path).save(Settings(system_idle_enabled=True, system_bored_seconds=30, system_sleep_seconds=180))

    loaded = SettingsManager(path).load()
    assert (loaded.system_idle_enabled, loaded.system_bored_seconds, loaded.system_sleep_seconds) == (True, 30, 180)

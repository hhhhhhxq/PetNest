"""用户设置的持久化和恢复行为。"""

from __future__ import annotations

import json

from petnest.core.settings_manager import SettingsManager
from petnest.models.settings import Settings


def test_defaults_are_available_without_a_file(tmp_path) -> None:
    settings = SettingsManager(tmp_path / "settings.json").load()
    assert settings == Settings()


def test_new_users_have_system_idle_actions_enabled_with_short_thresholds(tmp_path) -> None:
    settings = SettingsManager(tmp_path / "settings.json").load()

    assert (settings.system_idle_enabled, settings.system_bored_seconds, settings.system_sleep_seconds) == (True, 20, 35)


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


def test_custom_pets_root_round_trips(tmp_path) -> None:
    path = tmp_path / "settings.json"
    SettingsManager(path).save(Settings(pets_root="D:/PetNestPets"))

    assert SettingsManager(path).load().pets_root == "D:/PetNestPets"


def test_work_countdown_settings_round_trip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    SettingsManager(path).save(
        Settings(work_countdown_enabled=False, work_start_time="10:00", work_end_time="19:30")
    )

    loaded = SettingsManager(path).load()
    assert (loaded.work_countdown_enabled, loaded.work_start_time, loaded.work_end_time) == (False, "10:00", "19:30")


def test_version_7_countdown_migrates_to_weekday_schedule(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 7, "work_end_time": "18:30"}), encoding="utf-8")

    loaded = SettingsManager(path).load()

    assert loaded.daily_work_end_times == {
        "0": "18:30", "1": "18:30", "2": "18:30", "3": "18:30", "4": "18:30", "5": None, "6": None
    }


def test_version_8_adds_compact_countdown_card_layout_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 8}), encoding="utf-8")

    loaded = SettingsManager(path).load()

    assert (loaded.countdown_gap, loaded.countdown_width, loaded.countdown_height, loaded.countdown_theme) == (
        0, 132, 37, "cream"
    )


def test_countdown_theme_round_trips(tmp_path) -> None:
    path = tmp_path / "settings.json"
    SettingsManager(path).save(Settings(countdown_theme="night", countdown_width=142, countdown_height=32))

    loaded = SettingsManager(path).load()

    assert (loaded.countdown_theme, loaded.countdown_width, loaded.countdown_height) == ("night", 142, 32)


def test_mouse_follow_defaults_round_trip_and_migrate(tmp_path) -> None:
    path = tmp_path / "settings.json"
    manager = SettingsManager(path)

    assert (manager.load().mouse_follow_enabled, manager.load().mouse_follow_scale) == (False, 0.45)
    manager.save(Settings(mouse_follow_enabled=True, mouse_follow_scale=0.7))
    assert (manager.load().mouse_follow_enabled, manager.load().mouse_follow_scale) == (True, 0.7)

    path.write_text(json.dumps({"schema_version": 13, "mouse_follow_scale": 0.55}), encoding="utf-8")
    migrated = manager.load()
    assert (migrated.mouse_follow_enabled, migrated.mouse_follow_scale) == (False, 0.45)


def test_cursor_style_preferences_migrate_from_schema_14(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 14}), encoding="utf-8")

    loaded = SettingsManager(path).load()

    assert (loaded.cursor_style_enabled, loaded.cursor_style_id, loaded.cursor_restore_pending) == (False, None, False)


def test_nickname_and_device_id_are_persisted_and_added_by_schema_migration(tmp_path) -> None:
    path = tmp_path / "settings.json"
    manager = SettingsManager(path)
    manager.save(Settings(nickname="小平安", device_id="abcdef123456"))

    loaded = manager.load()
    assert (loaded.nickname, loaded.device_id) == ("小平安", "abcdef123456")

    path.write_text(json.dumps({"schema_version": 15}), encoding="utf-8")
    migrated = manager.load()
    assert migrated.schema_version == Settings.SCHEMA_VERSION
    assert migrated.nickname == ""
    assert migrated.device_id == ""


def test_lan_interaction_preference_round_trips_and_migrates(tmp_path) -> None:
    path = tmp_path / "settings.json"
    manager = SettingsManager(path)
    manager.save(Settings(lan_interaction_enabled=False))

    assert manager.load().lan_interaction_enabled is False

    path.write_text(json.dumps({"schema_version": 16}), encoding="utf-8")
    migrated = manager.load()
    assert migrated.schema_version == Settings.SCHEMA_VERSION
    assert migrated.lan_interaction_enabled is True


def test_remote_interaction_preference_round_trips_and_migrates(tmp_path) -> None:
    path = tmp_path / "settings.json"
    manager = SettingsManager(path)
    manager.save(Settings(remote_interaction_enabled=False))

    assert manager.load().remote_interaction_enabled is False

    path.write_text('{"schema_version": 17}', encoding="utf-8")
    migrated = manager.load()
    assert migrated.schema_version == Settings.SCHEMA_VERSION
    assert migrated.remote_interaction_enabled is True


def test_elastic_clock_in_defaults_are_available_and_round_trip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    manager = SettingsManager(path)

    defaults = manager.load()
    assert (defaults.cursor_scale, defaults.work_schedule_mode) == (100, "fixed")
    assert (defaults.clock_in_start_time, defaults.clock_in_end_time) == ("09:30", "10:00")
    assert (defaults.work_duration_minutes, defaults.clock_in_date, defaults.clock_in_time) == (540, None, None)

    manager.save(
        Settings(
            cursor_scale=125,
            work_schedule_mode="elastic",
            clock_in_start_time="09:30",
            clock_in_end_time="10:00",
            work_duration_minutes=540,
            clock_in_date="2026-08-13",
            clock_in_time="09:40",
        )
    )
    loaded = manager.load()
    assert (
        loaded.cursor_scale,
        loaded.work_schedule_mode,
        loaded.clock_in_start_time,
        loaded.clock_in_end_time,
        loaded.work_duration_minutes,
        loaded.clock_in_date,
        loaded.clock_in_time,
    ) == (125, "elastic", "09:30", "10:00", 540, "2026-08-13", "09:40")


def test_schema_18_migrates_new_settings_with_safe_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 18}), encoding="utf-8")

    loaded = SettingsManager(path).load()

    assert loaded.schema_version == Settings.SCHEMA_VERSION
    assert loaded.cursor_scale == 100
    assert loaded.work_schedule_mode == "fixed"
    assert loaded.clock_in_start_time == "09:30"
    assert loaded.clock_in_end_time == "10:00"
    assert loaded.work_duration_minutes == 540


def test_invalid_new_settings_fall_back_to_safe_defaults() -> None:
    loaded = Settings.from_dict(
        {
            "cursor_scale": 111,
            "work_schedule_mode": "daily-exceptions",
            "work_duration_minutes": 0,
        }
    )

    assert (loaded.cursor_scale, loaded.work_schedule_mode, loaded.work_duration_minutes) == (100, "fixed", 540)


def test_invalid_daily_work_schedule_falls_back_to_safe_weekday_values() -> None:
    loaded = Settings.from_dict(
        {
            "daily_work_end_times": {
                "0": "19:30",
                "1": "not-a-time",
                "5": None,
            }
        }
    )

    assert loaded.daily_work_end_times == {
        "0": "19:30",
        "1": "18:00",
        "2": "18:00",
        "3": "18:00",
        "4": "18:00",
        "5": None,
        "6": None,
    }

    malformed = Settings.from_dict({"daily_work_end_times": ["18:00"]})
    assert malformed.daily_work_end_times == {
        "0": "18:00",
        "1": "18:00",
        "2": "18:00",
        "3": "18:00",
        "4": "18:00",
        "5": None,
        "6": None,
    }

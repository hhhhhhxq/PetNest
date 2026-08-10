"""用户配置目录中的原子设置读写与版本迁移。"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from petnest.models.settings import Settings


class SettingsManager:
    """以可注入路径保存设置，避免写入应用安装目录。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.default_path()

    @staticmethod
    def default_path(app_name: str = "PetNest") -> Path:
        """返回当前平台惯用的用户配置路径。"""
        if sys.platform == "win32":
            root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        elif sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support"
        else:
            root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return root / app_name / "settings.json"

    def load(self) -> Settings:
        """读取、迁移设置；损坏文件会被保留为带时间戳的备份。"""
        if not self.path.exists():
            return Settings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("设置根节点必须为对象")
            migrated = self._migrate(raw)
            settings = Settings.from_dict(migrated)
            if migrated != raw:
                self.save(settings)
            return settings
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            self._backup_corrupt_file()
            return Settings()

    def save(self, settings: Settings) -> None:
        """通过同目录临时文件和 replace 原子写入设置。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        contents = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        try:
            temporary.write_text(contents + "\n", encoding="utf-8")
            with temporary.open("r+", encoding="utf-8") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
        version = raw.get("schema_version", 1)
        if not isinstance(version, int) or version < 1:
            raise ValueError("设置版本无效")
        if version > Settings.SCHEMA_VERSION:
            raise ValueError("设置版本高于当前程序")
        migrated = dict(raw)
        if version == 1:
            migrated.setdefault("mouse_interaction_enabled", True)
            migrated.setdefault("external_event_server_enabled", False)
            migrated.setdefault("external_event_port", 18486)
            migrated.setdefault("system_idle_enabled", False)
            migrated.setdefault("system_idle_seconds", 300)
            migrated.setdefault("run_at_startup", False)
            migrated["schema_version"] = 2
            version = 2
        if version == 2:
            migrated.setdefault("animation_overrides", {})
            migrated["schema_version"] = 3
            version = 3
        if version == 3:
            raw_overrides = migrated.get("animation_overrides")
            if isinstance(raw_overrides, dict):
                for actions in raw_overrides.values():
                    if not isinstance(actions, dict):
                        continue
                    for override in actions.values():
                        if isinstance(override, dict) and "mode" not in override:
                            override["mode"] = "per_frame" if override.get("frame_durations_ms") is not None else "total"
            migrated["schema_version"] = 4
            version = 4
        if version == 4:
            migrated.setdefault("system_bored_seconds", 30)
            migrated.setdefault("system_sleep_seconds", 180)
            migrated["schema_version"] = 5
            version = 5
        if version == 5:
            migrated.setdefault("pets_root", None)
            migrated["schema_version"] = 6
            version = 6
        if version == 6:
            migrated.setdefault("work_countdown_enabled", True)
            migrated.setdefault("work_start_time", "09:00")
            migrated.setdefault("work_end_time", "18:00")
            migrated["schema_version"] = Settings.SCHEMA_VERSION
            version = 7
        if version == 7:
            legacy_end = migrated.get("work_end_time", "18:00")
            migrated.setdefault(
                "daily_work_end_times",
                {"0": legacy_end, "1": legacy_end, "2": legacy_end, "3": legacy_end, "4": legacy_end, "5": None, "6": None},
            )
            migrated["schema_version"] = 8
            version = 8
        if version == 8:
            migrated.setdefault("countdown_gap", 8)
            migrated.setdefault("countdown_width", 190)
            migrated.setdefault("countdown_height", 48)
            migrated["schema_version"] = 9
            version = 9
        if version == 9:
            if (
                migrated.get("countdown_gap") == 8
                and migrated.get("countdown_width") == 190
                and migrated.get("countdown_height") == 48
            ):
                migrated["countdown_gap"] = 5
                migrated["countdown_width"] = 150
                migrated["countdown_height"] = 34
            migrated.setdefault("countdown_theme", "cream")
            migrated["schema_version"] = 10
            version = 10
        if version == 10:
            if (
                migrated.get("countdown_gap") == 5
                and migrated.get("countdown_width") == 150
                and migrated.get("countdown_height") == 34
            ):
                migrated["countdown_gap"] = 0
                migrated["countdown_width"] = 132
                migrated["countdown_height"] = 30
            migrated["schema_version"] = 11
            version = 11
        if version == 11:
            if migrated.get("countdown_width") == 132 and migrated.get("countdown_height") == 30:
                migrated["countdown_height"] = 37
            migrated["schema_version"] = 12
            version = 12
        if version == 12:
            migrated.setdefault("mouse_follow_enabled", False)
            migrated.setdefault("mouse_follow_scale", 0.55)
            migrated["schema_version"] = 13
            version = 13
        if version == 13:
            if migrated.get("mouse_follow_scale") == 0.55:
                migrated["mouse_follow_scale"] = 0.45
            migrated["schema_version"] = 14
            version = 14
        if version == 14:
            migrated.setdefault("cursor_style_enabled", False)
            migrated.setdefault("cursor_style_id", None)
            migrated.setdefault("cursor_restore_pending", False)
            migrated["schema_version"] = Settings.SCHEMA_VERSION
        return migrated

    def _backup_corrupt_file(self) -> None:
        if not self.path.exists():
            return
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}.bak")
        try:
            shutil.move(self.path, backup)
        except OSError:
            # 不能恢复配置时仍返回默认值；下一次写入会重新创建设置文件。
            pass

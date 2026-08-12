"""设置中心兼容入口。

历史版本从本模块导入 ``SettingsDialog``；保留该名称，实际实现统一使用
``SettingsCenterDialog``，避免旧插件或外部调用者因为模块迁移而失效。
"""

from .settings_center_dialog import SettingsCenterDialog

SettingsDialog = SettingsCenterDialog

__all__ = ["SettingsCenterDialog", "SettingsDialog"]

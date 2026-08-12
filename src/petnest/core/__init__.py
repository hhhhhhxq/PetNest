"""PetNest 的独立核心逻辑。

公开名称按需导入，避免只使用更新器等轻量模块时加载 Qt、Pillow 和动画库。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "AnimationActionSyncError": ("animation_action_synchronizer", "AnimationActionSyncError"),
    "AnimationActionSyncResult": ("animation_action_synchronizer", "AnimationActionSyncResult"),
    "AnimationActionSynchronizer": ("animation_action_synchronizer", "AnimationActionSynchronizer"),
    "AnimationPlayer": ("animation_player", "AnimationPlayer"),
    "EffectCatalog": ("lottie_effects", "EffectCatalog"),
    "EffectImportError": ("lottie_effects", "EffectImportError"),
    "EffectImportResult": ("lottie_effects", "EffectImportResult"),
    "EffectManifest": ("lottie_effects", "EffectManifest"),
    "EventBus": ("event_bus", "EventBus"),
    "FirebaseConfig": ("remote_interaction_service", "FirebaseConfig"),
    "FirebaseRemoteInteractionService": ("remote_interaction_service", "FirebaseRemoteInteractionService"),
    "FallbackResolver": ("fallback_resolver", "FallbackResolver"),
    "LottieEffectImporter": ("lottie_effects", "LottieEffectImporter"),
    "LottieEffectInfo": ("lottie_effects", "LottieEffectInfo"),
    "LanInteractionService": ("lan_service", "LanInteractionService"),
    "LanPacketCodec": ("lan_interaction", "LanPacketCodec"),
    "LanProtocolError": ("lan_interaction", "LanProtocolError"),
    "PackageLoader": ("package_loader", "PackageLoader"),
    "PackageValidationError": ("package_validator", "PackageValidationError"),
    "PackageValidator": ("package_validator", "PackageValidator"),
    "PetStateMachine": ("state_machine", "PetStateMachine"),
    "ReceivedInteraction": ("lan_interaction", "ReceivedInteraction"),
    "SettingsManager": ("settings_manager", "SettingsManager"),
    "SpriteSheetImporter": ("spritesheet_importer", "SpriteSheetImporter"),
    "SyncedAction": ("animation_action_synchronizer", "SyncedAction"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute)
    globals()[name] = value
    return value

"""命令行入口的安装器与 Codex Hook 辅助命令测试。"""

import io
from pathlib import Path
import sys

import petnest.__main__ as main_module
from petnest.__main__ import main
from petnest.core.settings_manager import SettingsManager


def test_set_pets_root_persists_an_absolute_custom_library(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(SettingsManager, "default_path", staticmethod(lambda app_name="PetNest": settings_path))

    assert main(["--set-pets-root", str(tmp_path / "D" / "PetNestPets")]) == 0

    assert SettingsManager(settings_path).load().pets_root == str((tmp_path / "D" / "PetNestPets").resolve())


def test_codex_hook_bridge_runs_before_qt_and_single_instance(tmp_path: Path, monkeypatch) -> None:
    metadata_path = tmp_path / "codex-link.json"
    raw = b'{"hook_event_name":"Stop","session_id":"s","turn_id":"t"}'
    calls: list[tuple[Path, bytes]] = []

    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    monkeypatch.setattr(
        main_module,
        "forward_codex_hook",
        lambda path, body: calls.append((path, body)) or True,
        raising=False,
    )
    monkeypatch.setattr(
        main_module,
        "QApplication",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应创建 QApplication")),
    )

    assert main(["--codex-hook", str(metadata_path)]) == 0
    assert calls == [(metadata_path.resolve(), raw)]


def test_firewall_helper_runs_before_qt_when_frozen_on_windows(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "PetNest.exe"
    calls: list[Path] = []
    monkeypatch.setattr(main_module.sys, "platform", "win32")
    monkeypatch.setattr(main_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main_module.sys, "executable", str(executable))
    monkeypatch.setattr(
        main_module,
        "configure_public_firewall_rules",
        lambda path: calls.append(path) or 7,
        raising=False,
    )
    monkeypatch.setattr(
        main_module,
        "QApplication",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应创建 QApplication")),
    )

    assert main(["--configure-lan-firewall-public"]) == 7
    assert calls == [executable]


def test_firewall_helper_rejects_developer_mode(monkeypatch) -> None:
    monkeypatch.setattr(main_module.sys, "platform", "win32")
    monkeypatch.delattr(main_module.sys, "frozen", raising=False)

    assert main(["--configure-lan-firewall-public"]) == 2

"""PetNest Codex 插件的安全安装与状态检测测试。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from petnest.core.codex_link import CodexHookManager
from petnest.core.codex_plugin import CodexPluginManager, locate_codex_cli


PLUGIN_NAME = "petnest-status-link"
PLUGIN_EVENTS = {"UserPromptSubmit", "PermissionRequest", "PostToolUse", "Stop"}


class FakeCodexCli:
    def __init__(
        self,
        *,
        installed: bool = False,
        enabled: bool = True,
        add_exit_code: int = 0,
        marketplace_name: str = "personal",
    ) -> None:
        self.installed = installed
        self.enabled = enabled
        self.add_exit_code = add_exit_code
        self.marketplace_name = marketplace_name
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, arguments: tuple[str, ...]) -> tuple[int, str, str]:
        self.calls.append(arguments)
        if arguments == ("plugin", "list", "--json"):
            installed = []
            if self.installed:
                installed.append(
                    {
                        "pluginId": f"{PLUGIN_NAME}@{self.marketplace_name}",
                        "name": PLUGIN_NAME,
                        "marketplaceName": self.marketplace_name,
                        "installed": True,
                        "enabled": self.enabled,
                    }
                )
            return 0, json.dumps({"installed": installed, "available": []}), ""
        if arguments == ("plugin", "remove", PLUGIN_NAME):
            self.installed = False
            return 0, "", ""
        if arguments == ("plugin", "add", f"{PLUGIN_NAME}@{self.marketplace_name}", "--json"):
            if self.add_exit_code:
                return self.add_exit_code, "", "Codex refused plugin"
            self.installed = True
            self.enabled = True
            return 0, json.dumps({"installed": True}), ""
        raise AssertionError(f"unexpected Codex CLI call: {arguments}")


def _write_template(root: Path) -> Path:
    template = root / "template"
    (template / ".codex-plugin").mkdir(parents=True)
    (template / "hooks").mkdir()
    (template / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": PLUGIN_NAME,
                "version": "0.1.0",
                "description": "PetNest status bridge",
                "author": {"name": "PetNest"},
                "interface": {
                    "displayName": "PetNest 状态联动",
                    "shortDescription": "让桌宠跟随 Codex 任务状态",
                    "longDescription": "只发送任务状态，不读取提示词、回复或代码。",
                    "developerName": "PetNest",
                    "category": "Productivity",
                    "capabilities": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (template / "hooks" / "hooks.json").write_text(
        json.dumps({"hooks": {event: [] for event in PLUGIN_EVENTS}}),
        encoding="utf-8",
    )
    return template


def _manager(tmp_path: Path, cli: FakeCodexCli, *, template: Path | None = None) -> CodexPluginManager:
    codex_home = tmp_path / ".codex"
    data_dir = tmp_path / "petnest-data"
    hook_manager = CodexHookManager(
        codex_home,
        data_dir,
        port=18486,
        command_prefix=("petnest",),
    )
    return CodexPluginManager(
        template or _write_template(tmp_path),
        data_dir,
        codex_home=codex_home,
        agents_plugins_root=tmp_path / ".agents" / "plugins",
        plugin_source_root=tmp_path / "plugins",
        hook_manager=hook_manager,
        command_runner=cli,
    )


def test_bundled_plugin_is_recognizable_and_has_only_four_status_hooks() -> None:
    template = Path(__file__).resolve().parents[1] / "assets" / "codex-plugins" / PLUGIN_NAME

    manifest = json.loads((template / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    hooks = json.loads((template / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]

    assert manifest["name"] == PLUGIN_NAME
    assert manifest["interface"]["displayName"] == "PetNest 状态联动"
    assert manifest["author"]["name"] == "PetNest"
    assert set(hooks) == PLUGIN_EVENTS
    assert all(len(groups) == 1 for groups in hooks.values())


def test_inspect_offers_one_plain_primary_action_when_plugin_is_missing(tmp_path: Path) -> None:
    status = _manager(tmp_path, FakeCodexCli()).inspect()

    assert status.state == "missing"
    assert status.installed is False
    assert status.action_label == "启用精确连接"
    assert "基础联动" in status.message


def test_plugin_manager_can_switch_cli_codex_home_without_moving_marketplace(tmp_path: Path) -> None:
    manager = _manager(tmp_path, FakeCodexCli())
    original_marketplace = manager.marketplace_path
    original_plugin_root = manager.plugin_root
    second = tmp_path / "second-codex-home"

    manager.set_codex_home(second)

    assert manager.codex_home == second.resolve()
    assert manager.marketplace_path == original_marketplace
    assert manager.plugin_root == original_plugin_root


def test_plugin_receipt_check_is_local_and_does_not_call_codex_cli(tmp_path: Path) -> None:
    cli = FakeCodexCli()
    manager = _manager(tmp_path, cli)

    assert manager.has_install_receipt() is False
    assert cli.calls == []
    manager.install_or_repair()
    calls_after_install = list(cli.calls)

    assert manager.has_install_receipt() is True
    assert cli.calls == calls_after_install


def test_install_materializes_plugin_merges_marketplace_and_replaces_legacy_hooks(tmp_path: Path) -> None:
    cli = FakeCodexCli()
    manager = _manager(tmp_path, cli)
    manager.hook_manager.install()
    marketplace_path = manager.marketplace_path
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.write_text(
        json.dumps(
            {
                "name": "personal",
                "interface": {"displayName": "My plugins"},
                "future": {"keep": True},
                "plugins": [
                    {
                        "name": "keep-me",
                        "source": {"source": "local", "path": "./plugins/keep-me"},
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
                        "category": "Productivity",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    status = manager.install_or_repair()

    assert status.state == "pending"
    assert status.installed is True
    assert status.action_label == "我已完成，重新检查"
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
    assert marketplace["future"] == {"keep": True}
    assert [entry["name"] for entry in marketplace["plugins"]] == ["keep-me", PLUGIN_NAME]
    assert (manager.plugin_root / ".codex-plugin" / "plugin.json").is_file()
    assert manager.plugin_root == tmp_path / "plugins" / PLUGIN_NAME
    installed_hooks = json.loads((manager.plugin_root / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert set(installed_hooks["hooks"]) == PLUGIN_EVENTS
    commands = [
        hook["commandWindows"]
        for groups in installed_hooks["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]
    assert all("--codex-hook" in command for command in commands)
    assert manager.hook_manager.inspect().installed is False
    assert ("plugin", "add", f"{PLUGIN_NAME}@personal", "--json") in cli.calls


def test_inspect_requests_repair_when_installed_material_is_changed(tmp_path: Path) -> None:
    cli = FakeCodexCli()
    manager = _manager(tmp_path, cli)
    manager.install_or_repair()
    (manager.plugin_root / "hooks" / "hooks.json").write_text("{}", encoding="utf-8")

    status = manager.inspect()

    assert status.state == "repair"
    assert status.installed is True
    assert status.action_label == "修复精确连接"


def test_plugin_is_only_reported_enabled_after_first_authenticated_event(tmp_path: Path) -> None:
    cli = FakeCodexCli()
    manager = _manager(tmp_path, cli)
    manager.install_or_repair()

    assert manager.inspect().state == "pending"

    manager.mark_confirmed()

    assert manager.inspect().state == "enabled"


def test_failed_codex_registration_keeps_basic_link_available_and_reports_retry(tmp_path: Path) -> None:
    cli = FakeCodexCli(add_exit_code=7)
    manager = _manager(tmp_path, cli)

    status = manager.install_or_repair()

    assert status.state == "error"
    assert status.installed is False
    assert status.action_label == "重试"
    assert "基础联动仍可使用" in status.message
    assert manager.plugin_root.is_dir()


def test_failed_repair_does_not_remove_previously_installed_plugin(tmp_path: Path) -> None:
    cli = FakeCodexCli(installed=True, add_exit_code=7)
    manager = _manager(tmp_path, cli)

    status = manager.install_or_repair()

    assert status.state == "error"
    assert status.installed is True
    assert cli.installed is True
    assert ("plugin", "remove", PLUGIN_NAME) not in cli.calls


def test_remove_unregisters_only_petnest_plugin_and_keeps_marketplace_source(tmp_path: Path) -> None:
    cli = FakeCodexCli()
    manager = _manager(tmp_path, cli)
    manager.install_or_repair()

    status = manager.remove()

    assert status.state == "missing"
    assert status.installed is False
    assert ("plugin", "remove", PLUGIN_NAME) in cli.calls
    marketplace = json.loads(manager.marketplace_path.read_text(encoding="utf-8"))
    assert any(entry["name"] == PLUGIN_NAME for entry in marketplace["plugins"])


def test_invalid_marketplace_is_never_overwritten(tmp_path: Path) -> None:
    manager = _manager(tmp_path, FakeCodexCli())
    manager.marketplace_path.parent.mkdir(parents=True)
    manager.marketplace_path.write_text("{ broken", encoding="utf-8")

    status = manager.install_or_repair()

    assert status.state == "error"
    assert manager.marketplace_path.read_text(encoding="utf-8") == "{ broken"


def test_existing_personal_marketplace_name_is_used_for_codex_registration(tmp_path: Path) -> None:
    cli = FakeCodexCli(marketplace_name="my-local")
    manager = _manager(tmp_path, cli)
    manager.marketplace_path.parent.mkdir(parents=True)
    manager.marketplace_path.write_text(
        json.dumps({"name": "my-local", "plugins": []}),
        encoding="utf-8",
    )

    status = manager.install_or_repair()

    assert status.state == "pending"
    assert ("plugin", "add", f"{PLUGIN_NAME}@my-local", "--json") in cli.calls


def test_symlinked_plugin_target_is_rejected_without_touching_external_files(tmp_path: Path) -> None:
    manager = _manager(tmp_path, FakeCodexCli())
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    manager.plugin_root.parent.mkdir(parents=True)
    try:
        manager.plugin_root.symlink_to(external, target_is_directory=True)
    except OSError:
        return

    status = manager.install_or_repair()

    assert status.state == "error"
    assert marker.read_text(encoding="utf-8") == "keep"


def test_existing_unrecognized_plugin_directory_is_never_replaced(tmp_path: Path) -> None:
    manager = _manager(tmp_path, FakeCodexCli())
    manager.plugin_root.mkdir(parents=True)
    marker = manager.plugin_root / "user-data.txt"
    marker.write_text("keep", encoding="utf-8")

    status = manager.install_or_repair()

    assert status.state == "error"
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (manager.plugin_root / ".codex-plugin" / "plugin.json").exists()
    assert not manager.marketplace_path.exists()


def test_windows_prefers_desktop_executable_over_path_cmd(
    tmp_path: Path, monkeypatch
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    desktop_cli = local_app_data / "OpenAI" / "Codex" / "bin" / "new" / "codex.exe"
    desktop_cli.parent.mkdir(parents=True)
    desktop_cli.write_bytes(b"exe")
    path_cmd = tmp_path / "node" / "codex.CMD"
    path_cmd.parent.mkdir()
    path_cmd.write_text("@echo off", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr("petnest.core.codex_plugin.sys.platform", "win32")
    monkeypatch.setattr("petnest.core.codex_plugin.shutil.which", lambda _name: str(path_cmd))

    assert locate_codex_cli() == desktop_cli.resolve()


def test_windows_cmd_cli_uses_cmd_wrapper_and_selected_codex_home(
    tmp_path: Path, monkeypatch
) -> None:
    cli_path = tmp_path / "codex.CMD"
    cli_path.write_text("@echo off", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(arguments, **kwargs):
        captured["arguments"] = tuple(arguments)
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"installed": [], "available": []}), stderr="")

    monkeypatch.setattr("petnest.core.codex_plugin.sys.platform", "win32")
    monkeypatch.setattr("petnest.core.codex_plugin.subprocess.run", fake_run)
    manager = CodexPluginManager(
        _write_template(tmp_path),
        tmp_path / "data",
        codex_home=tmp_path / "portable-codex",
        agents_plugins_root=tmp_path / ".agents" / "plugins",
        plugin_source_root=tmp_path / "plugins",
        hook_manager=CodexHookManager(
            tmp_path / "portable-codex",
            tmp_path / "data",
            port=18486,
            command_prefix=("petnest",),
        ),
        codex_cli=cli_path,
    )

    assert manager.inspect().state == "missing"
    arguments = captured["arguments"]
    assert isinstance(arguments, tuple)
    assert Path(arguments[0]).name.casefold() == "cmd.exe"
    assert arguments[1:5] == ("/d", "/s", "/c", str(cli_path))
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["CODEX_HOME"] == str((tmp_path / "portable-codex").resolve())
    assert env["PATH"] == os.environ["PATH"]

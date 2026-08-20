"""可识别的 PetNest Codex 状态插件安装、检测与修复。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
import uuid

from petnest.core.codex_link import CodexHookManager, CodexLinkError


PLUGIN_NAME = "petnest-status-link"
PLUGIN_DISPLAY_NAME = "PetNest 状态联动"
PLUGIN_EVENTS = ("UserPromptSubmit", "PermissionRequest", "PostToolUse", "Stop")
_RECEIPT_SCHEMA = 1

CodexCommandRunner = Callable[[tuple[str, ...]], tuple[int, str, str]]


@dataclass(frozen=True, slots=True)
class CodexPluginStatus:
    """设置页使用的单一主操作状态。"""

    state: str
    message: str
    installed: bool
    action_label: str
    details: str = ""

    @classmethod
    def missing(cls) -> "CodexPluginStatus":
        return cls(
            "missing",
            "精确连接尚未启用，基础联动仍可使用。",
            False,
            "启用精确连接",
            "Codex 尚未安装 PetNest 状态联动插件。",
        )

    @classmethod
    def enabled(cls) -> "CodexPluginStatus":
        return cls(
            "enabled",
            "精确连接已启用。",
            True,
            "已启用",
            "Codex 插件已安装并启用。",
        )

    @classmethod
    def pending(cls) -> "CodexPluginStatus":
        return cls(
            "pending",
            "PetNest 已完成配置，请在 Codex 中确认后重新检查。",
            True,
            "我已完成，重新检查",
            "插件已安装；收到第一条 PetNest 插件事件后才会确认精确连接已生效。",
        )

    @classmethod
    def repair(cls, details: str) -> "CodexPluginStatus":
        return cls(
            "repair",
            "精确连接需要修复，基础联动仍可使用。",
            True,
            "修复精确连接",
            details,
        )

    @classmethod
    def disabled(cls) -> "CodexPluginStatus":
        return cls(
            "disabled",
            "精确连接已在 Codex 中关闭，基础联动仍可使用。",
            True,
            "重新启用",
            "Codex 报告 PetNest 状态联动插件已安装但未启用。",
        )

    @classmethod
    def unavailable(cls, details: str) -> "CodexPluginStatus":
        return cls(
            "unavailable",
            "暂时无法检查精确连接，基础联动仍可使用。",
            False,
            "重新检查",
            details,
        )

    @classmethod
    def error(cls, details: str, *, installed: bool = False) -> "CodexPluginStatus":
        return cls(
            "error",
            "精确连接未完成，基础联动仍可使用。",
            installed,
            "重试",
            details,
        )


class CodexPluginManager:
    """只管理个人插件目录中的 PetNest 状态插件。"""

    def __init__(
        self,
        template_root: Path,
        data_dir: Path,
        *,
        codex_home: Path | None = None,
        agents_plugins_root: Path | None = None,
        plugin_source_root: Path | None = None,
        hook_manager: CodexHookManager,
        command_runner: CodexCommandRunner | None = None,
        codex_cli: Path | None = None,
    ) -> None:
        self.template_root = template_root.expanduser().resolve()
        self.data_dir = data_dir.expanduser().resolve()
        self.codex_home = (codex_home or Path.home() / ".codex").expanduser().resolve()
        self.agents_plugins_root = (
            agents_plugins_root or Path.home() / ".agents" / "plugins"
        ).expanduser().resolve()
        self.marketplace_path = self.agents_plugins_root / "marketplace.json"
        self.plugin_source_root = (plugin_source_root or Path.home() / "plugins").expanduser().resolve()
        self.plugin_root = self.plugin_source_root / PLUGIN_NAME
        self.receipt_path = self.data_dir / "codex-plugin.json"
        self.hook_manager = hook_manager
        self._codex_cli = codex_cli or locate_codex_cli()
        self._command_runner = command_runner or self._run_codex

    def inspect(self) -> CodexPluginStatus:
        """只读检查 Codex 注册状态和 PetNest 已安装材料。"""
        try:
            record = self._installed_record()
        except (CodexLinkError, OSError) as error:
            return CodexPluginStatus.unavailable(str(error))
        if record is None:
            return CodexPluginStatus.missing()
        if not bool(record.get("enabled", False)):
            return CodexPluginStatus.disabled()
        try:
            receipt = self._read_receipt()
            if receipt is None or not self.plugin_root.is_dir() or _is_link_like(self.plugin_root):
                return CodexPluginStatus.repair("已安装材料缺失或来源不安全。")
            current_digest = _tree_digest(self.plugin_root)
            if receipt.get("digest") != current_digest:
                return CodexPluginStatus.repair("插件文件与 PetNest 上次安装的版本不一致。")
            template_version = self._template_manifest()["version"]
            if receipt.get("version") != template_version:
                return CodexPluginStatus.repair("PetNest 提供了新的精确连接版本。")
            if receipt.get("confirmed") is not True:
                return CodexPluginStatus.pending()
        except (CodexLinkError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            return CodexPluginStatus.repair(str(error))
        return CodexPluginStatus.enabled()

    def install_or_repair(self) -> CodexPluginStatus:
        """安全写入个人 marketplace，注册插件，成功后移除旧匿名 Hook。"""
        installed_before = False
        try:
            self._validate_template()
            self._validate_plugin_target()
            self.hook_manager.ensure_metadata()
            marketplace_name = self._merge_marketplace()
            self._materialize_plugin()
            record = self._installed_record(allow_unavailable=True, marketplace_name=marketplace_name)
            installed_before = record is not None
            code, _stdout, stderr = self._command_runner(
                ("plugin", "add", f"{PLUGIN_NAME}@{marketplace_name}", "--json")
            )
            if code != 0:
                raise CodexLinkError(f"Codex 无法启用插件：{_bounded_error(stderr)}")
            manifest = self._template_manifest()
            _atomic_write_json(
                self.receipt_path,
                {
                    "schema_version": _RECEIPT_SCHEMA,
                    "plugin": PLUGIN_NAME,
                    "version": manifest["version"],
                    "digest": _tree_digest(self.plugin_root),
                    "confirmed": False,
                },
            )
            try:
                self.hook_manager.remove()
            except CodexLinkError:
                # 旧配置异常不能回滚已成功的可识别插件；高级诊断仍会显示。
                pass
            return CodexPluginStatus.pending()
        except (CodexLinkError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            return CodexPluginStatus.error(str(error), installed=installed_before)

    def remove(self) -> CodexPluginStatus:
        """从 Codex 停用 PetNest 插件；保留可重新启用的本地来源。"""
        try:
            record = self._installed_record(allow_unavailable=True)
            if record is not None:
                code, _stdout, stderr = self._command_runner(("plugin", "remove", PLUGIN_NAME))
                if code != 0:
                    raise CodexLinkError(f"Codex 无法停用插件：{_bounded_error(stderr)}")
            if self.receipt_path.exists() and not _is_link_like(self.receipt_path):
                self.receipt_path.unlink()
            return CodexPluginStatus.missing()
        except (CodexLinkError, OSError) as error:
            return CodexPluginStatus.error(str(error), installed=True)

    def mark_confirmed(self) -> None:
        """收到鉴权插件事件后持久确认，避免把“已安装”误报成“已生效”。"""
        receipt = self._read_receipt()
        if receipt is None or receipt.get("confirmed") is True:
            return
        receipt["confirmed"] = True
        _atomic_write_json(self.receipt_path, receipt)

    def _run_codex(self, arguments: tuple[str, ...]) -> tuple[int, str, str]:
        if self._codex_cli is None:
            raise CodexLinkError("未找到 Codex 命令行程序")
        invocation: tuple[str, ...] = (str(self._codex_cli), *arguments)
        if sys.platform == "win32" and self._codex_cli.suffix.casefold() in {".cmd", ".bat"}:
            command_shell = (
                shutil.which("cmd.exe")
                or os.environ.get("COMSPEC")
                or str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe")
            )
            invocation = (command_shell, "/d", "/s", "/c", str(self._codex_cli), *arguments)
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self.codex_home)
        try:
            completed = subprocess.run(
                invocation,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0),
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CodexLinkError(f"无法运行 Codex：{error}") from error
        return completed.returncode, completed.stdout, completed.stderr

    def _installed_record(
        self,
        *,
        allow_unavailable: bool = False,
        marketplace_name: str | None = None,
    ) -> dict[str, Any] | None:
        try:
            code, stdout, stderr = self._command_runner(("plugin", "list", "--json"))
        except (OSError, CodexLinkError) as error:
            if allow_unavailable:
                return None
            raise CodexLinkError(str(error)) from error
        if code != 0:
            if allow_unavailable:
                return None
            raise CodexLinkError(f"Codex 状态检查失败：{_bounded_error(stderr)}")
        try:
            document = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise CodexLinkError("Codex 返回了无法识别的插件状态") from error
        installed = document.get("installed") if isinstance(document, dict) else None
        if not isinstance(installed, list):
            raise CodexLinkError("Codex 返回的插件列表格式不受支持")
        selected_marketplace = marketplace_name or self._marketplace_name()
        return next(
            (
                item
                for item in installed
                if isinstance(item, dict)
                and item.get("name") == PLUGIN_NAME
                and item.get("marketplaceName") == selected_marketplace
                and item.get("installed") is not False
            ),
            None,
        )

    def _validate_template(self) -> None:
        manifest = self._template_manifest()
        if manifest.get("name") != PLUGIN_NAME:
            raise CodexLinkError("PetNest 内置插件名称无效")
        hooks_path = self.template_root / "hooks" / "hooks.json"
        if not hooks_path.is_file() or _is_link_like(hooks_path):
            raise CodexLinkError("PetNest 内置插件缺少安全的状态配置")
        if any(_is_link_like(path) for path in self.template_root.rglob("*")):
            raise CodexLinkError("PetNest 内置插件包含不安全的链接")
        hooks = _read_json_object(hooks_path).get("hooks")
        if not isinstance(hooks, dict) or set(hooks) != set(PLUGIN_EVENTS):
            raise CodexLinkError("PetNest 内置插件的状态事件不完整")

    def _template_manifest(self) -> dict[str, Any]:
        path = self.template_root / ".codex-plugin" / "plugin.json"
        if not path.is_file() or _is_link_like(path):
            raise CodexLinkError("PetNest 内置插件清单缺失")
        return _read_json_object(path)

    def _materialize_plugin(self) -> None:
        parent = self.plugin_root.parent
        parent.mkdir(parents=True, exist_ok=True)
        self._validate_plugin_target()
        staging = parent / f".{PLUGIN_NAME}.staging-{uuid.uuid4().hex}"
        backup = parent / f".{PLUGIN_NAME}.backup-{uuid.uuid4().hex}"
        try:
            shutil.copytree(self.template_root, staging)
            hooks_path = staging / "hooks" / "hooks.json"
            hooks = {
                "hooks": {
                    event: [{"matcher": "", "hooks": [self.hook_manager.handler_for(event)]}]
                    for event in PLUGIN_EVENTS
                }
            }
            _atomic_write_json(hooks_path, hooks)
            had_previous = self.plugin_root.exists()
            if had_previous:
                self.plugin_root.replace(backup)
            try:
                staging.replace(self.plugin_root)
            except OSError:
                if had_previous and backup.exists() and not self.plugin_root.exists():
                    backup.replace(self.plugin_root)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if staging.exists() and not _is_link_like(staging):
                shutil.rmtree(staging)

    def _validate_plugin_target(self) -> None:
        if self.plugin_root.parent != self.plugin_source_root:
            raise CodexLinkError("PetNest 插件安装位置超出个人插件目录，未做任何修改")
        if _is_link_like(self.plugin_root) or (self.plugin_root.exists() and not self.plugin_root.is_dir()):
            raise CodexLinkError("PetNest 插件安装位置不安全，未做任何修改")
        if self.plugin_root.exists() and not self._is_managed_plugin_root():
            raise CodexLinkError("插件安装位置已被其他文件占用，未做任何修改")
        if self.plugin_root.exists() and any(_is_link_like(path) for path in self.plugin_root.rglob("*")):
            raise CodexLinkError("现有 PetNest 插件包含不安全的链接，未做任何修改")

    def _is_managed_plugin_root(self) -> bool:
        manifest_path = self.plugin_root / ".codex-plugin" / "plugin.json"
        if not manifest_path.is_file() or _is_link_like(manifest_path):
            return False
        try:
            manifest = _read_json_object(manifest_path)
        except CodexLinkError:
            return False
        interface = manifest.get("interface")
        author = manifest.get("author")
        return (
            manifest.get("name") == PLUGIN_NAME
            and isinstance(interface, dict)
            and interface.get("displayName") == PLUGIN_DISPLAY_NAME
            and isinstance(author, dict)
            and author.get("name") == "PetNest"
        )

    def _merge_marketplace(self) -> str:
        if self.marketplace_path.parent != self.agents_plugins_root:
            raise CodexLinkError("个人插件清单超出预期目录，未做任何修改")
        if _is_link_like(self.marketplace_path):
            raise CodexLinkError("个人插件清单是链接，未做任何修改")
        if self.marketplace_path.exists():
            document = _read_json_object(self.marketplace_path)
        else:
            document = {
                "name": "personal",
                "interface": {"displayName": "Personal"},
                "plugins": [],
            }
        plugins = document.get("plugins")
        if not isinstance(plugins, list):
            raise CodexLinkError("个人插件清单的 plugins 字段不是数组，未做任何修改")
        marketplace_name = document.get("name")
        if not isinstance(marketplace_name, str) or re.fullmatch(r"[A-Za-z0-9_-]+", marketplace_name) is None:
            raise CodexLinkError("个人插件清单的 name 字段无效，未做任何修改")
        entry = {
            "name": PLUGIN_NAME,
            "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }
        replaced = False
        merged: list[object] = []
        for item in plugins:
            if isinstance(item, dict) and item.get("name") == PLUGIN_NAME:
                if not replaced:
                    merged.append(entry)
                    replaced = True
            else:
                merged.append(item)
        if not replaced:
            merged.append(entry)
        document["plugins"] = merged
        _atomic_write_json(self.marketplace_path, document, backup_existing=True)
        return marketplace_name

    def _marketplace_name(self) -> str:
        if not self.marketplace_path.exists():
            return "personal"
        if _is_link_like(self.marketplace_path):
            raise CodexLinkError("个人插件清单是链接，未做任何修改")
        document = _read_json_object(self.marketplace_path)
        name = document.get("name")
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_-]+", name) is None:
            raise CodexLinkError("个人插件清单的 name 字段无效")
        return name

    def _read_receipt(self) -> dict[str, Any] | None:
        if not self.receipt_path.exists():
            return None
        if self.receipt_path.parent != self.data_dir:
            raise CodexLinkError("PetNest 插件收据超出数据目录")
        if _is_link_like(self.receipt_path):
            raise CodexLinkError("PetNest 插件收据路径不安全")
        receipt = _read_json_object(self.receipt_path)
        if receipt.get("schema_version") != _RECEIPT_SCHEMA or receipt.get("plugin") != PLUGIN_NAME:
            return None
        return receipt


def locate_codex_cli() -> Path | None:
    """定位 PATH 或 Codex Desktop 自带的命令行程序。"""
    candidates: list[Path] = []
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.extend(Path(local_app_data).glob("OpenAI/Codex/bin/*/codex.exe"))
    existing = [path for path in candidates if path.is_file() and not _is_link_like(path)]
    if existing:
        return max(existing, key=lambda path: path.stat().st_mtime_ns).resolve()
    found = shutil.which("codex")
    return Path(found).resolve() if found else None


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CodexLinkError(f"无法解析 {path.name}，未做任何修改：{error}") from error
    if not isinstance(document, dict):
        raise CodexLinkError(f"{path.name} 的根节点必须是对象")
    return document


def _atomic_write_json(path: Path, document: dict[str, Any], *, backup_existing: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if _is_link_like(path):
        raise CodexLinkError(f"{path.name} 是链接，未做任何修改")
    if backup_existing and path.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(f"{path.name}.petnest-{stamp}.bak")
        shutil.copy2(path, backup)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _tree_digest(root: Path) -> str:
    if not root.is_dir() or _is_link_like(root):
        raise CodexLinkError("插件目录不存在或来源不安全")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if _is_link_like(path):
            raise CodexLinkError("插件目录包含不安全的链接")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            while chunk := stream.read(65_536):
                digest.update(chunk)
    return digest.hexdigest()


def _bounded_error(message: str) -> str:
    normalized = " ".join(message.split())
    return normalized[:500] or "未提供原因"


def _is_link_like(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True

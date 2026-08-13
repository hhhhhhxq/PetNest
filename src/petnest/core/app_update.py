"""跨平台应用安装包更新协议与下载实现。

该模块只负责网络元数据、版本和文件完整性校验，不直接操作 Qt。UI 可以在
后台线程调用 :class:`AppUpdateClient`；平台不匹配时检查结果为空，安装动作
由各平台独立的 updater 完成。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import BinaryIO, Callable
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from petnest import __version__

DEFAULT_APP_UPDATE_MANIFEST_URL = (
    "https://github.com/hhhhhhxq/PetNest/releases/latest/download/app-update.json"
)
APP_UPDATE_SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
MAX_RELEASE_NOTES_BYTES = 64 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
ALLOWED_RELEASE_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class AppUpdateError(RuntimeError):
    """更新元数据、网络下载或完整性校验失败。"""


@dataclass(frozen=True)
class AppUpdateAsset:
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class AppUpdateInfo:
    version: str
    platform: str
    asset: AppUpdateAsset
    release_notes: str = ""


@dataclass(frozen=True)
class AppUpdateCheckResult:
    checked: bool
    skipped: bool
    update: AppUpdateInfo | None = None
    error: str | None = None


@dataclass(frozen=True)
class _AppUpdateState:
    last_check_at: str | None = None
    last_error: str | None = None


def _version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or _VERSION_RE.fullmatch(value) is None:
        raise AppUpdateError(f"版本号格式无效：{value!r}")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    assert match is not None
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def _validate_asset_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2_048:
        raise AppUpdateError("更新包 URL 无效")
    try:
        parsed = urlparse(value)
    except ValueError as error:
        raise AppUpdateError("更新包 URL 无效") from error
    if parsed.scheme.lower() != "https" or parsed.username or parsed.password:
        raise AppUpdateError("更新包必须使用 HTTPS")
    if parsed.hostname is None or parsed.hostname.casefold() not in ALLOWED_RELEASE_HOSTS:
        raise AppUpdateError("更新包 URL 不是允许的 GitHub Releases 地址")
    try:
        port = parsed.port
    except ValueError as error:
        raise AppUpdateError("更新包 URL 端口无效") from error
    if port not in (None, 443):
        raise AppUpdateError("更新包 URL 端口无效")
    if not parsed.path or ".." in parsed.path.split("/"):
        raise AppUpdateError("更新包 URL 路径无效")
    return value


def parse_update_manifest(
    payload: bytes | str,
    *,
    current_version: str = __version__,
    platform_name: str | None = None,
) -> AppUpdateInfo | None:
    """解析并验证公开 Release 的 ``app-update.json``。

    返回 ``None`` 表示当前平台不适用或没有比当前版本更新的版本；不可信的
    内容一律抛出 :class:`AppUpdateError`，不会被当成可安装版本。
    """

    if isinstance(payload, bytes):
        if len(payload) > MAX_MANIFEST_BYTES:
            raise AppUpdateError("更新元数据过大")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AppUpdateError("更新元数据不是 UTF-8") from error
    elif isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise AppUpdateError("更新元数据过大")
        text = payload
    else:
        raise AppUpdateError("更新元数据类型无效")
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError) as error:
        raise AppUpdateError("更新元数据 JSON 无效") from error
    if not isinstance(document, dict):
        raise AppUpdateError("更新元数据根节点必须是对象")
    if isinstance(document.get("schema_version"), bool) or document.get("schema_version") != APP_UPDATE_SCHEMA_VERSION:
        raise AppUpdateError("更新元数据版本不受支持")
    target_platform = document.get("platform")
    if not isinstance(target_platform, str) or target_platform not in {
        "windows-x64",
        "windows",
        "darwin",
        "macos",
        "macos-x64",
        "macos-arm64",
    }:
        raise AppUpdateError("更新元数据平台无效")
    if platform_name == "win32" and target_platform not in {"windows-x64", "windows"}:
        return None
    if platform_name == "darwin" and target_platform not in {"darwin", "macos", "macos-x64", "macos-arm64"}:
        return None
    if platform_name is not None and platform_name not in {"win32", "darwin"}:
        return None
    version = document.get("version")
    current = _version_tuple(current_version)
    candidate = _version_tuple(version)
    if candidate <= current:
        return None
    asset_document = document.get("asset")
    if not isinstance(asset_document, dict):
        raise AppUpdateError("更新元数据缺少 asset")
    url = _validate_asset_url(asset_document.get("url"))
    size = asset_document.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > MAX_INSTALLER_BYTES:
        raise AppUpdateError("更新包大小无效")
    sha256 = asset_document.get("sha256")
    if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
        raise AppUpdateError("更新包 SHA-256 无效")
    release_notes = document.get("release_notes", "")
    if not isinstance(release_notes, str) or len(release_notes.encode("utf-8")) > MAX_RELEASE_NOTES_BYTES:
        raise AppUpdateError("更新说明无效")
    return AppUpdateInfo(
        version=version,
        platform=target_platform,
        asset=AppUpdateAsset(url=url, size=size, sha256=sha256.casefold()),
        release_notes=release_notes,
    )


def _read_limited(stream: BinaryIO, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(DOWNLOAD_CHUNK_BYTES, limit - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise AppUpdateError("响应内容超过大小限制")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_response_url(response: object) -> None:
    """校验 urllib 自动重定向后的最终地址仍在 GitHub Releases 白名单内。"""

    geturl = getattr(response, "geturl", None)
    if not callable(geturl):
        return
    final_url = geturl()
    if isinstance(final_url, str):
        _validate_asset_url(final_url)


class AppUpdateClient:
    """可注入网络打开器的应用更新客户端，适合后台线程与单元测试。"""

    def __init__(
        self,
        *,
        manifest_url: str = DEFAULT_APP_UPDATE_MANIFEST_URL,
        current_version: str = __version__,
        platform_name: str | None = None,
        timeout: float = 15.0,
        opener: Callable[..., object] | None = None,
    ) -> None:
        self.manifest_url = _validate_asset_url(manifest_url)
        self.current_version = current_version
        self.platform_name = sys.platform if platform_name is None else platform_name
        self.timeout = timeout
        self._opener = opener or urlopen

    def check(self) -> AppUpdateInfo | None:
        if self.platform_name not in {"win32", "darwin"}:
            return None
        request = Request(
            self.manifest_url,
            headers={"Accept": "application/json", "Cache-Control": "no-cache"},
        )
        response = None
        try:
            response = self._opener(request, timeout=self.timeout)
            _validate_response_url(response)
            payload = _read_limited(response, MAX_MANIFEST_BYTES)  # type: ignore[arg-type]
            return parse_update_manifest(
                payload,
                current_version=self.current_version,
                platform_name=self.platform_name,
            )
        except AppUpdateError:
            raise
        except HTTPError as error:
            if error.code == 404:
                platform_label = "Windows" if self.platform_name == "win32" else "macOS"
                raise AppUpdateError(
                    f"{platform_label} 更新清单尚未发布（GitHub Release 暂无对应附件）"
                ) from error
            raise AppUpdateError(f"无法检查程序更新：{error}") from error
        except (URLError, OSError, TimeoutError) as error:
            raise AppUpdateError(f"无法检查程序更新：{error}") from error
        except Exception as error:  # noqa: BLE001 - untrusted opener must not escape cleanup.
            raise AppUpdateError(f"无法检查程序更新：{error}") from error
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

    def download(
        self,
        info: AppUpdateInfo,
        destination: Path,
        *,
        progress: Callable[[int], object] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> None:
        """流式下载到 ``.part``，校验成功后原子替换目标文件。"""

        url = _validate_asset_url(info.asset.url)
        if (
            isinstance(info.asset.size, bool)
            or not isinstance(info.asset.size, int)
            or info.asset.size <= 0
            or info.asset.size > MAX_INSTALLER_BYTES
            or _SHA256_RE.fullmatch(info.asset.sha256) is None
        ):
            raise AppUpdateError("更新包信息无效")
        if _version_tuple(info.version) <= _version_tuple(self.current_version):
            raise AppUpdateError("更新包版本不是当前版本的新版本")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        response = None
        received = 0
        digest = hashlib.sha256()
        try:
            request = Request(url, headers={"Accept": "application/octet-stream"})
            response = self._opener(request, timeout=self.timeout)
            _validate_response_url(response)
            with partial.open("wb") as output:
                while True:
                    if cancel is not None and cancel():
                        raise AppUpdateError("用户取消了更新下载")
                    chunk = response.read(min(DOWNLOAD_CHUNK_BYTES, info.asset.size - received + 1))  # type: ignore[union-attr]
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > info.asset.size:
                        raise AppUpdateError("更新包超过声明大小")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress is not None:
                        progress(min(100, received * 100 // info.asset.size))
                output.flush()
            if received != info.asset.size:
                raise AppUpdateError("更新包大小校验失败")
            if digest.hexdigest() != info.asset.sha256.casefold():
                raise AppUpdateError("更新包 SHA-256 校验失败")
            partial.replace(destination)
            if progress is not None:
                progress(100)
        except AppUpdateError:
            partial.unlink(missing_ok=True)
            raise
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            partial.unlink(missing_ok=True)
            raise AppUpdateError(f"无法下载程序更新：{error}") from error
        except Exception as error:  # noqa: BLE001 - always remove an interrupted .part file.
            partial.unlink(missing_ok=True)
            raise AppUpdateError(f"无法下载程序更新：{error}") from error
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()


def build_updater_command(
    updater_path: Path,
    installer_path: Path,
    parent_pid: int,
    *,
    restart_path: Path | None = None,
) -> list[str]:
    """构造不经过 shell 的 updater 参数，避免路径注入和引号错误。"""

    if isinstance(parent_pid, bool) or not isinstance(parent_pid, int) or parent_pid <= 0:
        raise AppUpdateError("父进程 PID 无效")
    updater = Path(updater_path)
    installer = Path(installer_path)
    if not updater.is_absolute() or not installer.is_absolute():
        raise AppUpdateError("updater 和安装包路径必须是绝对路径")
    command = [str(updater), "--wait-pid", str(parent_pid), "--installer", str(installer)]
    if restart_path is not None:
        restart = Path(restart_path)
        if not restart.is_absolute():
            raise AppUpdateError("重启路径必须是绝对路径")
        command.extend(("--restart", str(restart)))
    return command


class AppUpdateCoordinator:
    """提供启动/定时检查的 24 小时节流，手动检查可用 ``force=True``。"""

    def __init__(
        self,
        client: AppUpdateClient,
        state_path: Path,
        *,
        now: Callable[[], datetime] | None = None,
        interval: timedelta = timedelta(hours=24),
    ) -> None:
        self.client = client
        self.state_path = Path(state_path)
        self.now = now or (lambda: datetime.now(UTC))
        self.interval = interval
        self._state = self._load_state()

    def should_check(self, *, force: bool = False) -> bool:
        if force or self._state.last_check_at is None:
            return True
        try:
            previous = datetime.fromisoformat(self._state.last_check_at).astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            return True
        return self.now().astimezone(UTC) - previous >= self.interval

    def check(self, *, force: bool = False) -> AppUpdateCheckResult:
        if not self.should_check(force=force):
            return AppUpdateCheckResult(False, True)
        try:
            update = self.client.check()
        except Exception as error:  # noqa: BLE001 - a failed check must not stop PetNest.
            message = str(error) or error.__class__.__name__
            self._state = _AppUpdateState(self.now().astimezone(UTC).isoformat(), message)
            self._save_state()
            return AppUpdateCheckResult(False, False, error=message)
        self._state = _AppUpdateState(self.now().astimezone(UTC).isoformat(), None)
        self._save_state()
        return AppUpdateCheckResult(True, False, update=update)

    def _load_state(self) -> _AppUpdateState:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return _AppUpdateState()
        if not isinstance(raw, dict):
            return _AppUpdateState()
        return _AppUpdateState(
            last_check_at=raw.get("last_check_at") if isinstance(raw.get("last_check_at"), str) else None,
            last_error=raw.get("last_error") if isinstance(raw.get("last_error"), str) else None,
        )

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {"last_check_at": self._state.last_check_at, "last_error": self._state.last_error},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with temporary.open("r+", encoding="utf-8") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.state_path)
        finally:
            temporary.unlink(missing_ok=True)

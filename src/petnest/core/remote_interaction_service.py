"""通过 Firebase Realtime Database 中继远程伙伴互动。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from secrets import choice
import sys
from threading import Event, Lock, Thread
from time import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

from PySide6.QtCore import QObject, Signal

from petnest.core.lan_interaction import LanPacketCodec, LanProtocolError
from petnest.models.lan_interaction import InteractionDraft, LanPeer

LOGGER = logging.getLogger(__name__)
PAIR_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
PAIR_CODE_LENGTH = 10
MESSAGE_TTL_SECONDS = 7 * 24 * 60 * 60
REJECTED_REFRESH_TOKEN_ERRORS = frozenset(
    {
        "INVALID_REFRESH_TOKEN",
        "TOKEN_EXPIRED",
        "USER_NOT_FOUND",
    }
)


@dataclass(frozen=True, slots=True)
class FirebaseConfig:
    """客户端可公开的 Firebase Web API 参数。"""

    api_key: str
    database_url: str
    project_id: str = ""

    @classmethod
    def load(cls, directory: Path) -> "FirebaseConfig | None":
        api_key = os.environ.get("PETNEST_FIREBASE_API_KEY", "").strip()
        database_url = os.environ.get("PETNEST_FIREBASE_DATABASE_URL", "").strip()
        project_id = ""
        config_path = directory / "firebase.json"
        if (not api_key or not database_url) and config_path.is_file():
            raw = _read_config_object(config_path)
            if raw is not None:
                api_key = api_key or str(raw.get("api_key", raw.get("apiKey", ""))).strip()
                database_url = database_url or str(raw.get("database_url", raw.get("databaseURL", ""))).strip()
                project_id = str(raw.get("project_id", raw.get("projectId", ""))).strip()
        for google_services_path in _google_services_paths(directory):
            if api_key and database_url:
                break
            if not google_services_path.is_file():
                continue
            raw = _read_config_object(google_services_path)
            if raw is None:
                continue
            google_api_key, google_database_url, google_project_id = _google_services_values(raw)
            if google_api_key and not google_database_url:
                LOGGER.warning(
                    "google-services.json 缺少 project_info/firebase_url；请创建 Realtime Database 后重新下载"
                )
            api_key = api_key or google_api_key
            database_url = database_url or google_database_url
            project_id = project_id or google_project_id
        if not api_key or not database_url:
            return None
        if not database_url.startswith("https://"):
            LOGGER.warning("Firebase database_url 必须使用 HTTPS")
            return None
        return cls(api_key=api_key, database_url=database_url.rstrip("/"), project_id=project_id)


def _read_config_object(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        LOGGER.warning("忽略无效 Firebase 配置：%s", path)
        return None
    if not isinstance(raw, dict):
        LOGGER.warning("忽略非对象 Firebase 配置：%s", path)
        return None
    return raw


def _google_services_paths(directory: Path) -> tuple[Path, ...]:
    """按用户配置、安装包、开发目录的优先级查找 Android 原版配置。"""
    candidates = [directory / "google-services.json"]
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        candidates.append(Path(frozen_root) / "google-services.json")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "google-services.json")
    else:
        project_root = Path(__file__).resolve().parents[3]
        candidates.extend((project_root / "google-services.json", project_root / "firebase" / "google-services.json"))
    paths: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            paths.append(resolved)
    return tuple(paths)


def _google_services_values(raw: dict[str, Any]) -> tuple[str, str, str]:
    """提取 Android ``google-services.json`` 中可供 REST 客户端使用的项目参数。"""
    project_info = raw.get("project_info")
    if not isinstance(project_info, dict):
        return "", "", ""
    database_url = str(project_info.get("firebase_url", project_info.get("database_url", ""))).strip()
    project_id = str(project_info.get("project_id", "")).strip()
    clients = raw.get("client")
    if not isinstance(clients, list):
        return "", database_url, project_id
    for client in clients:
        if not isinstance(client, dict):
            continue
        api_keys = client.get("api_key")
        if not isinstance(api_keys, list):
            continue
        for entry in api_keys:
            if isinstance(entry, dict) and isinstance(entry.get("current_key"), str):
                api_key = entry["current_key"].strip()
                if api_key:
                    return api_key, database_url, project_id
    return "", database_url, project_id


class RemoteCredentialStore:
    """把匿名帐号刷新令牌与配对码保存在独立的受限文件中。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            key: value
            for key, value in raw.items()
            if key in {"uid", "refresh_token", "pair_code"} and isinstance(value, str) and value.strip()
        }

    def save(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            temporary.replace(self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        finally:
            if temporary.exists():
                temporary.unlink()


class FirebaseRemoteInteractionService(QObject):
    """在后台线程维护匿名认证和单个 RTDB SSE 长连接。"""

    peer_changed = Signal(object)
    peer_removed = Signal(str)
    interaction_received = Signal(object)
    pairing_succeeded = Signal(object)
    pair_code_changed = Signal(str)
    status_changed = Signal(str)
    error = Signal(str)
    interaction_send_succeeded = Signal(object)
    interaction_send_failed = Signal(object, str)
    running_changed = Signal(bool)

    def __init__(
        self,
        *,
        display_name: str,
        pet_name: str,
        config_directory: Path,
        config: FirebaseConfig | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.display_name = display_name
        self.pet_name = pet_name
        self.config = config if config is not None else FirebaseConfig.load(config_directory)
        self._credential_store = RemoteCredentialStore(config_directory / "firebase-remote-credentials.json")
        credentials = self._credential_store.load()
        self._pair_code = normalize_pair_code(credentials.get("pair_code", "")) or _new_pair_code()
        self._credentials = {**credentials, "pair_code": self._pair_code}
        self._credential_store.save(self._credentials)
        self._token = ""
        self._uid = credentials.get("uid", "")
        self._token_lock = Lock()
        self._peers_lock = Lock()
        self._peers: dict[str, LanPeer] = {}
        self._processed_message_ids: set[str] = set()
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._stream_lock = Lock()
        self._stream: Any = None
        self._running = False
        self._status_message = "Firebase 尚未配置" if self.config is None else "远程互动尚未连接"

    @property
    def is_configured(self) -> bool:
        return self.config is not None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def pair_code(self) -> str:
        return self._pair_code

    @property
    def status_message(self) -> str:
        return self._status_message

    def peers(self) -> tuple[LanPeer, ...]:
        with self._peers_lock:
            values = tuple(self._peers.values())
        return tuple(sorted(values, key=lambda item: item.display_name.casefold()))

    def start(self) -> bool:
        if self._running:
            return True
        if self.config is None:
            self._set_status("Firebase 尚未配置，远程伙伴暂不可用")
            return False
        self._stop_event.clear()
        self._running = True
        self.running_changed.emit(True)
        self.pair_code_changed.emit(self._pair_code)
        self._set_status("正在连接远程伙伴…")
        self._thread = Thread(target=self._run, name="petnest-firebase", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        with self._stream_lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        with self._token_lock:
            self._token = ""
        self._running = False
        self.running_changed.emit(False)
        self._set_status("远程互动已关闭")

    def update_identity(self, *, display_name: str, pet_name: str) -> None:
        self.display_name = display_name
        self.pet_name = pet_name
        if self._running and self._current_auth()[0]:
            Thread(target=self._publish_identity_safely, name="petnest-firebase-profile", daemon=True).start()

    def pair_peer(self, code: str) -> bool:
        normalized = normalize_pair_code(code)
        if normalized is None:
            self.error.emit("伙伴码应为 10 位字母或数字")
            return False
        if normalized == self._pair_code:
            self.error.emit("不能添加自己的伙伴码")
            return False
        token, uid = self._current_auth()
        if not token or not uid:
            self.error.emit("远程伙伴尚未连接，请稍后重试")
            return False
        Thread(
            target=self._pair_peer_worker,
            args=(normalized, token, uid),
            name="petnest-firebase-pair",
            daemon=True,
        ).start()
        self._set_status("正在验证伙伴码…")
        return True

    def send_interaction(self, draft: InteractionDraft) -> bool:
        token, uid = self._current_auth()
        if not token or not uid:
            self.error.emit("远程伙伴尚未连接，请稍后重试")
            return False
        with self._peers_lock:
            if draft.target_device_id not in self._peers:
                self.error.emit("目标远程伙伴不存在，请刷新后重试")
                return False
        Thread(
            target=self._send_interaction_worker,
            args=(draft, token, uid),
            name="petnest-firebase-send",
            daemon=True,
        ).start()
        return True

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                token, uid = self._authenticate()
                with self._token_lock:
                    self._token, self._uid = token, uid
                self._publish_identity(token=token, uid=uid)
                self._set_status("远程伙伴已连接")
                self._stream_account(token=token, uid=uid)
            except (OSError, ValueError, HTTPError, URLError) as error:
                if self._stop_event.is_set():
                    break
                LOGGER.warning("Firebase 远程互动连接中断：%s", error)
                self._set_status("远程连接中断，正在重试…")
                self._stop_event.wait(3)
        with self._token_lock:
            self._token = ""

    def _authenticate(self) -> tuple[str, str]:
        assert self.config is not None
        refresh_token = self._credentials.get("refresh_token", "")
        refresh_token_rejected = False
        if refresh_token:
            try:
                response = _request_json(
                    f"https://securetoken.googleapis.com/v1/token?key={self.config.api_key}",
                    method="POST",
                    data=urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode(),
                    content_type="application/x-www-form-urlencoded",
                )
                token = str(response["id_token"])
                uid = str(response["user_id"])
                self._save_credentials(uid=uid, refresh_token=str(response.get("refresh_token", refresh_token)))
                return token, uid
            except HTTPError as error:
                error_code = _firebase_auth_error_code(error)
                if error_code not in REJECTED_REFRESH_TOKEN_ERRORS:
                    raise
                LOGGER.info("Firebase 匿名凭据已失效（%s），将创建新的匿名身份", error_code)
                refresh_token_rejected = True
        response = _request_json(
            f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.config.api_key}",
            method="POST",
            data=json.dumps({"returnSecureToken": True}).encode(),
        )
        token = str(response["idToken"])
        uid = str(response["localId"])
        if refresh_token_rejected:
            self._pair_code = _new_pair_code()
            self.pair_code_changed.emit(self._pair_code)
        self._save_credentials(uid=uid, refresh_token=str(response["refreshToken"]))
        return token, uid

    def _publish_identity_safely(self) -> None:
        token, uid = self._current_auth()
        if not token or not uid:
            return
        try:
            self._publish_identity(token=token, uid=uid)
        except (OSError, ValueError, HTTPError, URLError) as error:
            LOGGER.warning("更新远程伙伴身份失败：%s", error)

    def _publish_identity(self, *, token: str, uid: str) -> None:
        assert self.config is not None
        profile = self._profile(uid)
        _request_json(self._database_url(f"profiles/{uid}", token), method="PUT", data=_json_bytes(profile))
        pair_record = {**profile, "updated_at": _server_timestamp()}
        _request_json(
            self._database_url(f"pairCodes/{self._pair_code}", token),
            method="PUT",
            data=_json_bytes(pair_record),
        )

    def _stream_account(self, *, token: str, uid: str) -> None:
        request = Request(self._database_url(f"accounts/{uid}", token), headers={"Accept": "text/event-stream"})
        account: dict[str, Any] = {}
        with urlopen(request, timeout=70) as stream:  # noqa: S310 - URL comes from validated HTTPS Firebase config.
            with self._stream_lock:
                self._stream = stream
            event_name = ""
            data_lines: list[str] = []
            try:
                while not self._stop_event.is_set():
                    raw_line = stream.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif not line:
                        if event_name in {"put", "patch"} and data_lines:
                            payload = json.loads("\n".join(data_lines))
                            account = _apply_stream_change(account, payload, patch=event_name == "patch")
                            self._process_account(account, token=token, uid=uid)
                        elif event_name in {"auth_revoked", "cancel"}:
                            raise OSError("Firebase 流授权已失效")
                        event_name = ""
                        data_lines.clear()
            finally:
                with self._stream_lock:
                    if self._stream is stream:
                        self._stream = None

    def _process_account(self, account: dict[str, Any], *, token: str, uid: str) -> None:
        partners = account.get("partners") if isinstance(account.get("partners"), dict) else {}
        next_peers: dict[str, LanPeer] = {}
        for partner_uid, raw in partners.items():
            peer = _peer_from_record(partner_uid, raw)
            if peer is not None:
                next_peers[partner_uid] = peer
        with self._peers_lock:
            previous_ids = set(self._peers)
            self._peers = next_peers
        for peer in next_peers.values():
            self.peer_changed.emit(peer)
        for removed in previous_ids - set(next_peers):
            self.peer_removed.emit(removed)

        requests = account.get("requests") if isinstance(account.get("requests"), dict) else {}
        for sender_uid, raw in tuple(requests.items()):
            peer = _peer_from_record(sender_uid, raw)
            if peer is None:
                continue
            try:
                _request_json(
                    self._database_url(f"accounts/{uid}/partners/{sender_uid}", token),
                    method="PUT",
                    data=_json_bytes(_partner_record(peer)),
                )
                _request_json(
                    self._database_url(f"accounts/{uid}/requests/{sender_uid}", token),
                    method="DELETE",
                )
            except (OSError, ValueError, HTTPError, URLError) as error:
                LOGGER.warning("接受远程伙伴请求失败：%s", error)

        inbox = account.get("inbox") if isinstance(account.get("inbox"), dict) else {}
        for message_id, raw in tuple(inbox.items()):
            if message_id in self._processed_message_ids:
                continue
            self._processed_message_ids.add(message_id)
            try:
                received = _decode_remote_message(raw, local_uid=uid)
            except LanProtocolError as error:
                LOGGER.debug("忽略无效远程互动：%s", error)
            else:
                self.interaction_received.emit(received)
            try:
                _request_json(
                    self._database_url(f"accounts/{uid}/inbox/{message_id}", token),
                    method="DELETE",
                )
            except (OSError, ValueError, HTTPError, URLError) as error:
                LOGGER.warning("清理远程互动消息失败：%s", error)

    def _pair_peer_worker(self, code: str, token: str, uid: str) -> None:
        try:
            raw = _request_json(self._database_url(f"pairCodes/{code}", token))
            peer = _peer_from_record(str(raw.get("uid", "")), raw)
            if peer is None or peer.device_id == uid:
                raise ValueError("伙伴码不存在或已失效")
            _request_json(
                self._database_url(f"accounts/{uid}/partners/{peer.device_id}", token),
                method="PUT",
                data=_json_bytes(_partner_record(peer)),
            )
            request_record = {
                "uid": uid,
                "display_name": self.display_name,
                "pet_name": self.pet_name,
                "code": code,
                "created_at": _server_timestamp(),
            }
            _request_json(
                self._database_url(f"accounts/{peer.device_id}/requests/{uid}", token),
                method="PUT",
                data=_json_bytes(request_record),
            )
        except (OSError, ValueError, HTTPError, URLError, AttributeError) as error:
            self.error.emit(f"添加远程伙伴失败：{_friendly_network_error(error)}")
            return
        with self._peers_lock:
            self._peers[peer.device_id] = peer
        self.peer_changed.emit(peer)
        self.pairing_succeeded.emit(peer)
        self._set_status(f"已添加远程伙伴：{peer.display_name}")

    def _send_interaction_worker(self, draft: InteractionDraft, token: str, uid: str) -> None:
        try:
            payload = LanPacketCodec.interaction(draft, uid, self.display_name)
            payload["created_at"] = int(time() * 1000)
            payload["expires_at"] = int((time() + MESSAGE_TTL_SECONDS) * 1000)
            message_id = uuid.uuid4().hex
            _request_json(
                self._database_url(f"accounts/{draft.target_device_id}/inbox/{message_id}", token),
                method="PUT",
                data=_json_bytes(payload),
            )
            self.interaction_send_succeeded.emit(draft)
        except (OSError, ValueError, HTTPError, URLError, LanProtocolError) as error:
            message = f"远程互动发送失败：{_friendly_network_error(error)}"
            self.error.emit(message)
            self.interaction_send_failed.emit(draft, message)

    def _database_url(self, path: str, token: str) -> str:
        assert self.config is not None
        return f"{self.config.database_url}/{path}.json?auth={token}"

    def _current_auth(self) -> tuple[str, str]:
        with self._token_lock:
            return self._token, self._uid

    def _save_credentials(self, *, uid: str, refresh_token: str) -> None:
        self._credentials = {"uid": uid, "refresh_token": refresh_token, "pair_code": self._pair_code}
        self._credential_store.save(self._credentials)

    def _profile(self, uid: str) -> dict[str, Any]:
        return {"uid": uid, "display_name": self.display_name, "pet_name": self.pet_name}

    def _set_status(self, message: str) -> None:
        self._status_message = message
        self.status_changed.emit(message)


def normalize_pair_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = "".join(char for char in value.upper() if char.isalnum())
    if len(normalized) != PAIR_CODE_LENGTH or any(char not in PAIR_CODE_ALPHABET for char in normalized):
        return None
    return normalized


def _new_pair_code() -> str:
    return "".join(choice(PAIR_CODE_ALPHABET) for _ in range(PAIR_CODE_LENGTH))


def _firebase_auth_error_code(error: HTTPError) -> str:
    """从 Firebase Auth 的 HTTP 错误中提取稳定错误码。"""
    try:
        raw = json.loads(error.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(raw, dict):
        return ""
    detail = raw.get("error")
    if isinstance(detail, dict):
        message = detail.get("message")
    else:
        message = detail
    if not isinstance(message, str):
        return ""
    return message.partition(":")[0].strip().upper()


def _request_json(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    content_type: str = "application/json",
) -> dict[str, Any]:
    headers = {"Content-Type": content_type} if data is not None else {}
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=15) as response:  # noqa: S310 - callers supply Firebase HTTPS endpoints.
        body = response.read()
    if not body or body == b"null":
        return {}
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Firebase 返回了无效数据")
    return parsed


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _server_timestamp() -> dict[str, str]:
    return {".sv": "timestamp"}


def _partner_record(peer: LanPeer) -> dict[str, Any]:
    return {
        "uid": peer.device_id,
        "display_name": peer.display_name,
        "pet_name": peer.pet_name or "桌宠",
        "paired_at": _server_timestamp(),
    }


def _peer_from_record(uid: object, raw: object) -> LanPeer | None:
    if not isinstance(uid, str) or not uid or not isinstance(raw, dict):
        return None
    display_name = raw.get("display_name")
    pet_name = raw.get("pet_name")
    if not isinstance(display_name, str) or not display_name.strip():
        return None
    if not isinstance(pet_name, str) or not pet_name.strip():
        pet_name = None
    return LanPeer(uid, display_name.strip(), pet_name.strip() if pet_name else None, transport="remote")


def _decode_remote_message(raw: object, *, local_uid: str):
    if not isinstance(raw, dict):
        raise LanProtocolError("远程消息必须是对象")
    expires_at = raw.get("expires_at")
    if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
        raise LanProtocolError("远程消息缺少有效期")
    if expires_at < time() * 1000:
        raise LanProtocolError("远程消息已过期")
    return LanPacketCodec.decode_interaction(_json_bytes(raw), local_device_id=local_uid)


def _apply_stream_change(account: dict[str, Any], payload: object, *, patch: bool) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("path"), str):
        raise ValueError("Firebase 流消息无效")
    path = payload["path"]
    data = payload.get("data")
    if path == "/":
        if patch:
            updated = dict(account)
            if isinstance(data, dict):
                updated.update(data)
            return updated
        return dict(data) if isinstance(data, dict) else {}
    segments = [segment for segment in path.split("/") if segment]
    updated = json.loads(json.dumps(account))
    cursor = updated
    for segment in segments[:-1]:
        child = cursor.get(segment)
        if not isinstance(child, dict):
            child = {}
            cursor[segment] = child
        cursor = child
    leaf = segments[-1]
    if data is None:
        cursor.pop(leaf, None)
    elif patch and isinstance(data, dict) and isinstance(cursor.get(leaf), dict):
        cursor[leaf].update(data)
    else:
        cursor[leaf] = data
    return updated


def _friendly_network_error(error: BaseException) -> str:
    if isinstance(error, HTTPError):
        if error.code == 401:
            return "登录状态已失效"
        if error.code == 403:
            return "Firebase 安全规则拒绝了请求"
        if error.code == 404:
            return "伙伴码不存在或已失效"
        return f"Firebase 返回 HTTP {error.code}"
    text = str(error).strip()
    return text or error.__class__.__name__

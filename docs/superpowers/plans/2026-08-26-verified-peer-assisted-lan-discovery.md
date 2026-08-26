# 已验证伙伴辅助的跨网段局域网发现实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让可单播互通但广播隔离的 PetNest 子网，通过已验证伙伴安全交换在线端点并自动完成定向验证，同时复用该验证底座而保留预警池独立的加入/退出状态同步。

**架构：** `LanInteractionService` 继续拥有 UDP/TCP 套接字，并增加可选 presence 扩展、并发随机挑战探测和伙伴目录帧传输。新的目录协议与纯状态模块负责严格验证、多网卡端点归并、候选限频和退避；`LanPeerDiscoverySyncService` 负责目录反熵、候选调度和跨网段续期。`LanPoolSyncService` 删除重复的探测队列，改为把预警池记录交给公共发现服务验证，但继续保留 `JOINED/LEFT`、revision、summary/records 和兼容性 heartbeat。

**技术栈：** Python 3.12、PySide6 `QObject/QTimer/QUdpSocket/QTcpSocket`、JSON 长度前缀帧、`ipaddress`、`secrets`、pytest、pytest-qt。

**设计规格：** `docs/superpowers/specs/2026-08-26-verified-peer-assisted-lan-discovery-design.md`

---

## 文件结构

**新增文件：**

- `src/petnest/core/lan_peer_discovery_protocol.py`：伙伴目录记录、帧编码、严格解码和 RFC 1918 端点验证。
- `src/petnest/core/lan_peer_discovery_state.py`：直接验证端点簿、候选去重、失败退避和有界调度的纯 Python 状态。
- `src/petnest/core/lan_peer_discovery_sync.py`：Qt 定时器编排、目录反熵、随机 token 生命周期和定向续期。
- `tests/test_lan_peer_discovery_protocol.py`：目录协议安全边界测试。
- `tests/test_lan_peer_discovery_state.py`：端点簿和候选状态测试。
- `tests/test_lan_peer_discovery_sync.py`：A-B-C 收敛、限频、续期和预警池候选复用测试。

**修改文件：**

- `src/petnest/core/lan_interaction.py`：presence 的 `extensions` 与 `probe_token`。
- `src/petnest/core/lan_service.py`：presence 上下文信号、并发候选挑战、目录帧传输和静默后台发送。
- `src/petnest/core/lan_pool_sync.py`：移除自己的候选验证队列，注入公共候选接收器。
- `src/petnest/app.py`：创建、启动、停止和连接新同步服务。
- `tests/test_lan_protocol.py`：presence 兼容性和 token 测试。
- `tests/test_lan_service.py`：挑战匹配、未经验证候选不可见和目录帧来源验证。
- `tests/test_lan_pool_sync.py`：验证预警池复用公共候选接收器且成员反熵不回归。
- `tests/test_app_and_platforms.py`：应用生命周期和禁用局域网时的停止顺序。

## 固定协议与限制

- Presence 扩展名：`peer_directory_v1`、`probe_token_v1`。
- `probe_token`：32 个小写十六进制字符，由 `secrets.token_hex(16)` 生成。
- 自动候选只允许 RFC 1918 IPv4 和 UDP/TCP `18487`。
- 每个目录最多 64 个端点；每个设备最多 4 个不同端点。
- 候选队列最多 128；并发挑战最多 8；启动速率最多 4 个/秒。
- 全局最多 60 次/分钟；每个转告设备最多 20 次/分钟。
- 单次挑战 4 秒超时；失败退避为 120、240、480、600 秒并封顶 600 秒。
- 定向续期每 8 秒最多 16 个端点；辅助发现端点 90 秒无直接握手后过期。
- 目录只发布 24 秒内直接验证且声明 `probe_token_v1` 的端点。

---

### 任务 1：扩展兼容的 presence 与随机挑战字段

**文件：**

- 修改：`src/petnest/core/lan_interaction.py:29-107,268-290`
- 修改：`tests/test_lan_protocol.py:13-68`

- [ ] **步骤 1：编写失败的 presence 扩展测试**

在 `tests/test_lan_protocol.py` 增加并更新以下测试：

```python
def test_hello_advertises_peer_discovery_without_changing_interaction_capabilities() -> None:
    packet = LanPacketCodec.hello(
        device_id="local-1",
        display_name="小平安",
        pet_name="平安",
        port=18487,
    )

    assert packet["capabilities"] == ["greeting", "heart", "text", "effect"]
    assert packet["extensions"] == ["peer_directory_v1", "probe_token_v1"]


def test_presence_round_trips_probe_token_and_accepts_legacy_without_extensions() -> None:
    token = "a" * 32
    packet = LanPacketCodec.hello(
        device_id="peer-1",
        display_name="小林",
        pet_name="橘猫",
        port=18487,
        probe_token=token,
    )

    decoded = LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))
    assert decoded["extensions"] == ("peer_directory_v1", "probe_token_v1")
    assert decoded["probe_token"] == token

    packet.pop("extensions")
    packet.pop("probe_token")
    legacy = LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))
    assert legacy["extensions"] == ()
    assert legacy["probe_token"] is None


@pytest.mark.parametrize("token", ["short", "A" * 32, "g" * 32, 123])
def test_presence_rejects_invalid_probe_token(token: object) -> None:
    packet = LanPacketCodec.hello(
        device_id="peer-1", display_name="小林", pet_name="橘猫", port=18487
    )
    packet["probe_token"] = token

    with pytest.raises(LanProtocolError, match="挑战"):
        LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))


def test_presence_ignores_unknown_bounded_top_level_field() -> None:
    packet = LanPacketCodec.hello(
        device_id="peer-1", display_name="小林", pet_name="橘猫", port=18487
    )
    packet["future_field"] = {"value": 1}

    decoded = LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))
    assert decoded["device_id"] == "peer-1"
```

同时把 `test_hello_packet_contains_identity_but_no_resource_path` 的完整字典期望补上：

```python
"extensions": ["peer_directory_v1", "probe_token_v1"],
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_protocol.py -q
```

预期：FAIL，指出 `hello()` 不接受 `probe_token` 或返回值缺少 `extensions`。

- [ ] **步骤 3：实现最小 presence 扩展**

在 `src/petnest/core/lan_interaction.py` 增加：

```python
LAN_PRESENCE_EXTENSIONS = ("peer_directory_v1", "probe_token_v1")
MAX_PRESENCE_EXTENSIONS = 16
MAX_PRESENCE_EXTENSION_LENGTH = 64
_EXTENSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PROBE_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def _extensions(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_PRESENCE_EXTENSIONS:
        raise LanProtocolError("设备扩展列表无效")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or _EXTENSION_RE.fullmatch(item) is None:
            raise LanProtocolError("设备扩展列表无效")
        if item not in normalized:
            normalized.append(item)
    return tuple(normalized)


def _probe_token(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _PROBE_TOKEN_RE.fullmatch(value) is None:
        raise LanProtocolError("设备验证挑战值无效")
    return value
```

将 `hello()` 和 `hello_ack()` 的签名统一为：

```python
def hello(
    cls,
    *,
    device_id: str,
    display_name: str,
    pet_name: str,
    port: int,
    alert_group_joined: bool | None = None,
    extensions: tuple[str, ...] = LAN_PRESENCE_EXTENSIONS,
    probe_token: str | None = None,
) -> dict[str, Any]:
```

编码时总是写入规范化的 `extensions`；仅在 token 非空时写入 `probe_token`。`hello_ack()` 必须把收到的 token 原样交给 `hello()`。`decode_presence()` 返回以下两个新增键：

```python
"extensions": _extensions(raw.get("extensions")),
"probe_token": _probe_token(raw.get("probe_token")),
```

不要修改现有 `capabilities` 内容或枚举校验。

- [ ] **步骤 4：运行协议测试确认通过**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_protocol.py -q
```

预期：全部 PASS。

- [ ] **步骤 5：提交 presence 协议变更**

```powershell
git add src/petnest/core/lan_interaction.py tests/test_lan_protocol.py
git commit -m fix:扩展局域网握手验证字段
```

---

### 任务 2：建立严格的伙伴目录帧协议

**文件：**

- 创建：`src/petnest/core/lan_peer_discovery_protocol.py`
- 创建：`tests/test_lan_peer_discovery_protocol.py`

- [ ] **步骤 1：编写目录协议失败测试**

创建 `tests/test_lan_peer_discovery_protocol.py`：

```python
from __future__ import annotations

import pytest

from petnest.core.lan_peer_discovery_protocol import (
    PeerDirectory,
    PeerDirectoryCodec,
    PeerDirectoryProtocolError,
    PeerEndpointRecord,
)


def endpoint(device_id: str, ip_address: str, age_seconds: int = 0) -> PeerEndpointRecord:
    return PeerEndpointRecord(device_id, ip_address, 18487, age_seconds)


def test_directory_frame_round_trip_allows_four_endpoints_for_one_device() -> None:
    records = tuple(endpoint("multi", f"192.168.{index}.20", index) for index in range(4))
    directory = PeerDirectory("bridge", records)

    assert PeerDirectoryCodec.decode_frame(PeerDirectoryCodec.encode_frame(directory)) == directory


def test_directory_rejects_public_special_and_nonstandard_endpoints() -> None:
    for address in ("8.8.8.8", "127.0.0.1", "169.254.1.2", "224.0.0.1"):
        with pytest.raises(ValueError):
            endpoint("peer", address)
    with pytest.raises(ValueError):
        PeerEndpointRecord("peer", "192.168.1.20", 22, 0)


def test_directory_rejects_duplicate_endpoint_and_more_than_four_per_device() -> None:
    item = endpoint("peer", "192.168.1.20")
    with pytest.raises(ValueError, match="duplicate"):
        PeerDirectory("bridge", (item, item))
    with pytest.raises(ValueError, match="four"):
        PeerDirectory(
            "bridge",
            tuple(endpoint("peer", f"192.168.{index}.20") for index in range(5)),
        )


def test_directory_decoder_rejects_wrong_size_version_and_extra_fields() -> None:
    frame = PeerDirectoryCodec.encode_frame(PeerDirectory("bridge", (endpoint("peer", "10.0.0.8"),)))
    with pytest.raises(PeerDirectoryProtocolError):
        PeerDirectoryCodec.decode_frame(frame[:-1])
    with pytest.raises(PeerDirectoryProtocolError):
        PeerDirectoryCodec.decode_frame(b"\x00\x00\x00\x02{}")
```

- [ ] **步骤 2：运行测试确认模块不存在**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_peer_discovery_protocol.py -q
```

预期：ERROR，`ModuleNotFoundError: petnest.core.lan_peer_discovery_protocol`。

- [ ] **步骤 3：实现目录模型和 codec**

创建 `src/petnest/core/lan_peer_discovery_protocol.py`，固定公共接口：

```python
DIRECTORY_PROTOCOL_VERSION = 1
MAX_DIRECTORY_RECORDS = 64
MAX_ENDPOINTS_PER_DEVICE = 4
MAX_DIRECTORY_FRAME_BYTES = 32 * 1024


class PeerDirectoryProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PeerEndpointRecord:
    device_id: str
    ip_address: str
    port: int
    age_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _identity(self.device_id))
        object.__setattr__(self, "ip_address", _private_ipv4(self.ip_address))
        if self.port != LAN_INTERACTION_PORT:
            raise ValueError("automatic discovery port must be 18487")
        if isinstance(self.age_seconds, bool) or not isinstance(self.age_seconds, int):
            raise ValueError("age_seconds must be an integer")
        if not 0 <= self.age_seconds <= 24:
            raise ValueError("age_seconds must be from 0 to 24")


@dataclass(frozen=True, slots=True)
class PeerDirectory:
    sender_device_id: str
    records: tuple[PeerEndpointRecord, ...]

    def __post_init__(self) -> None:
        sender = _identity(self.sender_device_id)
        records = tuple(self.records)
        if len(records) > MAX_DIRECTORY_RECORDS:
            raise ValueError("directory cannot contain more than 64 endpoints")
        keys = [(item.device_id, item.ip_address, item.port) for item in records]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate endpoint")
        counts = Counter(item.device_id for item in records)
        if any(count > MAX_ENDPOINTS_PER_DEVICE for count in counts.values()):
            raise ValueError("one device cannot contain more than four endpoints")
        object.__setattr__(self, "sender_device_id", sender)
        object.__setattr__(self, "records", tuple(sorted(records, key=lambda item: (
            item.device_id, item.ip_address, item.port
        ))))
```

`_private_ipv4()` 必须显式检查地址属于 `10/8`、`172.16/12` 或 `192.168/16`，不能只依赖语义更宽的 `IPv4Address.is_private`。`PeerDirectoryCodec.encode_frame()` 写入精确字段：

```python
{
    "version": 1,
    "kind": "peer_directory",
    "sender_device_id": directory.sender_device_id,
    "records": [
        {
            "device_id": item.device_id,
            "ip_address": item.ip_address,
            "port": item.port,
            "age_seconds": item.age_seconds,
        }
        for item in directory.records
    ],
}
```

codec 使用 4 字节大端长度前缀；解码必须核对声明长度、最大帧大小、UTF-8、JSON 根对象、精确顶层字段和精确记录字段，再构造 dataclass，把所有 `TypeError/ValueError/JSONDecodeError/UnicodeDecodeError` 转成 `PeerDirectoryProtocolError`。

- [ ] **步骤 4：运行目录协议测试**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_peer_discovery_protocol.py -q
```

预期：全部 PASS。

- [ ] **步骤 5：提交目录协议**

```powershell
git add src/petnest/core/lan_peer_discovery_protocol.py tests/test_lan_peer_discovery_protocol.py
git commit -m feat:添加安全伙伴目录协议
```

---

### 任务 3：实现多网卡端点簿、候选去重和失败退避

**文件：**

- 创建：`src/petnest/core/lan_peer_discovery_state.py`
- 创建：`tests/test_lan_peer_discovery_state.py`

- [ ] **步骤 1：编写纯状态失败测试**

创建 `tests/test_lan_peer_discovery_state.py`，覆盖固定行为：

```python
from petnest.core.lan_peer_discovery_protocol import PeerEndpointRecord
from petnest.core.lan_peer_discovery_state import (
    CandidateKey,
    CandidateQueue,
    DirectEndpointBook,
)


def test_endpoint_book_keeps_four_recent_addresses_and_projects_one_device() -> None:
    book = DirectEndpointBook(local_device_id="local")
    for index in range(5):
        book.observe(
            device_id="multi",
            ip_address=f"192.168.{index}.20",
            port=18487,
            extensions=("probe_token_v1",),
            verified_at=float(index),
            assisted=index == 4,
        )

    records = book.shareable_records(now=5.0)
    assert len(records) == 4
    assert {item.device_id for item in records} == {"multi"}
    assert book.preferred("multi").ip_address == "192.168.4.20"


def test_endpoint_book_only_shares_fresh_probe_capable_direct_endpoints() -> None:
    book = DirectEndpointBook(local_device_id="local")
    book.observe("old", "192.168.1.20", 18487, ("probe_token_v1",), 0.0, False)
    book.observe("legacy", "192.168.1.21", 18487, (), 23.0, False)
    book.observe("fresh", "192.168.1.22", 18487, ("probe_token_v1",), 23.0, False)

    assert book.shareable_records(now=24.5) == (
        PeerEndpointRecord("fresh", "192.168.1.22", 18487, 1),
    )


def test_candidate_queue_deduplicates_limits_and_applies_exponential_backoff() -> None:
    queue = CandidateQueue(local_device_id="local", maximum=2)
    key = CandidateKey("peer", "192.168.20.85", 18487)
    assert queue.offer(key, referrer_device_id="bridge", now=0.0)
    assert not queue.offer(key, referrer_device_id="bridge", now=1.0)
    assert queue.take_ready(now=1.0, limit=1) == (key,)

    queue.mark_failed(key, now=5.0)
    assert not queue.offer(key, referrer_device_id="bridge", now=100.0)
    assert queue.offer(key, referrer_device_id="bridge", now=126.0)
    queue.take_ready(now=126.0, limit=1)
    queue.mark_failed(key, now=130.0)
    assert queue.backoff_until(key) == 370.0


def test_candidate_queue_rejects_local_existing_and_over_limit_candidates() -> None:
    queue = CandidateQueue(local_device_id="local", maximum=1)
    assert not queue.offer(CandidateKey("local", "192.168.1.20", 18487), "bridge", 0.0)
    assert queue.offer(CandidateKey("one", "192.168.1.21", 18487), "bridge", 0.0)
    assert not queue.offer(CandidateKey("two", "192.168.1.22", 18487), "bridge", 0.0)
```

- [ ] **步骤 2：运行测试确认模块不存在**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_peer_discovery_state.py -q
```

预期：ERROR，模块不存在。

- [ ] **步骤 3：实现固定状态接口**

`src/petnest/core/lan_peer_discovery_state.py` 必须提供两个 frozen dataclass：

- `CandidateKey(device_id: str, ip_address: str, port: int = LAN_INTERACTION_PORT)`；`__post_init__()` 复用目录协议的身份、RFC 1918 地址和固定 `18487` 端口校验。
- `DirectEndpoint(key: CandidateKey, extensions: frozenset[str], verified_at: float, assisted: bool)`。

`DirectEndpointBook` 必须实现 `__init__(local_device_id, maximum_per_device=4)`、`observe(device_id, ip_address, port, extensions, verified_at, assisted)`、`preferred(device_id)`、`shareable_records(now)`、`assisted_keys(now)` 和 `expire(now)`。内部用 `dict[CandidateKey, DirectEndpoint]` 保存端点；返回多项时始终按 `(device_id, ip_address, port)` 排序。

`CandidateQueue` 必须实现 `__init__(local_device_id, maximum=128)`、`offer(key, referrer_device_id, now, already_verified=False)`、`take_ready(now, limit)`、`referrer(key)`、`mark_failed(key, now)`、`mark_verified(key)`、`backoff_until(key)` 和 `clear()`，并固定 `BACKOFF_SECONDS = (120, 240, 480, 600)`。

实现要求：

- `observe()` 对同一 `(device_id, IP, port)` 原位更新时间；超过 4 个时删除最旧端点。
- 普通端点 24 秒过期，`assisted=True` 的端点 90 秒过期。
- `shareable_records()` 只返回 24 秒内且含 `probe_token_v1` 的端点，并把年龄截断为整数 `0..24`。
- `CandidateKey` 自身验证 RFC 1918/18487，因此目录和预警池两条输入路径都不能绕过校验；`LanPeerDiscoverySyncService.offer_candidate()` 捕获构造 `CandidateKey` 时的 `TypeError/ValueError` 并返回 `False`。队列的 `offer()` 另外拒绝本机、已验证、队列重复、活动重复、负缓存未到期和超过上限。
- 失败次数只在失败时增加；成功后删除失败次数和负缓存。
- 队列保持插入顺序，不能使用无序 set 决定探测顺序。

- [ ] **步骤 4：运行纯状态测试**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_peer_discovery_state.py -q
```

预期：全部 PASS。

- [ ] **步骤 5：提交状态模块**

```powershell
git add src/petnest/core/lan_peer_discovery_state.py tests/test_lan_peer_discovery_state.py
git commit -m feat:添加伙伴端点与候选状态管理
```

---

### 任务 4：让局域网服务安全承载并发挑战和目录帧

**文件：**

- 修改：`src/petnest/core/lan_service.py:54-82,107-146,216-268,585-705,812-848,940-1018`
- 修改：`tests/test_lan_service.py`

- [ ] **步骤 1：编写候选不可见和挑战匹配失败测试**

在 `tests/test_lan_service.py` 增加：

```python
def test_candidate_ack_is_not_registered_until_token_identity_and_endpoint_match(qtbot) -> None:
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", port=18487
    )
    service._running = True
    service._send_packet = lambda *_args: True
    succeeded = []
    service.candidate_probe_succeeded.connect(succeeded.append)

    assert service.probe_candidate("peer", "192.168.20.85", token="a" * 32)
    wrong = LanPacketCodec.hello_ack(
        device_id="peer", display_name="同事", pet_name="猫", port=18487,
        probe_token="b" * 32,
    )
    service._handle_datagram(LanPacketCodec.encode(wrong), QHostAddress("192.168.20.85"), 18487)
    assert service.peers() == ()
    assert succeeded == []

    valid = LanPacketCodec.hello_ack(
        device_id="peer", display_name="同事", pet_name="猫", port=18487,
        probe_token="a" * 32,
    )
    service._handle_datagram(LanPacketCodec.encode(valid), QHostAddress("192.168.20.85"), 18487)
    assert [peer.device_id for peer in service.peers()] == ["peer"]
    assert succeeded[0].peer.device_id == "peer"


def test_candidate_ack_rejects_wrong_device_ip_source_port_and_advertised_port(qtbot) -> None:
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安")
    service._running = True
    service._send_packet = lambda *_args: True
    token = "c" * 32
    assert service.probe_candidate("expected", "192.168.20.85", token=token)

    cases = (
        ("wrong", "192.168.20.85", 18487, 18487),
        ("expected", "192.168.20.86", 18487, 18487),
        ("expected", "192.168.20.85", 18488, 18487),
        ("expected", "192.168.20.85", 18487, 18488),
    )
    for device_id, host, source_port, advertised_port in cases:
        packet = LanPacketCodec.hello_ack(
            device_id=device_id, display_name="设备", pet_name="猫",
            port=advertised_port, probe_token=token,
        )
        service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress(host), source_port)

    assert service.peers() == ()
```

- [ ] **步骤 2：编写目录帧来源验证失败测试**

增加一个在线 `LanPeer(device_id="bridge", display_name="桥接设备", pet_name="猫", ip_address="192.168.101.65", port=18487, online=True)`，向 `_read_chat_stream()` 或抽出的 `_handle_framed_payload()` 注入目录帧，断言：

```python
assert received_context.message.sender_device_id == "bridge"
assert received_context.address == "192.168.101.65"
```

然后分别用未知 sender ID 和错误 TCP 来源 IP 注入同一帧，断言 `peer_directory_received` 不发出。使用 fake socket 时必须提供 `peerAddress()`、`readAll()`、`abort()`，不要依赖真实网络。

- [ ] **步骤 3：运行相关测试确认失败**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_service.py -q
```

预期：FAIL，缺少 `probe_candidate`、`candidate_probe_succeeded` 或目录信号。

- [ ] **步骤 4：实现并发候选挑战**

在 `lan_service.py` 增加上下文：

```python
@dataclass(frozen=True, slots=True)
class VerifiedPresenceContext:
    peer: LanPeer
    address: str
    source_port: int
    extensions: tuple[str, ...]
    probe_token: str | None
    assisted: bool


@dataclass(frozen=True, slots=True)
class ReceivedPeerDirectory:
    message: PeerDirectory
    address: str


@dataclass(frozen=True, slots=True)
class _CandidateProbeTarget:
    device_id: str
    ip_address: str
    port: int
```

新增信号和状态：

```python
presence_verified = Signal(object)
candidate_probe_succeeded = Signal(object)
peer_directory_received = Signal(object)
self._candidate_probe_targets: dict[str, _CandidateProbeTarget] = {}
```

公共方法固定为 `probe_candidate(expected_device_id, ip_address, port=LAN_INTERACTION_PORT, *, token) -> bool`、`cancel_candidate_probe(token) -> None` 和 `send_direct_hello(ip_address, port=LAN_INTERACTION_PORT) -> bool`。`cancel_candidate_probe()` 只执行 `self._candidate_probe_targets.pop(token, None)`，可以重复调用。

`probe_candidate()` 必须复用目录协议的 RFC 1918 和端口校验，拒绝重复 token，登记目标后发送带 token 的 hello；发送失败立即删除目标。`_handle_datagram()` 的顺序必须是：

1. 解码 presence。
2. 对带 token 的 `hello_ack` 先查 `_candidate_probe_targets`。
3. token 未知或任一身份/端点字段不匹配时直接返回，不能调用 `_handle_presence()`。
4. 全部匹配时删除 token、注册 peer，并把同一个 `VerifiedPresenceContext(assisted=True, probe_token=token)` 依次发给 `presence_verified` 和 `candidate_probe_succeeded`；同步层不需要猜测 signal payload 类型。
5. 普通广播/手动/已保存 presence 保持现有路径，并发出 `presence_verified(assisted=False)`。
6. 收到带 token 的 `hello` 时正常注册发送方，并在 ack 原样回显 token。

`stop()` 必须清空 `_candidate_probe_targets`。

- [ ] **步骤 5：抽取后台 TCP 帧发送并接入目录 codec**

把现有聊天/预警池重复的“查在线 peer → 创建 `QTcpSocket` → 发送长度帧”抽成私有 `_send_peer_frame(target_device_id, frame, *, report_errors)`。现有聊天保持 `report_errors=True`；目录和预警池后台同步使用 `False`，不能向用户弹出后台反熵失败。

新增：

```python
def send_peer_directory(self, target_device_id: str, frame: bytes) -> bool:
    return self._send_peer_frame(target_device_id, frame, report_errors=False)
```

读取 TCP 帧时按以下顺序解码：目录帧、预警池帧、聊天帧。公共读缓冲上限取 `max(MAX_DIRECTORY_FRAME_BYTES, MAX_POOL_FRAME_BYTES, MAX_CHAT_PACKET_BYTES)`，各 codec 仍执行自己的较小上限，避免目录上限误伤已有预警池帧。目录/预警池都调用统一的 `_trusted_frame_sender(sender_device_id, socket)`，要求 sender 存在、在线且 `socket.peerAddress().toString() == sender.ip_address`。目录成功后发出 `ReceivedPeerDirectory`；失败只关闭该 socket 并限频记录 warning。

- [ ] **步骤 6：运行服务和协议回归测试**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_service.py tests\test_lan_chat.py tests\test_lan_pool_protocol.py tests\test_lan_protocol.py -q
```

预期：全部 PASS。

- [ ] **步骤 7：提交局域网传输变更**

```powershell
git add src/petnest/core/lan_service.py tests/test_lan_service.py
git commit -m feat:支持并发候选验证与目录传输
```

---

### 任务 5：实现伙伴目录反熵、候选调度和跨网段续期

**文件：**

- 创建：`src/petnest/core/lan_peer_discovery_sync.py`
- 创建：`tests/test_lan_peer_discovery_sync.py`

- [ ] **步骤 1：建立 FakeLanService 和失败测试**

创建 `tests/test_lan_peer_discovery_sync.py`，Fake 必须精确提供：

```python
class FakeLanService(QObject):
    presence_verified = Signal(object)
    candidate_probe_succeeded = Signal(object)
    peer_directory_received = Signal(object)
    peer_changed = Signal(object)
    peer_removed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.peer_values: tuple[LanPeer, ...] = ()
        self.directories: list[tuple[str, bytes]] = []
        self.probes: list[tuple[str, str, int, str]] = []
        self.cancelled: list[str] = []
        self.renewals: list[tuple[str, int]] = []

    def peers(self) -> tuple[LanPeer, ...]:
        return self.peer_values

    def send_peer_directory(self, target: str, frame: bytes) -> bool:
        self.directories.append((target, frame))
        return True

    def probe_candidate(self, device_id: str, ip: str, port: int, *, token: str) -> bool:
        self.probes.append((device_id, ip, port, token))
        return True

    def cancel_candidate_probe(self, token: str) -> None:
        self.cancelled.append(token)

    def send_direct_hello(self, ip: str, port: int) -> bool:
        self.renewals.append((ip, port))
        return True
```

测试至少包括以下具名用例，并按描述写出具体输入和断言：

- `test_bridge_directory_candidate_stays_hidden_until_direct_probe_succeeds`：目录进入后断言 `probes == []` 和 `endpoint_book.preferred("c") is None`；调用一次 `pump_candidates()` 后断言恰好一个 probe；只有匹配成功上下文到达后才出现 C。
- `test_sync_never_republishes_an_unverified_received_candidate`：收到 C 的目录但尚未验证时调用 `sync_reachable_peers()`，解码 Fake 保存的帧并断言记录中没有 C。
- `test_probe_pump_caps_concurrency_global_rate_and_referrer_rate`：注入 64 个候选，连续推进 fake clock，断言 pending 从不超过 8、任意 60 秒窗口不超过 60 次、同一 referrer 不超过 20 次。
- `test_probe_timeout_enters_backoff_and_cancels_service_token`：推进到 4 秒后调用 `expire_pending()`，断言 token 进入 `cancelled` 且端点在 120 秒内不能重新入队。
- `test_success_clears_backoff_and_records_assisted_endpoint`：先失败一次，再成功一次，断言负缓存为空且 `assisted is True`。
- `test_periodic_directory_sync_rotates_three_online_peers`：提供 5 个在线且支持目录扩展的 peer，连续两轮断言目标分别为前三个和后两个再循环首个。
- `test_renewal_round_sends_at_most_sixteen_assisted_endpoints`：写入 20 个 assisted 端点，断言单轮 `renewals` 增量为 16。
- `test_stop_clears_timers_pending_tokens_and_transient_state`：启动、入队并产生 pending 后停止，断言所有 timer inactive、pending/queue 清空且每个活动 token 都被取消。

在第一个测试中，先调用 `receive_directory("bridge", directory)`，断言 Fake 只增加 `probes`，没有 `peer_changed` 或可见 peer；再发出匹配的 `candidate_probe_succeeded` 上下文，断言端点簿才记录目标。

- [ ] **步骤 2：运行同步测试确认模块不存在**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_peer_discovery_sync.py -q
```

预期：ERROR，模块不存在。

- [ ] **步骤 3：实现同步服务公共接口和定时器**

创建 `LanPeerDiscoverySyncService(QObject)`，构造函数固定为：

```python
def __init__(
    self,
    lan_service: object,
    *,
    local_device_id: str,
    clock: Callable[[], float] = monotonic,
    token_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    parent: QObject | None = None,
) -> None:
```

公共方法固定为 `start()`、`stop()`、`offer_candidate(device_id, ip_address, port, *, referrer_device_id)`、`receive_directory(referrer_device_id, directory)`、`sync_reachable_peers()`、`pump_candidates()`、`expire_pending()` 和 `renew_assisted_peers()`。所有改变队列的方法只在 Qt 所在线程调用；`start()` 和 `stop()` 必须幂等。

内部状态和定时器：

```python
self.endpoint_book = DirectEndpointBook(local_device_id=local_device_id)
self.candidates = CandidateQueue(local_device_id=local_device_id)
self._pending: dict[str, tuple[CandidateKey, float]] = {}
self._sync_cursor = 0
self._renew_cursor = 0
self._global_attempts: deque[float] = deque()
self._referrer_attempts: dict[str, deque[float]] = {}

self._pump_timer.setInterval(250)
self._pending_timer.setInterval(250)
self._sync_timer.setInterval(30_000)
self._renew_timer.setInterval(8_000)
self._debounce_timer.setSingleShot(True)
self._debounce_timer.setInterval(500)
```

连接信号：

- `presence_verified` → 记录直接端点；只有 candidate success context 才标记 `assisted=True`。
- `candidate_probe_succeeded` → 按 token 取出 pending，`mark_verified()`，记录端点并触发目录 debounce。
- `peer_directory_received` → 只接受 message sender 与已验证 TCP sender 一致的上下文，然后调用 `receive_directory()`。
- `peer_changed` → 新在线伙伴触发 debounce。
- `peer_removed` → 不删除仍有其他直接端点的 device。

`pump_candidates()` 每次最多启动一个新挑战，以 250ms 间隔实现 4 次/秒；启动前清理 60 秒窗口，检查 `_pending < 8`、全局 `<60`、referrer `<20`。token 必须由 factory 生成且不与 pending 重复。发送失败按失败处理并进入退避。

`expire_pending()` 对超过 4 秒的 token 调用 `lan_service.cancel_candidate_probe(token)`，再 `mark_failed()`。

`sync_reachable_peers()` 每轮按 device ID 排序并轮询最多 3 个在线、声明 `peer_directory_v1` 的伙伴。目录记录来自 `endpoint_book.shareable_records(now=clock())`，排除目标自身和本机。

`renew_assisted_peers()` 每轮轮询最多 16 个 90 秒内 assisted key，调用 `send_direct_hello()`；不修改候选 token 状态。

- [ ] **步骤 4：实现 A-B-C 纯服务收敛测试**

在同一测试文件增加 `test_a_discovers_c_through_dual_homed_b_without_showing_phantoms`，使用确定性 fake network 执行以下完整流程：

1. 构造 A 的同步服务，发出 B 的 `VerifiedPresenceContext(address="192.168.101.65", assisted=False)`，断言端点簿只有 B。
2. 调用 `receive_directory("b", PeerDirectory("b", (PeerEndpointRecord("c", "192.168.20.85", 18487, 0),)))`，断言端点簿仍没有 C。
3. 调用 `pump_candidates()`，从 `fake.probes` 取出唯一的 `(device_id, ip, port, token)`，逐项断言为 C、`192.168.20.85`、`18487` 和 factory 产生的固定 token。
4. 先发出 token 改动一位的 `VerifiedPresenceContext`，断言 C 仍不可见且 pending 未删除；再发出完全匹配、`assisted=True` 的上下文，断言 C 写入端点簿、pending 和候选队列均为空。
5. 调用 `sync_reachable_peers()`，解码发送给 B 的目录帧，断言只含已经直接验证的 B/C 端点，且同一个 device 不重复投影为多个 UI peer。

- [ ] **步骤 5：运行同步状态与协议测试**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_peer_discovery_protocol.py tests\test_lan_peer_discovery_state.py tests\test_lan_peer_discovery_sync.py -q
```

预期：全部 PASS。

- [ ] **步骤 6：提交发现同步服务**

```powershell
git add src/petnest/core/lan_peer_discovery_sync.py tests/test_lan_peer_discovery_sync.py
git commit -m feat:实现跨网段伙伴辅助发现
```

---

### 任务 6：复用目录验证底座并保留预警池成员反熵

**文件：**

- 修改：`src/petnest/core/lan_pool_sync.py:20-310`
- 修改：`tests/test_lan_pool_sync.py:13-130`

- [ ] **步骤 1：把 FakeLanService 的重复探测期望改为公共 candidate sink**

在 `tests/test_lan_pool_sync.py` 修改 `_sync_node()`，明确注入：

```python
candidates: list[tuple[str, str, int, str]] = []
sync = LanPoolSyncService(
    lan,
    roster,
    display_name=lambda: device_id,
    offer_candidate=lambda target_id, ip, port, referrer: (
        candidates.append((target_id, ip, port, referrer)) or True
    ),
)
return SimpleNamespace(
    device_id=device_id,
    roster=roster,
    lan=lan,
    sync=sync,
    candidates=candidates,
)
```

把 `test_received_third_party_records_are_merged_and_queued_for_direct_verification` 更新为：

```python
assert a.candidates == [("b", third_party.ip_address, third_party.port, "d")]
assert a.lan.probes == []
```

再增加：

```python
def test_left_third_party_record_is_synced_but_not_offered_for_endpoint_verification(qtbot, tmp_path) -> None:
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1),))
    left = record("b", 2, state=PoolMemberState.LEFT)

    a.sync.receive_records("d", PoolRecords("d", (left,)))

    assert a.roster.records()["b"] == left
    assert a.candidates == []
```

- [ ] **步骤 2：运行预警池同步测试确认旧实现失败**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_pool_sync.py -q
```

预期：FAIL，因为构造函数没有 `offer_candidate`，旧逻辑仍调用 `lan.probe_peer()`。

- [ ] **步骤 3：删除预警池自己的验证队列并注入公共接收器**

`LanPoolSyncService.__init__()` 增加：

```python
offer_candidate: Callable[[str, str, int, str], bool] | None = None,
```

保存为 `self._offer_candidate = offer_candidate`。删除以下状态和连接：

```python
self._verification_queue
self._verification_queued_ids
self._active_verification
self._verification_timeout
manual_probe_succeeded -> _on_probe_succeeded
```

删除 `_queue_verification()`、`_pump_verification_queue()`、`_on_probe_succeeded()` 和 `_expire_active_verification()`。在 `receive_records()` 对 changed record 使用：

```python
if (
    self._offer_candidate is not None
    and device_id not in {sender_device_id, self.roster.local_device_id}
    and record.state is PoolMemberState.JOINED
):
    self._offer_candidate(
        record.device_id,
        record.ip_address,
        record.port,
        sender_device_id,
    )
```

保留 `PoolHeartbeat`、summary/records、revision 比较、`set_local_joined()`、周期三伙伴轮询和 roster 持久化。不要把 `alert_group_joined` 简化为临时目录布尔值。

- [ ] **步骤 4：运行预警池完整回归**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_pool_protocol.py tests\test_lan_pool_roster.py tests\test_lan_pool_sync.py -q
```

预期：全部 PASS；JOINED/LEFT 离线收敛测试仍通过。

- [ ] **步骤 5：提交预警池复用变更**

```powershell
git add src/petnest/core/lan_pool_sync.py tests/test_lan_pool_sync.py
git commit -m refactor:复用伙伴目录候选验证
```

---

### 任务 7：接入应用生命周期并验证不增加 UI 操作

**文件：**

- 修改：`src/petnest/app.py:61-66,429-455,1996-2006,2491-2508`
- 修改：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：编写应用启动停止顺序失败测试**

在 `tests/test_app_and_platforms.py` 对现有局域网配置测试增加 discovery 记录器。至少覆盖：

```python
def test_configure_lan_starts_discovery_before_pool_sync(application, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(application.lan_service, "start", lambda: calls.append("lan") or True)
    monkeypatch.setattr(application.lan_peer_discovery, "start", lambda: calls.append("discovery"))
    monkeypatch.setattr(application.lan_pool_sync, "start", lambda: calls.append("pool"))
    monkeypatch.setattr(application.lan_pool_sync, "set_local_joined", lambda *_args, **_kwargs: None)

    application._configure_lan_service()

    assert calls == ["lan", "discovery", "pool"]


def test_disabling_lan_stops_pool_then_discovery_then_transport(application, monkeypatch) -> None:
    calls: list[str] = []
    application.settings = replace(application.settings, lan_interaction_enabled=False)
    monkeypatch.setattr(application.lan_pool_sync, "stop", lambda: calls.append("pool"))
    monkeypatch.setattr(application.lan_peer_discovery, "stop", lambda: calls.append("discovery"))
    monkeypatch.setattr(application.lan_service, "stop", lambda: calls.append("lan"))

    application._configure_lan_service()

    assert calls == ["pool", "discovery", "lan"]
```

同时在 `PETNEST_TEST_DISABLE_LAN=1` 测试中断言 discovery 也不会启动。

- [ ] **步骤 2：运行应用生命周期测试确认失败**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_app_and_platforms.py -q
```

预期：FAIL，`PetNestApplication` 缺少 `lan_peer_discovery`。

- [ ] **步骤 3：接入发现服务和预警池 callback**

在 app 初始化中按顺序创建：

```python
self.lan_peer_discovery = LanPeerDiscoverySyncService(
    self.lan_service,
    local_device_id=self.settings.device_id,
    parent=self.window,
)
self.lan_pool_sync = LanPoolSyncService(
    self.lan_service,
    self.lan_pool_roster,
    display_name=lambda: display_name_for(self.settings),
    offer_candidate=lambda device_id, ip, port, referrer: self.lan_peer_discovery.offer_candidate(
        device_id,
        ip,
        port,
        referrer_device_id=referrer,
    ),
    parent=self.window,
)
```

生命周期固定为：

- 启动：`lan_service.start()` → `lan_peer_discovery.start()` → `lan_pool_sync.start()`。
- 禁用/测试禁用：`lan_pool_sync.stop()` → `lan_peer_discovery.stop()` → `lan_service.stop()`。
- 应用 shutdown 使用同样的逆序。

不修改 `LanInteractionDialog` 布局，不新增团队码、邀请、二维码、候选行或设置项。现有 `peer_changed/peer_removed` 已使验证成功的伙伴自动进入列表。

- [ ] **步骤 4：运行应用和局域网 UI 回归**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_app_and_platforms.py tests\test_lan_interactions.py tests\test_settings_dialog.py -q
```

预期：全部 PASS。

- [ ] **步骤 5：提交应用接入**

```powershell
git add src/petnest/app.py tests/test_app_and_platforms.py
git commit -m feat:接入跨网段伙伴发现生命周期
```

---

### 任务 8：安全回归、真实拓扑验收和提交整理

**文件：**

- 修改：`tests/test_lan_peer_discovery_sync.py`
- 验证：`docs/superpowers/specs/2026-08-26-verified-peer-assisted-lan-discovery-design.md`

- [ ] **步骤 1：补齐恶意输入和资源上限回归测试**

在同步测试中补齐以下用例，全部使用确定性 `clock` 和 `token_factory`，通过推进 fake clock 后直接调用方法，不真实等待 90 秒：

- `test_malicious_bridge_cannot_make_unverified_candidates_visible`：注入合法目录但不返回挑战，断言 probe 数为 1、端点状态为空、可见 peer 数不变。
- `test_directory_with_64_candidates_never_creates_more_than_8_pending_probes`：单轮逐次 pump 后断言恰好 8 个 pending 和 8 个不同 token，第 9 次不发送。
- `test_same_endpoint_from_directory_and_pool_is_only_probed_once`：先走目录、再调用公共 pool candidate sink，断言第二次返回 `False` 且 probe 总数仍为 1。
- `test_same_device_with_two_verified_subnet_addresses_projects_one_peer`：验证同一 device 的两个 RFC 1918 地址，断言端点簿有 2 个 key，但 `lan_service.peers()` 只投影 1 个 device。
- `test_bridge_shutdown_does_not_break_already_verified_a_c_renewal`：验证 C 后发出 B removed，推进 8 秒并续期，断言仍向 C 的地址发送一次 direct hello；推进到 C 端点 90 秒失效后，断言续期停止且 C 被清理。

每个测试都必须断言具体 probe 数量、token、候选状态、端点状态和可见 peer 数量。

- [ ] **步骤 2：运行所有局域网相关测试**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_lan_protocol.py tests\test_lan_discovery.py tests\test_lan_service.py tests\test_lan_chat.py tests\test_lan_peer_registry.py tests\test_lan_peer_discovery_protocol.py tests\test_lan_peer_discovery_state.py tests\test_lan_peer_discovery_sync.py tests\test_lan_pool_protocol.py tests\test_lan_pool_roster.py tests\test_lan_pool_sync.py tests\test_lan_interactions.py -q
```

预期：0 failures。

- [ ] **步骤 3：运行完整测试套件**

```powershell
.venv\Scripts\python.exe -m pytest -q
```

预期：至少 `1349 passed`，仅保留当前 Windows 不支持符号链接相关的 7 个 skip；如果出现原生 access violation，先单独运行崩溃测试，再完整重跑一次并记录两次结果，不能把崩溃当作通过。

- [ ] **步骤 4：检查协议和安全不变量**

运行：

```powershell
git diff --check
rg -n "probe_candidate|offer_candidate|peer_directory_v1|probe_token_v1" src tests
rg -n "Firebase|pair_code|team|团队码|二维码" src/petnest/core/lan_peer_discovery_*.py
```

预期：

- `git diff --check` 无输出。
- 新协议关键入口在实现和测试中均有覆盖。
- 新发现模块不依赖 Firebase、团队码或邀请逻辑。

- [ ] **步骤 5：整理最后一个测试提交**

```powershell
git add tests/test_lan_peer_discovery_sync.py
git commit -m test:覆盖跨网段发现安全边界
```

- [ ] **步骤 6：在真实 A-B-C 拓扑验收**

使用三台安装同一构建的设备：

1. A：仅连接 `192.168.101.x`。
2. C：仅连接 `192.168.20.x`。
3. B：同时能发现两个子网，例如具有 `192.168.101.65` 和 Wi-Fi 地址。
4. 确认 A 与 C 的 UDP/TCP `18487` 单播互通，但广播不跨网段。
5. 分别按 A→B→C、C→B→A、B 最后启动三种顺序测试。
6. 每种顺序下打开互动页，A 与 C 必须最终各只显示对方一次。
7. 在验证完成后退出 B；等待超过原广播过期时间，A 与 C 仍应通过定向续期保持在线。
8. 临时阻断 A-C 单播；90 秒后双方应消失，而不是变成大量离线或幽灵用户。
9. 让 C 加入再退出预警池；A 离线重启后仍应收到较新的 `LEFT` 状态，证明成员 revision 同步未被临时目录替代。

记录每台设备的 `device_id`、所有网卡 IP、发现耗时、是否出现重复项以及预警池最终状态。任何未经直接握手的候选都不得出现在 UI。

- [ ] **步骤 7：提交前审查提交序列**

```powershell
git status --short
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
```

预期：

- 只有本功能的受跟踪变更。
- 未跟踪宠物资源和工具文件未被暂存。
- 提交按“握手协议 → 目录协议 → 状态 → 传输 → 同步 → 预警池复用 → 应用接入 → 安全测试”排列。

如果需要压缩提交，只合并相邻且职责相同的提交；不要把设计、协议、实现和测试全部压成一个无法审查的巨型提交。

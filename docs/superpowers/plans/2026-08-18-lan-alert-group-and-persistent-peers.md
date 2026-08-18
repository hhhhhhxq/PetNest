# 局域网预警组与伙伴持久化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让手动验证的跨网段伙伴可持久化并自动重连，同时增加一个无群主、自愿加入的固定局域网预警组、组内聊天和带送达确认的全屏危险预警。

**架构：** 保留 `LanPeer` 作为实时状态，在独立 `KnownLanPeerRegistry` 中保存定向重连端点；预警组成员资格只由各设备的本机设置和握手声明决定。`LanInteractionService` 负责多接口发现、组内消息、预警确认/重试，UI 只消费明确的服务接口，`DangerAlertOverlay` 独立负责短时全屏视觉警示。

**技术栈：** Python 3.12、PySide6、Qt UDP/TCP 网络、dataclass/JSON、pytest、pytest-qt。

---

## 文件结构

- 创建 `src/petnest/core/lan_peer_registry.py`：已保存局域网伙伴模型、原子 JSON 存储和损坏恢复。
- 创建 `src/petnest/core/lan_discovery.py`：可测试的有效 IPv4 接口筛选与 Qt 接口适配。
- 创建 `src/petnest/ui/danger_alert.py`：预警确认对话框和全屏警示层；两者共享预警文案但职责独立。
- 创建 `tests/test_lan_peer_registry.py`：伙伴持久化、身份冲突和损坏恢复测试。
- 创建 `tests/test_lan_discovery.py`：多接口广播地址筛选测试。
- 创建 `tests/test_danger_alert.py`：确认框和全屏警示层测试。
- 修改 `src/petnest/models/settings.py`、`src/petnest/core/settings_manager.py`：保存本机是否加入固定预警组。
- 修改 `src/petnest/models/lan_interaction.py`：显式聊天范围、预警/确认/送达结果模型和预警组能力字段。
- 修改 `src/petnest/core/lan_interaction.py`：新旧握手兼容、预警组聊天范围、预警与确认编解码。
- 修改 `src/petnest/core/lan_service.py`：多接口广播、已保存伙伴重连、组内 fan-out、确认/重试/限流。
- 修改 `src/petnest/ui/lan_interaction_dialog.py`：固定预警组入口、加入/退出、已保存伙伴状态和组内聊天。
- 修改 `src/petnest/app.py`：注册表装配、右键预警、接收显示和送达反馈。
- 修改现有 `tests/test_settings_manager.py`、`tests/test_lan_protocol.py`、`tests/test_lan_service.py`、`tests/test_lan_chat.py`、`tests/test_lan_interactions.py`、`tests/test_app_and_platforms.py`：逐层回归覆盖。
- 修改 `README.md`：记录固定预警组、跨网段伙伴重连和网络边界。

### 任务 1：实现已保存局域网伙伴注册表

**文件：**
- 创建：`src/petnest/core/lan_peer_registry.py`
- 创建：`tests/test_lan_peer_registry.py`

- [ ] **步骤 1：编写注册表失败测试**

```python
from petnest.core.lan_peer_registry import KnownLanPeer, KnownLanPeerRegistry


def test_registry_round_trips_verified_peer_atomically(tmp_path):
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    peer = KnownLanPeer("peer-1", "小林", "192.168.20.12", 18487)

    registry.upsert(peer)

    assert KnownLanPeerRegistry(registry.path).load() == (peer,)


def test_registry_backs_up_corrupt_data_and_starts_empty(tmp_path):
    path = tmp_path / "known-lan-peers.json"
    path.write_text("not-json", encoding="utf-8")

    assert KnownLanPeerRegistry(path).load() == ()
    assert len(tuple(tmp_path.glob("known-lan-peers.json.corrupt-*.bak"))) == 1


def test_registry_does_not_rebind_a_saved_ip_to_another_device(tmp_path):
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("peer-1", "小林", "192.168.20.12", 18487))

    assert registry.matches_expected_identity("192.168.20.12", "peer-2") is False
    assert registry.load()[0].device_id == "peer-1"
```

- [ ] **步骤 2：运行测试确认模块尚不存在**

运行：

```powershell
$env:PYTHONPATH='src'
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_peer_registry.py -q
```

预期：FAIL，`ModuleNotFoundError: No module named 'petnest.core.lan_peer_registry'`。

- [ ] **步骤 3：实现最小注册表**

```python
@dataclass(frozen=True, slots=True)
class KnownLanPeer:
    device_id: str
    display_name: str
    ip_address: str
    port: int

    def __post_init__(self) -> None:
        if not self.device_id.strip() or len(self.device_id) > 64:
            raise ValueError("设备 ID 无效")
        if not self.display_name.strip() or len(self.display_name) > 40:
            raise ValueError("显示名称无效")
        if not isinstance(ip_address(self.ip_address), IPv4Address):
            raise ValueError("伙伴地址必须是 IPv4")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65_535:
            raise ValueError("伙伴端口无效")


class KnownLanPeerRegistry:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[KnownLanPeer, ...]:
        if not self.path.exists():
            return ()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != self.SCHEMA_VERSION:
                raise ValueError("伙伴注册表版本无效")
            records = raw.get("peers")
            if not isinstance(records, list):
                raise ValueError("伙伴记录必须是列表")
            peers = tuple(KnownLanPeer(**record) for record in records if isinstance(record, dict))
            if len({peer.device_id for peer in peers}) != len(peers):
                raise ValueError("伙伴设备 ID 重复")
            return tuple(sorted(peers, key=lambda item: item.display_name.casefold()))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self._backup_corrupt_file()
            return ()

    def upsert(self, peer: KnownLanPeer) -> None:
        peers = {item.device_id: item for item in self.load()}
        peers[peer.device_id] = peer
        self._save(tuple(peers.values()))

    def forget(self, device_id: str) -> None:
        self._save(tuple(item for item in self.load() if item.device_id != device_id))

    def matches_expected_identity(self, ip_address: str, device_id: str) -> bool:
        expected = next((item for item in self.load() if item.ip_address == ip_address), None)
        return expected is None or expected.device_id == device_id
```

实现 `_save()` 时写入 `{"schema_version": 1, "peers": [asdict(peer) for peer in peers]}`，使用 `.tmp`、`flush()`、`os.fsync()` 和 `Path.replace()`；实现 `_backup_corrupt_file()` 时沿用 `SettingsManager` 的时间戳备份模式。测试还要覆盖空设备 ID、非 IPv4 地址、重复设备 ID，以及 `bool` 不能充当端口。

- [ ] **步骤 4：运行注册表测试**

运行：同步骤 2。

预期：`3 passed`。

- [ ] **步骤 5：提交注册表**

```powershell
git add src/petnest/core/lan_peer_registry.py tests/test_lan_peer_registry.py
git commit -m "feat: persist verified LAN peers"
```

### 任务 2：保存本机预警组加入状态

**文件：**
- 修改：`src/petnest/models/settings.py:35-85`
- 修改：`src/petnest/core/settings_manager.py:185-205`
- 修改：`tests/test_settings_manager.py:150-205`

- [ ] **步骤 1：编写设置迁移失败测试**

```python
def test_alert_group_membership_round_trips_and_migrates(tmp_path):
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(lan_alert_group_joined=True))
    assert manager.load().lan_alert_group_joined is True

    raw = manager.load().to_dict()
    raw["schema_version"] = 22
    raw.pop("lan_alert_group_joined")
    manager.path.write_text(json.dumps(raw), encoding="utf-8")

    migrated = manager.load()
    assert migrated.lan_alert_group_joined is False
    assert migrated.schema_version == 23
```

- [ ] **步骤 2：运行单测确认字段不存在**

运行：

```powershell
$env:PYTHONPATH='src'
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_settings_manager.py::test_alert_group_membership_round_trips_and_migrates -q
```

预期：FAIL，`Settings.__init__()` 不接受 `lan_alert_group_joined`。

- [ ] **步骤 3：实现 schema 23 迁移**

```python
class Settings:
    SCHEMA_VERSION = 23
    # 保留现有字段顺序，在 LAN 设置附近新增：
    lan_alert_group_joined: bool = False
```

在 `SettingsManager._migrate()` 末尾增加：

```python
if version == 22:
    migrated.setdefault("lan_alert_group_joined", False)
    migrated["schema_version"] = Settings.SCHEMA_VERSION
```

- [ ] **步骤 4：运行设置测试**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_settings_manager.py tests/test_settings_dialog.py -q
```

预期：全部 PASS。

- [ ] **步骤 5：提交设置迁移**

```powershell
git add src/petnest/models/settings.py src/petnest/core/settings_manager.py tests/test_settings_manager.py
git commit -m "feat: persist LAN alert group membership"
```

### 任务 3：实现多网卡发现地址筛选

**文件：**
- 创建：`src/petnest/core/lan_discovery.py`
- 创建：`tests/test_lan_discovery.py`
- 修改：`src/petnest/core/lan_service.py:167-190`
- 修改：`tests/test_lan_service.py`

- [ ] **步骤 1：编写纯函数失败测试**

```python
from petnest.core.lan_discovery import InterfaceIPv4, eligible_broadcast_addresses


def test_discovery_uses_every_valid_unique_interface_broadcast():
    entries = (
        InterfaceIPv4("ethernet", True, True, False, "192.168.101.14", "192.168.101.255"),
        InterfaceIPv4("wifi", True, True, False, "192.168.20.8", "192.168.20.255"),
        InterfaceIPv4("duplicate", True, True, False, "192.168.20.9", "192.168.20.255"),
        InterfaceIPv4("tailscale", True, True, False, "169.254.83.107", "169.254.255.255"),
        InterfaceIPv4("loopback", True, True, True, "127.0.0.1", "127.255.255.255"),
        InterfaceIPv4("disconnected", False, False, False, "192.168.8.8", "192.168.8.255"),
    )

    assert eligible_broadcast_addresses(entries) == (
        "192.168.20.255",
        "192.168.101.255",
    )
```

- [ ] **步骤 2：运行测试确认模块不存在**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_discovery.py -q
```

预期：FAIL，缺少 `petnest.core.lan_discovery`。

- [ ] **步骤 3：实现筛选与 Qt 适配**

```python
@dataclass(frozen=True, slots=True)
class InterfaceIPv4:
    name: str
    is_up: bool
    is_running: bool
    is_loopback: bool
    address: str
    broadcast: str


def eligible_broadcast_addresses(entries: Iterable[InterfaceIPv4]) -> tuple[str, ...]:
    valid = {
        item.broadcast
        for item in entries
        if item.is_up
        and item.is_running
        and not item.is_loopback
        and item.broadcast
        and not ip_address(item.address).is_link_local
        and not ip_address(item.address).is_loopback
        and not ip_address(item.address).is_unspecified
    }
    return tuple(sorted(valid, key=lambda value: int(ip_address(value))))


def qt_interface_ipv4() -> tuple[InterfaceIPv4, ...]:
    values: list[InterfaceIPv4] = []
    flags_type = QNetworkInterface.InterfaceFlag
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        for entry in interface.addressEntries():
            if entry.ip().protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            values.append(
                InterfaceIPv4(
                    interface.humanReadableName(),
                    bool(flags & flags_type.IsUp),
                    bool(flags & flags_type.IsRunning),
                    bool(flags & flags_type.IsLoopBack),
                    entry.ip().toString(),
                    entry.broadcast().toString(),
                )
            )
    return tuple(values)
```

- [ ] **步骤 4：让 `discover()` 逐地址发送并保留兼容广播**

```python
def _presence_packet(self) -> dict[str, object]:
    return LanPacketCodec.hello(
        device_id=self.device_id,
        display_name=self.display_name,
        pet_name=self.pet_name,
        port=self._port,
    )

def discover(self) -> None:
    if not self._running:
        return
    packet = self._presence_packet()
    destinations = (*eligible_broadcast_addresses(qt_interface_ipv4()), "255.255.255.255")
    for address in dict.fromkeys(destinations):
        self._send_packet(packet, QHostAddress(address), self._port)
```

为 `LanInteractionService.__init__` 增加可注入 `interface_provider`，测试中传入固定条目，避免依赖 CI 网卡。

- [ ] **步骤 5：运行发现与服务测试**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_discovery.py tests/test_lan_service.py -q
```

预期：全部 PASS。

- [ ] **步骤 6：提交多网卡发现**

```powershell
git add src/petnest/core/lan_discovery.py src/petnest/core/lan_service.py tests/test_lan_discovery.py tests/test_lan_service.py
git commit -m "feat: discover peers across active LAN interfaces"
```

### 任务 4：接入已保存伙伴自动重连与列表状态

**文件：**
- 修改：`src/petnest/models/lan_interaction.py:20-40`
- 修改：`src/petnest/core/lan_service.py:43-224,496-545`
- 修改：`tests/test_lan_service.py`

- [ ] **步骤 1：编写重启重连与身份冲突失败测试**

```python
def test_service_probes_saved_peers_on_start(qtbot, tmp_path):
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("receiver", "接收方", "127.0.0.1", 19000))
    service = LanInteractionService(
        device_id="sender",
        display_name="发送方",
        pet_name="平安",
        port=0,
        peer_registry=registry,
    )
    sent = []
    service._send_packet = lambda packet, address, port: sent.append((address.toString(), port)) or True

    assert service.start()
    assert ("127.0.0.1", 19000) in sent
    service.stop()


def test_saved_peer_remains_visible_when_offline(qtbot, tmp_path):
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("peer", "小林", "192.168.20.12", 18487))
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", port=0, peer_registry=registry
    )

    peer = next(item for item in service.peers() if item.device_id == "peer")
    assert peer.online is False
    assert peer.saved is True
    assert peer.connection_state == "offline"
```

- [ ] **步骤 2：运行测试确认构造器不支持注册表**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_service.py -q
```

预期：新增测试 FAIL，`LanInteractionService.__init__()` 不接受 `peer_registry`。

- [ ] **步骤 3：扩展运行时设备状态**

```python
@dataclass(frozen=True, slots=True)
class LanPeer:
    # 保留现有字段
    saved: bool = False
    connection_state: str = "online"
    alert_group_supported: bool = False
    alert_group_joined: bool = False
```

在 `LanInteractionService.peers()` 中以实时 `_peers` 覆盖注册表离线投影；服务启动时把已保存记录标记为 `connecting` 并逐条定向发送 `hello`，超时后为 `offline`。新增 `_saved_probe_targets: dict[tuple[str, int], str]` 记录所有并发启动探测的“端点 → 预期 device_id”，不要复用只能容纳一个目标的 `_manual_probe_target`。手动探测成功后 `registry.upsert()`；`forget_peer(device_id)` 删除注册表记录但不修改远端预警状态。已保存设备过期时发出 `peer_changed` 的离线投影，只有未保存设备继续发出 `peer_removed`。

同时增加供确认框使用的只读方法：

```python
def unavailable_known_peers(self) -> tuple[LanPeer, ...]:
    return tuple(peer for peer in self.peers() if peer.saved and not peer.online)
```

- [ ] **步骤 4：拒绝错误身份并更新正确的新地址**

在 `_complete_manual_probe()` 和 `_handle_presence()` 中先调用注册表身份校验。保存 IP 回应其他 ID 时发出明确错误并保留旧记录；相同 `device_id` 在已验证握手中出现新 IP 时更新记录。

- [ ] **步骤 5：运行注册表与服务测试**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_peer_registry.py tests/test_lan_service.py -q
```

预期：全部 PASS。

- [ ] **步骤 6：提交伙伴重连**

```powershell
git add src/petnest/models/lan_interaction.py src/petnest/core/lan_service.py tests/test_lan_service.py
git commit -m "feat: reconnect saved LAN peers"
```

### 任务 5：增加预警组握手与显式聊天范围

**文件：**
- 修改：`src/petnest/models/lan_interaction.py:13-150`
- 修改：`src/petnest/core/lan_interaction.py:35-170`
- 修改：`src/petnest/core/lan_service.py:236-288,340-405`
- 修改：`tests/test_lan_protocol.py`
- 修改：`tests/test_lan_chat.py`

- [ ] **步骤 1：编写握手兼容和聊天范围失败测试**

```python
def test_presence_round_trips_optional_alert_membership_and_accepts_legacy_packet():
    packet = LanPacketCodec.hello(
        device_id="peer", display_name="小林", pet_name="平安", port=18487, alert_group_joined=True
    )
    assert LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))["alert_group_joined"] is True

    packet.pop("alert_group_joined")
    legacy = LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))
    assert legacy["alert_group_supported"] is False
    assert legacy["alert_group_joined"] is False


def test_alert_group_chat_only_fans_out_to_joined_compatible_peers(qtbot):
    service = LanInteractionService(
        device_id="sender", display_name="发送方", pet_name="平安", port=0,
        alert_group_joined=True,
    )
    sent = []
    try:
        assert service.start()
        service._peers = {
            "joined": LanPeer("joined", "甲", ip_address="127.0.0.1", port=19001,
                              alert_group_supported=True, alert_group_joined=True),
            "left": LanPeer("left", "乙", ip_address="127.0.0.1", port=19002,
                            alert_group_supported=True, alert_group_joined=False),
        }
        service._start_chat_send = lambda peer, frame, message: sent.append(peer.device_id)

        assert service.send_chat(ChatDraft.alert_group_text_message("注意安全"))
        assert sent == ["joined"]
    finally:
        service.stop()
```

- [ ] **步骤 2：运行目标测试确认签名与范围缺失**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_protocol.py tests/test_lan_chat.py -q
```

预期：新增测试 FAIL，`hello()` 缺少参数且 `ChatDraft` 缺少预警组构造器。

- [ ] **步骤 3：实现兼容握手字段**

```python
def hello(
    cls,
    *,
    device_id: str,
    display_name: str,
    pet_name: str,
    port: int,
    alert_group_joined: bool | None = None,
) -> dict[str, Any]:
    packet = {
        "version": LAN_PROTOCOL_VERSION,
        "kind": "hello",
        "device_id": _identity(device_id, "设备 ID"),
        "display_name": _bounded_text(display_name, "显示名称", MAX_DISPLAY_NAME_LENGTH),
        "pet_name": _bounded_text(pet_name, "宠物名称", MAX_PET_NAME_LENGTH),
        "port": _port(port),
        "capabilities": list(cls.capabilities),
    }
    if alert_group_joined is not None:
        packet["alert_group_joined"] = bool(alert_group_joined)
    return packet
```

`decode_presence()` 缺少字段时返回 `alert_group_supported=False`；存在且严格为布尔值时返回 supported/joined，其他类型拒绝。

增加回归断言：旧客户端发送的握手没有预警字段时仍能被发现，但只显示“不支持预警组”；新版不得向它发送预警组聊天或危险预警，普通私聊和 `LAN_ROOM` 群聊保持可用。

- [ ] **步骤 4：增加显式聊天范围并保留旧构造兼容**

```python
class ChatScope(StrEnum):
    DIRECT = "direct"
    LAN_ROOM = "lan_room"
    ALERT_GROUP = "alert_group"


@dataclass(frozen=True, slots=True)
class ChatDraft:
    # 保留旧 is_group 字段以兼容现有调用，再增加：
    scope: ChatScope | None = None

    def __post_init__(self) -> None:
        resolved = self.scope or (ChatScope.LAN_ROOM if self.is_group else ChatScope.DIRECT)
        object.__setattr__(self, "scope", resolved)
        object.__setattr__(self, "is_group", resolved is not ChatScope.DIRECT)

    @classmethod
    def alert_group_text_message(cls, text: str) -> "ChatDraft":
        return cls("@lan-alert-group", ChatMessageKind.TEXT, text=text, is_group=True,
                   scope=ChatScope.ALERT_GROUP)

    @classmethod
    def alert_group_emoji(cls, emoji: str) -> "ChatDraft":
        return cls("@lan-alert-group", ChatMessageKind.EMOJI, text=emoji, is_group=True,
                   scope=ChatScope.ALERT_GROUP)

    @classmethod
    def alert_group_image(cls, data: bytes, name: str) -> "ChatDraft":
        return cls("@lan-alert-group", ChatMessageKind.IMAGE, image_data=data, image_name=name,
                   is_group=True, scope=ChatScope.ALERT_GROUP)
```

`LanChatMessage` 同样保存规范化 `scope`。线上旧 `scope: "group"` 映射为 `LAN_ROOM`，新包使用 `scope: "alert_group"`。

- [ ] **步骤 5：让服务按范围选择收件人并校验接收资格**

普通 `LAN_ROOM` 保持发送给所有实时在线局域网设备；`ALERT_GROUP` 仅发送给 `alert_group_supported and alert_group_joined` 的设备。接收预警组聊天时，本机未加入或发送者未加入则拒绝。

在服务中集中处理本机状态变化：

```python
def update_alert_group_membership(self, joined: bool) -> None:
    if self.alert_group_joined == joined:
        return
    self.alert_group_joined = joined
    if self._running:
        self.discover()
        self._refresh_manual_peers()
```

- [ ] **步骤 6：运行协议与聊天测试**

运行：同步骤 2。

预期：全部 PASS，现有群聊测试不修改语义。

- [ ] **步骤 7：提交预警组聊天协议**

```powershell
git add src/petnest/models/lan_interaction.py src/petnest/core/lan_interaction.py src/petnest/core/lan_service.py tests/test_lan_protocol.py tests/test_lan_chat.py
git commit -m "feat: add fixed LAN alert group chat"
```

### 任务 6：实现危险预警、确认、重试和限流

**文件：**
- 修改：`src/petnest/models/lan_interaction.py`
- 修改：`src/petnest/core/lan_interaction.py`
- 修改：`src/petnest/core/lan_service.py`
- 修改：`tests/test_lan_protocol.py`
- 修改：`tests/test_lan_service.py`

- [ ] **步骤 1：编写预警协议失败测试**

```python
def test_danger_alert_and_ack_round_trip():
    alert = DangerAlert(
        "alert-1", "sender", "小林", "receiver", 1_800_000_000
    )
    decoded = LanPacketCodec.decode_danger_alert(
        LanPacketCodec.encode(LanPacketCodec.danger_alert(alert)),
        local_device_id="receiver",
        now=1_800_000_001,
    )
    assert decoded == alert

    ack = DangerAlertAck(alert.alert_id, "receiver", "sender")
    assert LanPacketCodec.decode_danger_alert_ack(
        LanPacketCodec.encode(LanPacketCodec.danger_alert_ack(ack)),
        local_device_id="sender",
    ) == ack
```

- [ ] **步骤 2：编写服务 fan-out 与去重失败测试**

```python
@pytest.fixture
def three_alert_services(qtbot):
    services = tuple(
        LanInteractionService(
            device_id=device_id,
            display_name=device_id,
            pet_name="平安",
            port=0,
            alert_group_joined=joined,
        )
        for device_id, joined in (("sender", True), ("joined", True), ("left", False))
    )
    sender, joined, left = services
    for service in services:
        assert service.start()
    for peer in (joined, left):
        assert sender.probe_peer("127.0.0.1", peer.port)
        qtbot.waitUntil(
            lambda peer=peer: any(item.device_id == peer.device_id for item in sender.peers()),
            timeout=2_000,
        )
    try:
        yield services
    finally:
        for service in services:
            service.stop()


def test_alert_reaches_only_joined_peer_and_reports_ack(qtbot, three_alert_services):
    sender, joined, left = three_alert_services
    received = []
    completed = []
    joined.danger_alert_received.connect(received.append)
    sender.danger_alert_delivery_completed.connect(completed.append)

    assert sender.send_danger_alert()
    qtbot.waitUntil(lambda: len(completed) == 1, timeout=2_000)

    assert len(received) == 1
    assert completed[0].acknowledged_device_ids == ("joined",)
    assert "left" not in completed[0].target_device_ids
```

- [ ] **步骤 3：运行新增测试确认模型缺失**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_protocol.py tests/test_lan_service.py -q
```

预期：FAIL，缺少 `DangerAlert`、`DangerAlertAck` 和服务信号。

- [ ] **步骤 4：实现不可变消息与结果模型**

```python
@dataclass(frozen=True, slots=True)
class DangerAlert:
    alert_id: str
    sender_device_id: str
    sender_name: str
    target_device_id: str
    created_at: int


@dataclass(frozen=True, slots=True)
class DangerAlertAck:
    alert_id: str
    sender_device_id: str
    target_device_id: str


@dataclass(frozen=True, slots=True)
class DangerAlertDeliveryResult:
    alert_id: str
    target_device_ids: tuple[str, ...]
    acknowledged_device_ids: tuple[str, ...]


@dataclass(slots=True)
class _PendingDangerAlert:
    target_device_ids: tuple[str, ...]
    packets: dict[str, dict[str, object]]
    acknowledged: set[str]
```

构造与解码统一复用现有 identity、显示名称、epoch 和包大小校验；预警只接受短时窗口内的时间戳。

- [ ] **步骤 5：实现服务状态机**

在 `LanInteractionService` 新增：

```python
danger_alert_received = Signal(object)
danger_alert_delivery_completed = Signal(object)

def alert_group_peers(self) -> tuple[LanPeer, ...]:
    return tuple(peer for peer in self._peers.values()
                 if peer.online and peer.alert_group_supported and peer.alert_group_joined)

def send_danger_alert(self) -> bool:
    now = self._clock()
    if not self.alert_group_joined:
        self.error.emit("请先加入局域网预警组")
        return False
    if now - self._last_alert_sent_at < 5.0:
        self.error.emit("预警发送过于频繁，请稍候")
        return False
    peers = self.alert_group_peers()
    if not peers:
        self.error.emit("预警组当前没有其他在线成员")
        return False
    alert_id = uuid.uuid4().hex
    created_at = int(time())
    packets = {
        peer.device_id: LanPacketCodec.danger_alert(
            DangerAlert(alert_id, self.device_id, self.display_name, peer.device_id, created_at)
        )
        for peer in peers
    }
    self._pending_alerts[alert_id] = _PendingDangerAlert(
        target_device_ids=tuple(packets), packets=packets, acknowledged=set()
    )
    for peer in peers:
        self._send_packet(packets[peer.device_id], QHostAddress(peer.ip_address), int(peer.port))
    self._last_alert_sent_at = now
    self._schedule_alert_retry(alert_id)
    self._schedule_alert_completion(alert_id)
    return True

def _schedule_alert_retry(self, alert_id: str) -> None:
    QTimer.singleShot(300, lambda: self._retry_unacknowledged_alert(alert_id))

def _schedule_alert_completion(self, alert_id: str) -> None:
    QTimer.singleShot(1_500, lambda: self._complete_alert_delivery(alert_id))

def _retry_unacknowledged_alert(self, alert_id: str) -> None:
    pending = self._pending_alerts.get(alert_id)
    if pending is None:
        return
    peers = {peer.device_id: peer for peer in self.alert_group_peers()}
    for device_id in pending.target_device_ids:
        if device_id in pending.acknowledged or device_id not in peers:
            continue
        peer = peers[device_id]
        self._send_packet(pending.packets[device_id], QHostAddress(peer.ip_address), int(peer.port))

def _complete_alert_delivery(self, alert_id: str) -> None:
    pending = self._pending_alerts.pop(alert_id, None)
    if pending is None:
        return
    self.danger_alert_delivery_completed.emit(
        DangerAlertDeliveryResult(
            alert_id,
            pending.target_device_ids,
            tuple(device_id for device_id in pending.target_device_ids
                  if device_id in pending.acknowledged),
        )
    )
```

为每个 pending 预警保存原始包、目标端点和确认集合：300ms 后仅重试未确认目标，1.5s 后发出 `DangerAlertDeliveryResult` 并清理。接收端在发送 ack 前登记最多 256 个近期 `alert_id`；同一发送者 60 秒内最多触发 3 次。

- [ ] **步骤 6：验证未知端点、过期、重复、退出组和频率限制**

为每个拒绝条件添加独立测试；使用可注入 clock，禁止测试依赖真实等待。确认 ack 只接受 pending 中预期的设备 ID 与地址。

- [ ] **步骤 7：运行预警协议与服务测试**

运行：同步骤 3。

预期：全部 PASS。

- [ ] **步骤 8：提交危险预警传输**

```powershell
git add src/petnest/models/lan_interaction.py src/petnest/core/lan_interaction.py src/petnest/core/lan_service.py tests/test_lan_protocol.py tests/test_lan_service.py
git commit -m "feat: deliver acknowledged LAN danger alerts"
```

### 任务 7：更新互动页面与伙伴管理

**文件：**
- 修改：`src/petnest/ui/lan_interaction_dialog.py:151-1121`
- 修改：`tests/test_lan_interactions.py`
- 修改：`tests/test_lan_chat.py`

- [ ] **步骤 1：编写固定入口与加入流程失败测试**

```python
def test_dialog_always_shows_alert_group_and_requires_join_before_chat(qtbot):
    changed = []
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local", lan_alert_group_joined=False),
        peers=[],
        on_alert_membership_changed=lambda joined: changed.append(joined) or True,
    )
    qtbot.addWidget(dialog)

    assert dialog.peer_list.item(0).data(Qt.ItemDataRole.UserRole) == "@lan-alert-group"
    dialog.peer_list.setCurrentRow(0)
    assert not dialog.chat_input.isEnabled()

    dialog.alert_join_button.click()
    assert changed == [True]
    assert dialog.chat_input.isEnabled()
```

- [ ] **步骤 2：编写设备状态和预警组聊天失败测试**

```python
def test_dialog_labels_saved_offline_and_unsupported_peers(qtbot):
    peers = (
        LanPeer("saved", "小林", ip_address="192.168.20.12", online=False,
                saved=True, connection_state="offline"),
        LanPeer("legacy", "小陈", ip_address="192.168.1.20", online=True,
                alert_group_supported=False),
    )
    dialog = LanInteractionDialog(settings=Settings(device_id="local"), peers=peers)
    qtbot.addWidget(dialog)

    text = "\n".join(dialog.peer_list.item(i).text() for i in range(dialog.peer_list.count()))
    assert "已保存 · 离线" in text
    assert "不支持预警组" in text
```

- [ ] **步骤 3：运行 UI 测试确认入口不存在**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_interactions.py tests/test_lan_chat.py -q
```

预期：新增测试 FAIL，缺少预警组入口和回调。

- [ ] **步骤 4：实现固定会话和加入/退出页面**

增加 `_ALERT_GROUP_DEVICE_ID = "@lan-alert-group"`。`_populate_peers()` 始终先添加“局域网预警组”和“局域网群聊”两个固定入口；没有普通在线设备时，局域网群聊入口显示“当前 0 台设备”并禁用发送，但不从列表消失。预警组未加入时显示说明与加入按钮，加入后启用聊天和成员列表。退出使用 `QMessageBox.question()` 确认并调用 `on_alert_membership_changed(False)`。

- [ ] **步骤 5：实现按状态渲染伙伴与管理动作**

为设备行集中实现 `_peer_status_text(peer)`：

```python
def _peer_status_text(peer: LanPeer) -> str:
    if peer.connection_state == "conflict":
        return "地址冲突"
    if peer.saved and not peer.online:
        return "已保存 · 离线"
    if peer.saved:
        return "已保存 · 在线"
    return "附近 · 在线"
```

为已保存设备增加右键“更新地址”“忘记此伙伴”，通过注入的 `on_update_peer_address` 与 `on_forget_peer` 回调处理，UI 不直接写注册表。

- [ ] **步骤 6：让聊天编辑器按预警组范围构造草稿**

选择预警组时文字、表情和图片分别创建 `ChatDraft.alert_group_text_message()`、`ChatDraft.alert_group_emoji()`、`ChatDraft.alert_group_image()`；选择普通群聊时继续创建 `group_text_message()`、`group_emoji()`、`group_image()`。聊天记录按 `ChatScope` 隔离。

- [ ] **步骤 7：运行互动与聊天 UI 测试**

运行：同步骤 3。

预期：全部 PASS。

- [ ] **步骤 8：提交互动页面**

```powershell
git add src/petnest/ui/lan_interaction_dialog.py tests/test_lan_interactions.py tests/test_lan_chat.py
git commit -m "feat: expose LAN alert group controls"
```

### 任务 8：实现确认框与全屏警示层

**文件：**
- 创建：`src/petnest/ui/danger_alert.py`
- 创建：`tests/test_danger_alert.py`

- [ ] **步骤 1：编写确认框失败测试**

```python
def test_confirm_dialog_lists_online_and_unavailable_recipients(qtbot):
    dialog = DangerAlertConfirmDialog(
        online=(LanPeer("one", "小林"), LanPeer("two", "小陈")),
        unavailable=(LanPeer("three", "小周", online=False, saved=True),),
    )
    qtbot.addWidget(dialog)

    assert "小林" in dialog.online_label.text()
    assert "小陈" in dialog.online_label.text()
    assert "小周" in dialog.unavailable_label.text()
    assert dialog.send_button.text() == "立即发送"
```

- [ ] **步骤 2：编写警示层屏幕与时间线失败测试**

```python
def test_overlay_uses_pet_screen_geometry_and_hides_after_three_peaks(qtbot):
    clock = FakeClock()
    overlay = DangerAlertOverlay(clock=clock)
    qtbot.addWidget(overlay)
    geometry = QRect(100, 200, 1920, 1080)

    overlay.show_alert("alert-1", "小林", geometry)
    assert overlay.geometry() == geometry
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    observed = []
    for elapsed in (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5):
        clock.value = elapsed
        overlay._refresh()
        observed.append(overlay.red_alpha)
    assert count_local_peaks(observed) == 3
    assert not overlay.isVisible()
```

在同一测试文件顶部定义确定性时钟和峰值计数：

```python
class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def count_local_peaks(values: list[int]) -> int:
    return sum(
        1
        for index in range(1, len(values) - 1)
        if values[index] > values[index - 1] and values[index] > values[index + 1]
    )
```

- [ ] **步骤 3：运行测试确认模块不存在**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_danger_alert.py -q
```

预期：FAIL，缺少 `petnest.ui.danger_alert`。

- [ ] **步骤 4：实现确认对话框**

使用 `QDialog`、两个只读收件人区域和 `QDialogButtonBox`；发送按钮设置危险样式并仅在 `online` 非空时启用。对话框不启动网络请求，只通过 `Accepted` 返回确认。

- [ ] **步骤 5：实现警示层**

```python
class DangerAlertOverlay(QWidget):
    DURATION_SECONDS = 1.5
    PEAK_COUNT = 3

    def show_alert(self, alert_id: str, sender_name: str, geometry: QRect) -> None:
        if alert_id in self._seen_ids:
            return
        self._seen_ids.add(alert_id)
        self.setGeometry(geometry)
        self._sender_name = sender_name
        self._started_at = self._clock()
        self.show()
        self.raise_()
        self.timer.start()

    def _refresh(self) -> None:
        elapsed = self._clock() - self._started_at
        if elapsed >= self.DURATION_SECONDS:
            self.timer.stop()
            self.hide()
            return
        phase = elapsed / self.DURATION_SECONDS * self.PEAK_COUNT
        self.red_alpha = round(55 + 105 * (0.5 - 0.5 * cos(phase * 2 * pi)))
        self.update()
```

窗口 flags 与下班提醒透明层一致，并增加中央标题/发送者绘制。测试时确认 `WindowDoesNotAcceptFocus`、`WA_ShowWithoutActivating` 和鼠标穿透。

- [ ] **步骤 6：运行全屏警示 UI 测试**

运行：同步骤 3。

预期：全部 PASS。

- [ ] **步骤 7：提交预警 UI 组件**

```powershell
git add src/petnest/ui/danger_alert.py tests/test_danger_alert.py
git commit -m "feat: add full-screen danger alert overlay"
```

### 任务 9：在应用中装配伙伴、预警组和右键流程

**文件：**
- 修改：`src/petnest/app.py:168-360,553-650,743-803,943-985,1368-1426`
- 修改：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：编写应用装配失败测试**

```python
def test_app_uses_peer_registry_next_to_settings_and_exposes_alert_action(qtbot, tmp_path):
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    manager = SettingsManager(tmp_path / "config" / "settings.json")
    app = PetNest(pets_root=tmp_path / "pets", settings_manager=manager, enable_tray=False)
    qtbot.addWidget(app.window)

    assert app.peer_registry.path == manager.path.parent / "known-lan-peers.json"
    assert app.danger_alert_action.text() == "⚠  发送危险预警"
    app.shutdown()
```

- [ ] **步骤 2：编写接收屏幕与发送结果失败测试**

```python
def test_app_shows_received_alert_on_pet_screen(qtbot, tmp_path, monkeypatch):
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    petnest_app = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(petnest_app.window)
    shown = []
    monkeypatch.setattr(petnest_app.danger_alert_overlay, "show_alert", lambda *args: shown.append(args))
    monkeypatch.setattr(petnest_app, "_pet_screen_geometry", lambda: QRect(10, 20, 800, 600))

    petnest_app._handle_danger_alert(
        DangerAlert("alert-1", "peer", "小林", petnest_app.settings.device_id, int(time()))
    )

    assert shown == [("alert-1", "小林", QRect(10, 20, 800, 600))]
    petnest_app.shutdown()
```

- [ ] **步骤 3：运行应用测试确认组件未装配**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_app_and_platforms.py -q
```

预期：新增测试 FAIL，缺少 `peer_registry`、`danger_alert_action` 和 overlay。

- [ ] **步骤 4：装配注册表、服务与互动页面回调**

在 `PetNest.__init__` 中先创建：

```python
self.peer_registry = KnownLanPeerRegistry(
    self.settings_manager.path.parent / "known-lan-peers.json"
)
self.lan_service = LanInteractionService(
    device_id=self.settings.device_id,
    display_name=display_name_for(self.settings),
    pet_name=self.package.name,
    parent=self.window,
    peer_registry=self.peer_registry,
    alert_group_joined=self.settings.lan_alert_group_joined,
)
```

互动页面加入/退出回调调用 `apply_settings(replace(self.settings, lan_alert_group_joined=joined))`，并立即调用 `lan_service.update_alert_group_membership(joined)`；忘记/更新地址通过服务方法完成。

- [ ] **步骤 5：装配右键确认与异步结果**

在缩放操作前增加独立分隔区和 `danger_alert_action`。触发方法：

```python
def _confirm_danger_alert(self) -> None:
    if not self.settings.lan_alert_group_joined:
        self._show_alert_group_join_required()
        return
    online = self.lan_service.alert_group_peers()
    dialog = DangerAlertConfirmDialog(online=online, unavailable=self.lan_service.unavailable_known_peers(), parent=self.window)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        self.lan_service.send_danger_alert()

def _show_alert_group_join_required(self) -> None:
    QMessageBox.information(self.window, "尚未加入预警组", "请先在互动页面加入局域网预警组。")
    self.show_lan_interaction_dialog()
```

处理 `danger_alert_delivery_completed` 时以 `acknowledged_device_ids` 生成真实送达气泡，不使用 socket 写入结果冒充送达。

- [ ] **步骤 6：装配接收警示与目标屏幕选择**

```python
def _pet_screen_geometry(self) -> QRect:
    center = self.window.frameGeometry().center()
    screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
    return screen.geometry() if screen is not None else self.window.screen().geometry()

def _handle_danger_alert(self, alert: DangerAlert) -> None:
    self.danger_alert_overlay.show_alert(alert.alert_id, alert.sender_name, self._pet_screen_geometry())
```

警示层不隐藏桌宠。下班提醒已显示时，调用 `raise_()` 保证预警层暂时位于其上方。

- [ ] **步骤 7：实现 shutdown 清理和设置变更同步**

`shutdown()` 停止 overlay timer，并在停止 LAN 服务前清理 pending alert timers。`apply_settings()` 仅在加入状态变化时发送新 presence，不重启无关组件。

- [ ] **步骤 8：运行应用与窗口回归测试**

运行：

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_app_and_platforms.py tests/test_pet_window.py tests/test_work_finish_reminder.py -q
```

预期：全部 PASS。

- [ ] **步骤 9：提交应用装配**

```powershell
git add src/petnest/app.py tests/test_app_and_platforms.py
git commit -m "feat: integrate LAN danger alert workflow"
```

### 任务 10：端到端回归、文档与人工网络验证

**文件：**
- 修改：`README.md:130-150`
- 修改：`tests/test_lan_service.py`，增加三设备范围隔离集成测试。
- 验证：`src/petnest/core/lan_peer_registry.py`、`src/petnest/core/lan_discovery.py`、`src/petnest/models/settings.py`、`src/petnest/models/lan_interaction.py`、`src/petnest/core/lan_interaction.py`、`src/petnest/core/lan_service.py`、`src/petnest/ui/lan_interaction_dialog.py`、`src/petnest/ui/danger_alert.py`、`src/petnest/app.py`，只对测试证明存在的问题做对应修改。

- [ ] **步骤 1：增加三设备集成测试**

在 `tests/test_lan_service.py` 增加：

```python
def test_three_devices_keep_lan_room_and_alert_group_scopes_separate(qtbot, three_alert_services):
    sender, joined, left = three_alert_services
    joined_chat, left_chat, joined_alert, left_alert = [], [], [], []
    joined.chat_message_received.connect(joined_chat.append)
    left.chat_message_received.connect(left_chat.append)
    joined.danger_alert_received.connect(joined_alert.append)
    left.danger_alert_received.connect(left_alert.append)

    assert sender.send_chat(ChatDraft.group_text_message("全员消息"))
    qtbot.waitUntil(lambda: len(joined_chat) == len(left_chat) == 1, timeout=2_000)
    assert sender.send_chat(ChatDraft.alert_group_text_message("预警组消息"))
    assert sender.send_danger_alert()
    qtbot.waitUntil(lambda: len(joined_alert) == 1, timeout=2_000)

    assert [item.scope for item in joined_chat] == [ChatScope.LAN_ROOM, ChatScope.ALERT_GROUP]
    assert [item.scope for item in left_chat] == [ChatScope.LAN_ROOM]
    assert left_alert == []
```

- [ ] **步骤 2：运行局域网专项测试**

运行：

```powershell
$env:PYTHONPATH='src'
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_peer_registry.py tests/test_lan_discovery.py tests/test_lan_protocol.py tests/test_lan_service.py tests/test_lan_chat.py tests/test_lan_interactions.py tests/test_danger_alert.py -q
```

预期：全部 PASS，0 failures。

- [ ] **步骤 3：更新 README**

在局域网互动说明中明确：

```markdown
- “局域网预警组”是无群主的固定频道，用户自行加入或退出；只有在线且已加入的成员接收组内聊天和危险预警。
- 手动连接 IP 成功后会保存该伙伴，应用以后自动定向重连；这可覆盖可单播互通但广播无法跨越的其他办公子网。
- 自动发现会向每个有效 IPv4 接口广播，但不会主动扫描整个网段；跨 VLAN 仍需首次手动添加或由网络管理员配置发现转发。
```

- [ ] **步骤 4：运行完整测试套件**

运行：

```powershell
$env:PYTHONPATH='src'
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest -q
```

预期：不低于基线 `660 passed, 4 skipped`，0 failures；新增测试使 passed 数量上升，Windows 符号链接权限相关的 4 个 skip 可保持。

- [ ] **步骤 5：运行静态与差异检查**

```powershell
git diff --check
git status --short
git log --oneline --decorate -10
```

预期：`git diff --check` 无输出；状态中只包含本功能明确修改的文件；提交历史按任务递增。

- [ ] **步骤 6：人工枚举当前广播地址**

```powershell
$env:PYTHONPATH='src'
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -c "from petnest.core.lan_discovery import eligible_broadcast_addresses, qt_interface_ipv4; print(eligible_broadcast_addresses(qt_interface_ipv4()))"
```

当前环境预期至少包含 `192.168.101.255`，且不包含 Tailscale/WLAN 的 `169.254.255.255`。若此时 Wi-Fi 已取得正常地址，还应同时包含其广播地址。

- [ ] **步骤 7：提交文档和最终集成调整**

```powershell
git add README.md tests src
git commit -m "docs: document LAN alert group workflow"
```

- [ ] **步骤 8：完成前验证**

重新运行步骤 2、4、5、6，并记录精确通过数、跳过数、当前分支和未提交状态。只有新鲜输出显示 0 failures 时才能宣布实现完成。

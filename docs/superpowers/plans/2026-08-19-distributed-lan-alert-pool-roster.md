# 分布式局域网预警池名单同步实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让固定局域网预警池的成员名单在所有已建立连接的广播域之间持续、持久、断线可补偿地同步，并分别展示已加入、在线和可发送人数。

**架构：** 新增独立 `PoolRosterStore` 保存每设备自有 revision 记录，新增 `LanPoolPacketCodec` 处理 heartbeat/summary/records，新增 `LanPoolSyncService` 负责比较摘要、交换差异和排队验证跨网段端点。现有 `LanInteractionService` 只增加受限的 pool UDP/TCP 传输入口，应用和 UI 消费同步服务提供的成员视图，不再从实时 `_peers` 推断成员总数。

**技术栈：** Python 3.12、PySide6、Qt UDP/TCP、dataclass/JSON、pytest、pytest-qt。

---

## 文件结构

- 创建 `src/petnest/models/lan_pool.py`：成员状态、成员记录、合并结果和 UI 成员视图。
- 创建 `src/petnest/core/lan_pool_roster.py`：名单合并、revision 管理、摘要和原子 JSON 持久化。
- 创建 `src/petnest/core/lan_pool_protocol.py`：heartbeat、summary、records 的严格编解码和大小限制。
- 创建 `src/petnest/core/lan_pool_sync.py`：心跳、名单校对、周期同步、跨网段端点验证队列。
- 创建 `tests/test_lan_pool_roster.py`、`tests/test_lan_pool_protocol.py`、`tests/test_lan_pool_sync.py`。
- 修改 `src/petnest/core/lan_service.py`：pool 数据报/帧信号、通用 TCP 帧分派和受限发送 API。
- 修改 `src/petnest/ui/lan_interaction_dialog.py`：成员总数、在线数、可发送数和名单视图。
- 修改 `src/petnest/app.py`：装配 roster/sync，加入退出改为产生自有记录，发送使用同步成员视图。
- 修改 `tests/test_lan_service.py`、`tests/test_lan_chat.py`、`tests/test_lan_interactions.py`、`tests/test_app_and_platforms.py`。
- 修改 `README.md`：说明开放池名单同步、跨网段桥接和不可消除的首次入口边界。

### 任务 1：实现成员记录、合并与原子存储

**文件：**
- 创建：`src/petnest/models/lan_pool.py`
- 创建：`src/petnest/core/lan_pool_roster.py`
- 创建：`tests/test_lan_pool_roster.py`

- [ ] **步骤 1：编写 revision 与 tombstone 失败测试**

```python
def test_newer_revision_wins_and_left_tombstone_blocks_old_joined(tmp_path):
    store = PoolRosterStore(tmp_path / "lan-alert-pool-roster.json", local_device_id="local")
    joined = PoolMemberRecord("peer", "小林", PoolMemberState.JOINED, 1, "192.168.1.20", 18487, 1)
    left = replace(joined, state=PoolMemberState.LEFT, revision=2)

    assert store.merge((joined,)).changed_device_ids == ("peer",)
    assert store.merge((left,)).changed_device_ids == ("peer",)
    assert store.merge((joined,)).changed_device_ids == ()
    assert store.records()["peer"].state is PoolMemberState.LEFT
```

```python
def test_equal_revision_conflict_waits_for_direct_owner(tmp_path):
    store = PoolRosterStore(tmp_path / "roster.json", local_device_id="local")
    first = PoolMemberRecord("peer", "小林", PoolMemberState.JOINED, 3, "192.168.1.20", 18487, 1)
    conflict = replace(first, display_name="伪造昵称")
    store.merge((first,), directly_verified_ids={"peer"})

    result = store.merge((conflict,))

    assert result.conflicted_device_ids == ("peer",)
    assert store.records()["peer"] == first
```

- [ ] **步骤 2：运行测试确认模块不存在**

运行：

```powershell
$env:PYTHONPATH='src'
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_pool_roster.py -q
```

预期：FAIL，缺少 `petnest.models.lan_pool` 或 `petnest.core.lan_pool_roster`。

- [ ] **步骤 3：实现最小模型和逐设备合并**

```python
class PoolMemberState(StrEnum):
    JOINED = "joined"
    LEFT = "left"


@dataclass(frozen=True, slots=True)
class PoolMemberRecord:
    device_id: str
    display_name: str
    state: PoolMemberState
    revision: int
    ip_address: str
    port: int
    protocol_version: int = 1


@dataclass(frozen=True, slots=True)
class PoolMergeResult:
    changed_device_ids: tuple[str, ...] = ()
    local_newer_device_ids: tuple[str, ...] = ()
    conflicted_device_ids: tuple[str, ...] = ()
```

`PoolMemberRecord.__post_init__()` 严格验证 device ID、40 字昵称、state、正整数 revision、IPv4、非 bool 端口和协议版本。`PoolRosterStore.merge()` 逐 device ID 比较 revision；同 revision 不同内容只在远端记录来自该 device ID 的直接验证连接时允许覆盖。

- [ ] **步骤 4：增加自有 revision 失败测试并实现**

```python
def test_local_record_revision_increments_for_join_leave_name_and_endpoint(tmp_path):
    store = PoolRosterStore(tmp_path / "roster.json", local_device_id="local")
    first = store.update_local(display_name="本机", state=PoolMemberState.JOINED,
                               ip_address="192.168.1.10", port=18487)
    same = store.update_local(display_name="本机", state=PoolMemberState.JOINED,
                              ip_address="192.168.1.10", port=18487)
    left = store.update_local(display_name="本机", state=PoolMemberState.LEFT,
                              ip_address="192.168.1.10", port=18487)

    assert (first.revision, same.revision, left.revision) == (1, 1, 2)
```

`update_local()` 仅在内容变化时递增，并拒绝调用方更新非本机 device ID。

- [ ] **步骤 5：增加原子存储与上限测试并实现**

测试 round-trip、损坏备份、备份失败写保护、replace 失败保留旧文件、重复 device ID、257 条记录拒绝。存储格式：

```json
{
  "schema_version": 1,
  "local_device_id": "...",
  "local_revision": 4,
  "records": []
}
```

复用 `KnownLanPeerRegistry` 的 `.tmp + fsync + replace` 模式，不复制不安全的宽泛异常处理。

- [ ] **步骤 6：运行名单测试并提交**

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_pool_roster.py -q
git add src/petnest/models/lan_pool.py src/petnest/core/lan_pool_roster.py tests/test_lan_pool_roster.py
git commit -m "feat: 添加分布式预警池成员名单存储"
```

预期：名单测试全部 PASS。

### 任务 2：实现受限名单同步协议

**文件：**
- 创建：`src/petnest/core/lan_pool_protocol.py`
- 创建：`tests/test_lan_pool_protocol.py`

- [ ] **步骤 1：编写 heartbeat、summary 和 records 失败测试**

```python
def test_pool_protocol_round_trips_heartbeat_summary_and_records():
    record = PoolMemberRecord("peer", "小林", PoolMemberState.JOINED, 3,
                              "192.168.1.20", 18487, 1)
    heartbeat = PoolHeartbeat("petnest_lan_alert_pool_v1", "peer", record, "a" * 64, 2)
    summary = PoolSummary("peer", (("peer", 3), ("other", 2)))
    records = PoolRecords("peer", (record,))

    assert LanPoolPacketCodec.decode_heartbeat(LanPoolPacketCodec.encode_heartbeat(heartbeat)) == heartbeat
    assert LanPoolPacketCodec.decode_frame(LanPoolPacketCodec.encode_summary(summary)) == summary
    assert LanPoolPacketCodec.decode_frame(LanPoolPacketCodec.encode_records(records)) == records
```

- [ ] **步骤 2：运行测试确认协议模块不存在**

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_pool_protocol.py -q
```

预期：FAIL，缺少 `lan_pool_protocol`。

- [ ] **步骤 3：实现不可变消息和 codec**

```python
POOL_ID = "petnest_lan_alert_pool_v1"
POOL_PROTOCOL_VERSION = 1
MAX_POOL_RECORDS = 256
MAX_POOL_UDP_BYTES = 8 * 1024
MAX_POOL_FRAME_BYTES = 256 * 1024

@dataclass(frozen=True, slots=True)
class PoolHeartbeat:
    pool_id: str
    sender_device_id: str
    sender_record: PoolMemberRecord
    roster_digest: str
    record_count: int

@dataclass(frozen=True, slots=True)
class PoolSummary:
    sender_device_id: str
    revisions: tuple[tuple[str, int], ...]

@dataclass(frozen=True, slots=True)
class PoolRecords:
    sender_device_id: str
    records: tuple[PoolMemberRecord, ...]
```

Heartbeat 使用 UDP JSON envelope；summary/records 使用现有 4 字节长度前缀 TCP frame。所有 decoder 拒绝未知字段类型、重复 device ID、超限条目、非法 digest、错误 pool/protocol 版本和超大 payload。

- [ ] **步骤 4：增加恶意输入测试**

覆盖 257 条 summary、重复 ID、records 非列表、31 字以上昵称、非 IPv4、bool revision、错误 pool ID、超大 frame。每个测试断言稳定 `LanPoolProtocolError`，不能泄漏原始 JSON 异常。

- [ ] **步骤 5：运行协议测试并提交**

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_pool_protocol.py -q
git add src/petnest/core/lan_pool_protocol.py tests/test_lan_pool_protocol.py
git commit -m "feat: 添加预警池名单同步协议"
```

### 任务 3：扩展局域网传输层以承载名单同步

**文件：**
- 修改：`src/petnest/core/lan_service.py`
- 修改：`tests/test_lan_service.py`
- 修改：`tests/test_lan_chat.py`

- [ ] **步骤 1：编写 pool 数据报和 TCP frame 分派失败测试**

```python
def test_service_dispatches_pool_heartbeat_without_treating_it_as_interaction(qtbot):
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安", port=0)
    received = []
    service.pool_heartbeat_received.connect(received.append)
    record = PoolMemberRecord("peer", "小林", PoolMemberState.JOINED, 1,
                              "192.168.1.20", 18487, 1)
    heartbeat = PoolHeartbeat(POOL_ID, "peer", record, "a" * 64, 1)

    service._handle_datagram(
        LanPoolPacketCodec.encode_heartbeat(heartbeat), QHostAddress("192.168.1.20"), 18487
    )

    assert received[0].message == heartbeat
```

```python
def test_tcp_stream_dispatches_pool_frame_and_keeps_chat_history_unchanged(qtbot):
    sender, receiver = _connected_services(qtbot)
    frames = []
    receiver.pool_frame_received.connect(frames.append)
    frame = LanPoolPacketCodec.encode_summary(PoolSummary("sender", (("sender", 1),)))

    assert sender.send_pool_frame("receiver", frame)
    qtbot.waitUntil(lambda: len(frames) == 1, timeout=2_000)

    assert receiver.chat_messages() == ()
```

在 `tests/test_lan_service.py` 中定义并复用：

```python
def _connected_services(qtbot):
    sender = LanInteractionService(device_id="sender", display_name="发送方", pet_name="平安", port=0)
    receiver = LanInteractionService(device_id="receiver", display_name="接收方", pet_name="橘猫", port=0)
    assert sender.start()
    assert receiver.start()
    assert sender.probe_peer("127.0.0.1", receiver.port)
    qtbot.waitUntil(
        lambda: any(peer.device_id == "receiver" for peer in sender.peers()),
        timeout=2_000,
    )
    return sender, receiver
```

测试使用 `try/finally` 调用两端 `stop()`，不得让 socket 泄漏到后续用例。

- [ ] **步骤 2：运行测试确认信号和 API 不存在**

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_service.py tests/test_lan_chat.py -q
```

预期：新增测试 FAIL，缺少 pool signals 或 `send_pool_frame()`。

- [ ] **步骤 3：增加最小传输边界**

新增不可变接收上下文：

```python
@dataclass(frozen=True, slots=True)
class ReceivedPoolMessage:
    message: object
    address: str
    source_port: int
```

`LanInteractionService` 增加：

```python
pool_heartbeat_received = Signal(object)
pool_frame_received = Signal(object)

def send_pool_heartbeat(self, packet: bytes, targets: Iterable[tuple[str, int]] = ()) -> bool:
    if not self._running or not packet or len(packet) > MAX_POOL_UDP_BYTES:
        return False
    broadcasts = eligible_broadcast_addresses(self._interface_provider())
    endpoints = {
        *((address, self._port) for address in broadcasts),
        ("255.255.255.255", self._port),
        *((str(address), int(port)) for address, port in targets),
    }
    results = [
        self._socket.writeDatagram(packet, QHostAddress(address), port) == len(packet)
        for address, port in sorted(endpoints)
    ]
    return bool(results) and all(results)

def send_pool_frame(self, target_device_id: str, frame: bytes) -> bool:
    peer = self._peers.get(target_device_id)
    if (
        not self.chat_is_available
        or peer is None
        or not peer.online
        or not peer.ip_address
        or not peer.port
        or not frame
        or len(frame) > MAX_POOL_FRAME_BYTES + 4
    ):
        return False
    self._start_frame_send(peer, frame, remember_message=None)
    return True
```

将现有 `_start_chat_send()` 提取为 `_start_frame_send(peer, frame, remember_message)`；`remember_message` 为 `LanChatMessage` 时沿用聊天历史写入，为 `None` 时只写帧并断开，不产生聊天记录。

- [ ] **步骤 4：让 TCP reader 按 `kind` 分派**

读取长度前缀后先解析 JSON envelope 的 `kind`：

- `chat` → 现有 `decode_chat_message()`；
- `pool_summary` / `pool_records` → `LanPoolPacketCodec.decode_frame()`；
- 未知 kind → 拒绝并关闭 socket。

pool frame 不进入聊天历史，不触发桌宠气泡。保持现有图片大小和聊天限流。

- [ ] **步骤 5：运行传输和聊天回归并提交**

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_service.py tests/test_lan_chat.py tests/test_codex_usage_sync.py -q
git add src/petnest/core/lan_service.py tests/test_lan_service.py tests/test_lan_chat.py
git commit -m "feat: 复用局域网传输承载名单同步"
```

### 任务 4：实现名单同步服务与端点验证队列

**文件：**
- 创建：`src/petnest/core/lan_pool_sync.py`
- 创建：`tests/test_lan_pool_sync.py`
- 修改：`src/petnest/core/lan_service.py`
- 修改：`tests/test_lan_service.py`

- [ ] **步骤 1：编写摘要差异同步失败测试**

先在 `tests/test_lan_pool_sync.py` 定义可观测的传输替身与节点 helper：

```python
class FakeLanService(QObject):
    pool_heartbeat_received = Signal(object)
    pool_frame_received = Signal(object)
    peer_changed = Signal(object)
    manual_probe_succeeded = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.heartbeats: list[bytes] = []
        self.frames: list[tuple[str, bytes]] = []
        self.probes: list[tuple[str, int]] = []
        self.transport_available = True

    def send_pool_heartbeat(self, packet: bytes, targets=()) -> bool:
        if not self.transport_available:
            return False
        self.heartbeats.append(packet)
        return True

    def send_pool_frame(self, target_device_id: str, frame: bytes) -> bool:
        if not self.transport_available:
            return False
        self.frames.append((target_device_id, frame))
        return True

    def probe_peer(self, ip_address: str, port: int = 18487) -> bool:
        if not self.transport_available:
            return False
        self.probes.append((ip_address, port))
        return True


def _sync_node(root, device_id, records=()):
    roster = PoolRosterStore(root / "roster.json", local_device_id=device_id)
    roster.merge(tuple(records), directly_verified_ids={item.device_id for item in records})
    lan = FakeLanService()
    sync = LanPoolSyncService(lan, roster, display_name=lambda: device_id)
    return SimpleNamespace(device_id=device_id, roster=roster, lan=lan, sync=sync)


def record(device_id: str, revision: int) -> PoolMemberRecord:
    return PoolMemberRecord(device_id, device_id, PoolMemberState.JOINED, revision,
                            f"192.168.1.{revision + 10}", 18487, 1)


def _deliver_pending_frames(sender, receiver):
    while sender.lan.frames:
        _target, frame = sender.lan.frames.pop(0)
        message = LanPoolPacketCodec.decode_frame(frame)
        receiver.sync.receive_frame(sender.device_id, message)
```

```python
def test_sync_exchanges_only_missing_or_older_records(qtbot, tmp_path):
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1), record("b", 2)))
    d = _sync_node(tmp_path / "d", "d", records=(record("a", 1), record("d", 1)))

    a.sync.receive_summary("d", d.sync.summary())
    d.sync.receive_summary("a", a.sync.summary())
    _deliver_pending_frames(a, d)

    assert a.roster.revisions() == d.roster.revisions() == {"a": 1, "b": 2, "d": 1}
```

- [ ] **步骤 2：编写后加入和断线补偿失败测试**

```python
def test_bridge_syncs_members_that_join_after_bridge_was_created(qtbot, tmp_path):
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1), record("d", 1)))
    d = _sync_node(tmp_path / "d", "d", records=(record("a", 1), record("d", 1)))
    a.roster.merge((record("b", 1),), directly_verified_ids={"b"})
    d.lan.transport_available = False
    a.sync.send_summary("d")
    assert "b" not in d.roster.records()

    d.lan.transport_available = True
    a.sync.send_summary("d")
    _deliver_pending_frames(a, d)
    _deliver_pending_frames(d, a)
    _deliver_pending_frames(a, d)

    assert d.roster.records()["b"].state is PoolMemberState.JOINED
```

- [ ] **步骤 3：运行测试确认同步服务不存在**

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_pool_sync.py -q
```

预期：FAIL，缺少 `LanPoolSyncService`。

- [ ] **步骤 4：实现同步服务核心**

```python
class LanPoolSyncService(QObject):
    roster_changed = Signal()
    sync_status_changed = Signal(str)

    def __init__(self, lan_service: LanInteractionService, roster: PoolRosterStore,
                 *, display_name: Callable[[], str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.lan_service = lan_service
        self.roster = roster
        self.display_name = display_name
        self._last_summary_sent: dict[str, float] = {}
        self._verification_queue: deque[tuple[str, str, int]] = deque()
        self._periodic_timer = QTimer(self)
        self._periodic_timer.setInterval(30_000)
```

连接 heartbeat/frame/peer_changed/manual_probe_succeeded 信号。Heartbeat digest 不同则向发送方发送 summary；收到 summary 后发送本机更新记录，并回发本机 summary 使对方能补齐反方向差异；收到 records 后合并、保存、更新 UI，并把未验证跨网段 endpoint 加入有界队列。

- [ ] **步骤 5：实现有界端点验证队列**

一次只调用一个 `probe_peer()`，避免现有单目标手动探测冲突。队列规则：

- 最多 256 项；
- endpoint 去重；
- 跳过本机、left、已在线 verified 和最近失败未到退避时间的记录；
- 成功后由现有 `KnownLanPeerRegistry` 保存；
- 超时后继续下一项；
- 失败使用 30 秒、2 分钟、10 分钟三级退避。

为服务增加专用自动 probe 结果信号或带上下文的 probe API，不能依赖面向 UI 的全局错误字符串判断成功失败。

- [ ] **步骤 6：实现本机加入、退出和 heartbeat**

```python
def set_local_joined(self, joined: bool, *, ip_address: str, port: int) -> PoolMemberRecord:
    state = PoolMemberState.JOINED if joined else PoolMemberState.LEFT
    record = self.roster.update_local(
        display_name=self.display_name(), state=state, ip_address=ip_address, port=port
    )
    self.broadcast_heartbeat()
    self.sync_reachable_peers()
    return record
```

启动时从现有 `lan_alert_group_joined` 设置恢复自有记录；昵称和已验证本机端点变化时只在内容真的变化时增加 revision。

- [ ] **步骤 7：运行同步、服务和协议测试并提交**

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_pool_sync.py tests/test_lan_pool_roster.py tests/test_lan_pool_protocol.py tests/test_lan_service.py -q
git add src/petnest/core/lan_pool_sync.py src/petnest/core/lan_service.py tests/test_lan_pool_sync.py tests/test_lan_service.py
git commit -m "feat: 添加无中心预警池名单同步"
```

### 任务 5：接入应用状态与成员视图

**文件：**
- 修改：`src/petnest/app.py`
- 修改：`src/petnest/ui/lan_interaction_dialog.py`
- 修改：`src/petnest/models/lan_pool.py`
- 修改：`tests/test_app_and_platforms.py`
- 修改：`tests/test_lan_interactions.py`

- [ ] **步骤 1：编写三个计数和成员状态失败测试**

```python
def test_dialog_shows_joined_online_and_sendable_counts(qtbot):
    members = (
        PoolMemberView("a", "甲", joined=True, online=True, verified=True, reachable=True),
        PoolMemberView("b", "乙", joined=True, online=True, verified=False, reachable=False),
        PoolMemberView("c", "丙", joined=True, online=False, verified=True, reachable=False),
        PoolMemberView("d", "丁", joined=False, online=False, verified=False, reachable=False),
    )
    dialog = LanInteractionDialog(settings=Settings(device_id="local"), pool_members=members)

    assert dialog.alert_joined_count_label.text() == "已加入 3 人"
    assert dialog.alert_online_count_label.text() == "在线 2 人"
    assert dialog.alert_sendable_count_label.text() == "可发送 1 人"
```

- [ ] **步骤 2：编写加入退出通过同步服务更新失败测试**

```python
def test_app_routes_join_and_leave_through_pool_sync(qtbot, petnest_app, monkeypatch):
    changed = []
    monkeypatch.setattr(
        petnest_app.lan_pool_sync,
        "set_local_joined",
        lambda joined, **kwargs: changed.append(joined),
    )

    petnest_app._set_lan_alert_group_joined(True)
    petnest_app._set_lan_alert_group_joined(False)

    assert changed == [True, False]
```

- [ ] **步骤 3：实现 `PoolMemberView` 与 UI**

```python
@dataclass(frozen=True, slots=True)
class PoolMemberView:
    device_id: str
    display_name: str
    joined: bool
    online: bool
    verified: bool
    reachable: bool
```

`LanPoolSyncService.member_views()` 把 roster 记录与 `lan_service.peers()` 合并。互动页面使用 view 渲染成员，不再用 `_alert_group_peers()` 推断总成员；left 记录不显示，未验证记录显示“待验证”，离线成员继续显示。

- [ ] **步骤 4：装配 roster 和 sync 生命周期**

在 `PetNest.__init__` 中创建：

```python
self.lan_pool_roster = PoolRosterStore(
    self.settings_manager.path.parent / "lan-alert-pool-roster.json",
    local_device_id=self.settings.device_id,
)
self.lan_pool_sync = LanPoolSyncService(
    self.lan_service,
    self.lan_pool_roster,
    display_name=lambda: display_name_for(self.settings),
    parent=self.window,
)
```

应用启动/局域网服务启用时启动 sync；关闭时先停 sync 再停 lan service。加入退出同时更新 `Settings` 兼容字段和自有 roster record。发送聊天/预警仍由 `LanInteractionService` 执行，但收件人资格由 roster joined 与实时 verified 共同决定。

- [ ] **步骤 5：运行应用和 UI 测试并提交**

```powershell
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_app_and_platforms.py tests/test_lan_interactions.py tests/test_lan_chat.py -q
git add src/petnest/app.py src/petnest/ui/lan_interaction_dialog.py src/petnest/models/lan_pool.py tests/test_app_and_platforms.py tests/test_lan_interactions.py
git commit -m "feat: 展示同步后的预警池成员状态"
```

### 任务 6：验证跨网段后加入、分区合并与兼容性

**文件：**
- 修改：`tests/test_lan_pool_sync.py`
- 修改：`tests/test_lan_service.py`
- 修改：`tests/test_lan_chat.py`
- 修改：`README.md`

- [ ] **步骤 1：增加 A/D 先桥接、B/E 后加入集成测试**

在 `tests/test_lan_pool_sync.py` 复用任务 4 的 `_sync_node()`，并定义：

```python
def _four_pool_nodes(tmp_path):
    return tuple(_sync_node(tmp_path / device_id, device_id, records=(record(device_id, 1),))
                 for device_id in ("a", "b", "d", "e"))


def _exchange(left, right):
    left.sync.send_summary(right.device_id)
    right.sync.send_summary(left.device_id)
    for _round in range(3):
        _deliver_pending_frames(left, right)
        _deliver_pending_frames(right, left)


def _join_locally(node, through):
    own = node.roster.records()[node.device_id]
    through.sync.receive_records(node.device_id, PoolRecords(node.device_id, (own,)))
    node.sync.receive_records(through.device_id, PoolRecords(
        through.device_id, tuple(through.roster.records().values())
    ))
```

```python
def test_members_joining_after_bridge_are_eventually_visible_everywhere(qtbot, tmp_path):
    a, b, d, e = _four_pool_nodes(tmp_path)
    _exchange(a, d)
    _join_locally(b, through=a)
    _join_locally(e, through=d)
    _exchange(a, d)
    _exchange(a, b)
    _exchange(d, e)

    assert all(set(node.roster.joined_device_ids()) == {"a", "b", "d", "e"}
               for node in (a, b, d, e))
```

- [ ] **步骤 2：增加离线补偿、并发加入和退出 tombstone 测试**

覆盖：

- D 离线时 B 经 A 加入，D 恢复后补收；
- 101 侧新增 B、106 侧新增 E，恢复桥接后取并集；
- A revision 3 left 覆盖任意旧 joined；
- 相同 revision 冲突直到 A 直接上线；
- 未验证第三方 endpoint 不进入预警收件人；
- 旧客户端忽略 pool 消息并保持普通群聊。

- [ ] **步骤 3：增加资源边界测试**

验证 256 人可同步，257 人拒绝；单一来源超频 heartbeat/summary 被限流；超大 TCP frame 关闭连接但不影响后续合法聊天。

- [ ] **步骤 4：更新 README**

写明：固定开放池、所有设备平等持有名单、一次跨网段桥接后持续同步、成员后加入可补偿、已加入/在线/可发送三个数字，以及“两个从未桥接的广播域仍需一个入口”的边界。

- [ ] **步骤 5：运行专项和全量测试**

```powershell
$env:PYTHONPATH='src'
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest tests/test_lan_pool_roster.py tests/test_lan_pool_protocol.py tests/test_lan_pool_sync.py tests/test_lan_service.py tests/test_lan_chat.py tests/test_lan_interactions.py -q
& 'F:\Desktop Projects\PetNest\.venv\Scripts\python.exe' -m pytest -q
```

预期：专项 0 failures；全量不低于基线 `816 passed, 4 skipped`，新增测试使通过数上升。

- [ ] **步骤 6：运行差异检查并提交**

```powershell
git diff --check
git status --short
git add README.md tests/test_lan_pool_sync.py tests/test_lan_service.py tests/test_lan_chat.py
git commit -m "test: 验证跨网段预警池名单最终同步"
```

- [ ] **步骤 7：完成前验证**

重新运行步骤 5 的专项和全量命令，记录准确通过数、跳过数、分支和工作树状态。只有新鲜输出为 0 failures 时才能宣布完成。

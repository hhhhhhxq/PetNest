# 局域网幽灵用户修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 阻止应用级测试广播虚假局域网身份，并安全清理附近设备和预警组名单中占用同一网络端点的重复临时身份。

**架构：** 测试环境通过显式开关跳过 `PetNest` 的 LAN 自动启动，底层服务仍能独立测试。运行时以 `(IP, advertised_port)` 为端点，仅替换同端点的未保存临时身份；本机预警组记录更新时原子删除与本机端点完全相同的外来记录。

**技术栈：** Python 3.12、PySide6、pytest、pytest-qt、JSON 原子存储

---

## 文件结构

- `tests/conftest.py`：应用级测试默认开启 LAN 隔离。
- `tests/test_app_and_platforms.py`、`src/petnest/app.py`：验证并实现应用自动启动边界。
- `tests/test_lan_service.py`、`src/petnest/core/lan_service.py`：验证并实现附近设备端点唯一性。
- `tests/test_lan_pool_roster.py`、`src/petnest/core/lan_pool_roster.py`：验证并实现本机端点冲突的原子清理。

### 任务 1：隔离应用级测试的真实 LAN 广播

**文件：**
- 修改：`tests/test_app_and_platforms.py:2970`
- 修改：`tests/conftest.py:11`
- 修改：`src/petnest/app.py:2239`

- [ ] **步骤 1：编写失败测试**

```python
def test_test_network_isolation_skips_app_lan_services(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("PETNEST_TEST_DISABLE_LAN", "1")
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    started = []
    monkeypatch.setattr(application.lan_service, "start", lambda: started.append("lan") or True)
    monkeypatch.setattr(application.lan_pool_sync, "start", lambda: started.append("pool"))
    application._configure_lan_service()
    assert started == []
    application.shutdown()
```

- [ ] **步骤 2：验证红灯**

运行：`python -m pytest tests/test_app_and_platforms.py::test_test_network_isolation_skips_app_lan_services -q`

预期：FAIL，`started` 包含 `lan` 和 `pool`。

- [ ] **步骤 3：最少实现**

在 `_configure_lan_service()` 开头添加：

```python
if os.environ.get("PETNEST_TEST_DISABLE_LAN", "").strip() == "1":
    self.lan_pool_sync.stop()
    self.lan_service.stop()
    return
```

在 `tests/conftest.py` 添加：

```python
os.environ.setdefault("PETNEST_TEST_DISABLE_LAN", "1")
```

给既有 `test_lan_service_follows_the_user_presence_toggle` 注入 `monkeypatch`，执行：

```python
monkeypatch.delenv("PETNEST_TEST_DISABLE_LAN", raising=False)
monkeypatch.setattr(application.lan_service, "discover", lambda: None)
```

这样该用例仍验证真实服务生命周期，但不发送广播。

- [ ] **步骤 4：验证绿灯**

运行：`python -m pytest tests/test_app_and_platforms.py::test_test_network_isolation_skips_app_lan_services tests/test_app_and_platforms.py::test_lan_service_follows_the_user_presence_toggle -q`

预期：2 passed。

- [ ] **步骤 5：提交**

```bash
git add tests/conftest.py tests/test_app_and_platforms.py src/petnest/app.py
git commit -m "test: isolate app LAN services"
```

### 任务 2：附近设备按完整端点去重

**文件：**
- 修改：`tests/test_lan_service.py`
- 修改：`src/petnest/core/lan_service.py:933`

- [ ] **步骤 1：编写同端点失败测试**

先在测试文件导入 `pytest`，供参数化边界测试使用：

```python
import pytest
```

```python
def test_same_endpoint_replaces_an_older_unsaved_identity(qtbot):
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安")
    removed = []
    service.peer_removed.connect(removed.append)
    for device_id in ("ghost-a", "ghost-b"):
        packet = LanPacketCodec.hello(
            device_id=device_id, display_name=device_id, pet_name="猫", port=18487
        )
        service._handle_datagram(
            LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 18487
        )
    assert [peer.device_id for peer in service.peers()] == ["ghost-b"]
    assert removed == ["ghost-a"]
    assert "ghost-a" not in service._peer_seen_at
```

- [ ] **步骤 2：编写边界测试**

```python
@pytest.mark.parametrize(
    ("second_ip", "second_port"),
    (("192.168.1.21", 18487), ("192.168.1.20", 18488)),
)
def test_different_endpoints_keep_both_unsaved_identities(qtbot, second_ip, second_port):
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安")
    first = LanPacketCodec.hello(device_id="peer-a", display_name="甲", pet_name="猫", port=18487)
    second = LanPacketCodec.hello(device_id="peer-b", display_name="乙", pet_name="猫", port=second_port)
    service._handle_datagram(LanPacketCodec.encode(first), QHostAddress("192.168.1.20"), 18487)
    service._handle_datagram(LanPacketCodec.encode(second), QHostAddress(second_ip), second_port)
    assert {peer.device_id for peer in service.peers()} == {"peer-a", "peer-b"}
```

- [ ] **步骤 3：验证红灯与既有边界**

运行：`python -m pytest tests/test_lan_service.py::test_same_endpoint_replaces_an_older_unsaved_identity tests/test_lan_service.py::test_different_endpoints_keep_both_unsaved_identities -q`

预期：同端点测试 FAIL；两个不同端点参数用例 PASS。

- [ ] **步骤 4：最少实现**

在 `_handle_presence()` 中复用一次 `known_peers = self._known_peers()`，构建新 peer 前删除同 IP、同声明端口、不同设备 ID 且不在 `known_peers` 中的运行时身份：

```python
duplicate_ids = tuple(
    peer_id
    for peer_id, existing_peer in self._peers.items()
    if peer_id != device_id
    and peer_id not in known_peers
    and existing_peer.ip_address == host
    and existing_peer.port == port
)
for duplicate_id in duplicate_ids:
    self._peers.pop(duplicate_id, None)
    self._peer_seen_at.pop(duplicate_id, None)
    self._interaction_times.pop(duplicate_id, None)
    self._usage_sync_times.pop(duplicate_id, None)
    self.peer_removed.emit(duplicate_id)
```

已保存伙伴仍由 `_reject_unexpected_probe_identity()` 保护，不允许静默覆盖。

- [ ] **步骤 5：验证 LAN 服务并提交**

运行：`python -m pytest tests/test_lan_service.py -q`

预期：全部通过。

```bash
git add tests/test_lan_service.py src/petnest/core/lan_service.py
git commit -m "fix: deduplicate LAN peers by endpoint"
```

### 任务 3：原子清理预警组中的本机幽灵身份

**文件：**
- 修改：`tests/test_lan_pool_roster.py`
- 修改：`src/petnest/core/lan_pool_roster.py:92`

- [ ] **步骤 1：编写同端点清理失败测试**

既有 `_record()` 已接受 `ip_address` 和 `port` 关键字参数，直接添加：

```python
def test_update_local_removes_foreign_records_at_the_same_endpoint(tmp_path):
    path = tmp_path / "roster.json"
    store = PoolRosterStore(path, local_device_id="local")
    store.merge((
        _record("ghost-a", ip_address="192.168.1.10", port=18487),
        _record("ghost-b", ip_address="192.168.1.10", port=18487),
        _record("other-ip", ip_address="192.168.1.11", port=18487),
        _record("other-port", ip_address="192.168.1.10", port=18488),
    ))
    store.update_local(
        display_name="本机", state=PoolMemberState.JOINED,
        ip_address="192.168.1.10", port=18487,
    )
    assert set(store.records()) == {"local", "other-ip", "other-port"}
    assert set(PoolRosterStore(path, local_device_id="local").records()) == {
        "local", "other-ip", "other-port"
    }
```

- [ ] **步骤 2：覆盖本机内容未变化的边界**

```python
def test_unchanged_local_record_still_cleans_a_later_endpoint_conflict(tmp_path):
    store = PoolRosterStore(tmp_path / "roster.json", local_device_id="local")
    local = store.update_local(
        display_name="本机", state=PoolMemberState.JOINED,
        ip_address="192.168.1.10", port=18487,
    )
    store.merge((_record("ghost", ip_address="192.168.1.10", port=18487),))
    same = store.update_local(
        display_name="本机", state=PoolMemberState.JOINED,
        ip_address="192.168.1.10", port=18487,
    )
    assert same.revision == local.revision
    assert set(store.records()) == {"local"}
```

- [ ] **步骤 3：验证红灯**

运行：`python -m pytest tests/test_lan_pool_roster.py::test_update_local_removes_foreign_records_at_the_same_endpoint tests/test_lan_pool_roster.py::test_unchanged_local_record_still_cleans_a_later_endpoint_conflict -q`

预期：两个测试都 FAIL。

- [ ] **步骤 4：最少实现**

在 `update_local()` 归一化状态后删除所有设备 ID 非本机、IP 和端口均与参数相同的记录。若本机内容未变化但发生清理，则 `_save()` 一次后返回原记录；若本机记录变化，沿用现有 revision 规则并只 `_save()` 一次。

```python
conflicting_ids = tuple(
    device_id
    for device_id, record in self._records.items()
    if device_id != self.local_device_id
    and record.ip_address == ip_address
    and record.port == port
)
for device_id in conflicting_ids:
    del self._records[device_id]
```

- [ ] **步骤 5：验证名单测试并提交**

运行：`python -m pytest tests/test_lan_pool_roster.py -q`

预期：全部通过，revision、损坏文件隔离和容量限制行为不变。

```bash
git add tests/test_lan_pool_roster.py src/petnest/core/lan_pool_roster.py
git commit -m "fix: clean local endpoint ghosts from LAN roster"
```

### 任务 4：完整验证

**文件：**
- 验证：上述源码、测试和计划文档

- [ ] **步骤 1：运行定向回归**

运行：`python -m pytest tests/test_lan_protocol.py tests/test_lan_service.py tests/test_lan_pool_roster.py tests/test_lan_pool_sync.py tests/test_lan_interactions.py tests/test_app_and_platforms.py -q`

预期：0 failed；Windows 无符号链接权限的既有用例允许 1 skip。

- [ ] **步骤 2：运行完整测试**

运行：`python -m pytest -q`

预期：0 failed；平台能力相关既有 skip 保持不变，且应用级测试不再向真实局域网广播随机设备 ID。

- [ ] **步骤 3：运行静态验证**

```bash
python -m compileall -q src/petnest
git diff --check
```

预期：两个命令退出码均为 0。

- [ ] **步骤 4：检查提交范围**

```bash
git status --short
git log --oneline --decorate -5
```

预期：工作区干净；提交只包含本计划列出的源码、测试和计划文档。

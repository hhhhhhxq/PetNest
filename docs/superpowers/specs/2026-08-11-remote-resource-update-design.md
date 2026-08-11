# PetNest 远程资源更新设计

## 目标

让 PetNest 在不更新安装包的情况下发现并使用私有 GitHub 资源仓库中的光标、互动动效和倒计时背景，同时保证启动不被网络阻塞、更新失败不破坏现有资源。

## 更新触发

客户端保存资源状态，不把资源状态混入用户偏好设置：

- 启动后提交一次后台检查任务；只有距离 `last_check_at` 至少 24 小时，或本地没有成功检查记录时，才请求 Worker manifest。
- 程序运行期间由 30 分钟 QTimer 触发同一个“是否到期”判断，因此不会重复请求。
- 托盘菜单的“立即检查资源更新”绕过 24 小时限制，立即请求 manifest。
- 检查只读取并校验 manifest，不在启动线程下载 800 多个动效帧。

发现远程 catalog 或文件 SHA-256 与当前应用版本不同时，持久化 `update_available=true`，托盘菜单动作显示蓝点。手动更新动作才下载资源；下载完成后提示“资源已更新，下次启动生效”，并清除蓝点。

## 缓存与原子切换

缓存目录位于用户可写目录 `%APPDATA%/PetNest/remote-resources`（其他平台使用对应应用数据目录）：

```text
remote-resources/
├─ versions/<catalog>-<digest>/resources/...
├─ current.json
├─ state.json
└─ staging/<run-id>/...
```

下载流程先创建 staging 目录，逐文件下载并核对 manifest 记录的大小和 SHA-256。所有文件验证成功后，将 staging 变成不可变版本目录，再用临时文件原子替换 `current.json` 指针。程序读取资源时只从 current 指向的版本目录读取，因此不会出现半套资源。保留当前版本和上一版本用于回退，后续仅清理更老版本。

当当前正在使用光标主题或正在播放某个资源时，不修改其已打开的路径；新版本在下一次启动或用户重新打开对应设置时生效。未使用资源也不直接覆盖旧版本，而是随新版本目录一起切换，以保持 manifest、光标、动效和背景的一致性。

## 应用集成

- `RemoteResourceCache` 提供 manifest 获取、版本化下载、校验、回退和安全路径解析。
- `RemoteResourceUpdateCoordinator` 管理检查节流、状态文件、蓝点状态和手动应用更新。
- 应用启动后创建协调器并提交后台任务；网络异常只记录日志并继续使用 current 或安装包内置资源。
- `CursorStyleCatalog` 优先扫描 current 版本的 `resources/cursors`，没有有效 current 时回退 `assets/cursors`。
- 倒计时背景和互动动效通过同一个 current 版本根目录解析；本次不改变它们已有的播放逻辑。
- 托盘增加“立即检查资源更新”动作，使用 `●` 前缀表示蓝点，不改变现有菜单动作接口。

## 错误处理

- Worker、JSON、路径、文件大小或 SHA-256 任一校验失败：删除本次 staging，保留旧 current。
- 没有历史缓存：使用安装包资源，蓝点保持为未确认状态并允许重试。
- 手动下载失败：不清除 `update_available`，托盘提示失败原因。
- 状态文件损坏：丢弃状态并按首次启动处理，不影响用户设置文件。

## 验证标准

- 单元测试覆盖 24 小时节流、手动绕过、蓝点持久化、完整 staging 失败回退和版本指针原子切换。
- 现有项目测试全部通过。
- 使用线上 Worker manifest 验证至少一个光标、一个动效和一个倒计时背景的大小与 SHA-256。

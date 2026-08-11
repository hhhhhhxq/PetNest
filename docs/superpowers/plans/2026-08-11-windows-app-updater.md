# Windows 应用自动更新计划

## 目标

为 PetNest 增加安全的 Windows 应用版本检查、下载和安装流程。更新包存放在公开的 PetNest 主项目 GitHub Releases 中；用户从设置页的“检查程序更新…”入口触发检查，也支持启动后的后台检查。macOS 保持现有行为，并通过跨平台接口为之后接入 Sparkle 等方案预留位置。

## 约束与边界

- 资源更新入口与应用安装包更新入口完全分开，避免用户混淆。
- 客户端只接受 HTTPS、GitHub Releases 允许域名、严格版本号、预期大小和 SHA-256 正确的安装包。
- 新版本不得低于或等于当前版本；下载写入用户可写临时目录，校验成功后才原子替换。
- 安装由独立的 Windows updater 进程完成：等待主程序退出，再启动 Inno Setup 安装器；主程序文件不在运行中直接覆盖。
- 检查、下载、校验均在后台线程；网络失败、空间不足、权限不足、进程退出和重复点击都应可恢复，不影响当前版本运行。
- 非 Windows 平台返回“暂不支持”，不导入或启动 Windows updater；macOS 构建脚本保持兼容。

## 发布元数据

每个公开 GitHub Release 上传：

1. `PetNest-Setup-<version>.exe`
2. `app-update.json`

元数据包含 `schema_version`、`version`、`platform`、`asset.url`、`asset.size`、`asset.sha256` 和可选 `release_notes`。安装器与元数据版本必须一致；后续可增加签名字段而不破坏现有解析器。

## 实施步骤

1. 先为元数据解析、版本比较、URL 白名单、大小上限、流式 SHA-256、临时文件清理和 updater 命令构造编写失败测试。
2. 实现平台无关的 `AppUpdateClient`/结果模型及 Windows 下载实现；实现 Windows updater 命令行入口和父进程等待。
3. 在设置对话框添加仅 Windows 显示的“检查程序更新…”按钮；增加后台检查、进度、取消/稍后、下载完成后启动 updater 的 UI 状态机。
4. 更新 Windows 构建脚本与 Inno Setup，将 updater 一并打包；不修改 macOS 构建输出。
5. 运行全量测试、Node/脚本语法检查、构建配置检查，并补充发布和回滚说明。


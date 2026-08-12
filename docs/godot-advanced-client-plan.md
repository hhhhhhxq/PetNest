# PetNest Godot 高级客户端实施计划

## 产品定位

PetNest 保留两个可独立运行、共享数据格式的客户端：

- **PetNest 标准版**：现有 Python 3.12 + PySide6 客户端，强调兼容性与成熟工具链。
- **PetNest 高级版**：Godot 4.7 + GDScript 客户端，覆盖标准版核心体验，并增加 GPU 高刷新率、自动行走、程序化跳跃和桌面活动区域。

两个客户端共享：

- `pet.json` 宠物包格式；
- 用户宠物库；
- Windows `%APPDATA%\PetNest\settings.json` / macOS `~/Library/Application Support/PetNest/settings.json` 中的通用设置；
- `127.0.0.1` 本机 JSON 事件协议。
- UDP `18487` 局域网发现与互动协议；
- `effect.json` + PNG 帧本地特效格式。

同一时间只运行一个客户端。Godot 专用设置使用 `godot_` 前缀，避免破坏标准版设置。

## 阶段与验收标准

### 阶段 1：高级客户端可运行基础

- [x] 独立 Godot 工程与 Windows 导出预设。
- [x] 扫描宠物库、校验并读取 PetNest `pet.json`。
- [x] 从外部目录加载 RGBA PNG 动画帧。
- [x] 透明、无边框、置顶窗口与按透明度生成的鼠标穿透轮廓。
- [x] 动画逐帧时长、循环、`next`、优先级和 fallback。
- [x] 多宠物切换、重新加载、暂停、缩放和位置保存。

### 阶段 2：Godot 高级能力

- [x] Godot 高刷新率调度与 60 FPS 省电模式（Windows 使用 `UpdateLayeredWindow` 逐像素 Alpha 显示器，保留半透明边缘并避开透明交换链驱动问题）。
- [x] 自动行走、转向和边界约束。
- [x] 程序化跳跃。
- [x] 鼠标跟随。
- [x] 系统空闲的 bored、sleep、wake 状态（Windows 原生显示桥通过 `GetLastInputInfo` 同时检测全局鼠标和键盘，不记录输入内容）。
- [x] 工作日下班倒计时。

### 阶段 3：独立客户端能力

- [x] 系统托盘与右键动作菜单。
- [x] 本机 TCP 外部事件接口。
- [x] Windows 开机启动与 macOS LaunchAgent 登录启动。
- [x] 单实例保护。
- [x] Godot 日志、端口占用和无效宠物包安全降级。

### 阶段 4：发行集成

- [x] Godot 一键构建脚本与渲染/协议烟雾测试。
- [x] Inno Setup 可选高级版组件。
- [x] 标准版、高级版独立快捷方式。
- [x] Godot 缺失时不影响标准版构建和安装。

### 阶段 5：v0.1.2 跨客户端互动

- [x] 与 PySide6 兼容的 UDP 广播、定向发现和 `hello_ack`。
- [x] 招呼、爱心、文字和特效 ID 的发送、接收与输入校验。
- [x] 设备过期、单设备限流、8 KiB 数据包限制。
- [x] Godot 原生附近设备、手动 IP、文字和特效互动窗口。
- [x] 加载用户目录、安装目录及标准版远程缓存中的特效包。
- [x] PNG 特效按 `layer` 在宠物上下层播放，并显示互动气泡。

### 后续完整功能对齐

- [x] Godot 原生设置窗口。
- [x] 精灵图导入界面与自动跳过透明帧（8×9 / 8×11）。
- [x] 精灵图导入手动选帧模式。
- [x] 原生逐帧动画时长编辑器与实时预览。
- [x] Windows `GetLastInputInfo` 原生桥，补齐全局键盘空闲检测。
- [x] Windows 系统光标主题原生桥与退出恢复。
- [x] 程序更新与远程资源更新入口（复用标准版校验、缓存及安装器更新核心）。
- [x] 与 Python 测试夹具共享的跨客户端一致性测试。

### 阶段 6：macOS 高级版

- [x] Godot macOS universal 导出预设与 `.app` / ZIP 构建脚本。
- [x] 全可用桌面透明窗口、宠物轮廓点击穿透和纵向移动空间。
- [x] `IOHIDSystem/HIDIdleTime` 全局键盘与鼠标空闲检测；不读取按键内容。
- [x] 与标准版共享 Application Support 设置、宠物库和远程资源缓存。
- [x] 中性 `sample_pet` 首次启动种子；本地导入素材不进入默认安装。
- [x] 登录启动、程序发行页和远程资源维护入口。
- [x] 复用同一发行包中标准维护组件的 macOS 系统光标应用与退出恢复。
- [ ] 在签名并公证的 Apple Silicon / Intel 产物上完成透明、穿透、托盘、辅助进程和系统升级回归。

## 目录约定

```text
clients/godot/
├─ project.godot
├─ export_presets.cfg
├─ src/
├─ tests/
├─ build-windows.ps1
└─ build-macos.sh
```

Windows 导出目标为 `dist/PetNestGodot/PetNestGodot.exe`，macOS 导出目标为 `dist/PetNest Advanced.app`。构建脚本会复制内置 `effects`、光标主题和中性 `sample_pet` 种子；用户宠物仍由两个客户端共享。本地导入和生成的宠物素材不进入任何版本的默认安装内容。

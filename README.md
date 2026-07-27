# PetNest

PetNest 是一个基于 Python 3.12+ 与 PySide6 的跨平台轻量桌面宠物播放器。它播放由 `pet.json` 配置的透明 PNG 序列帧，不绑定特定角色、AI 工具或素材风格。

目前以 Windows 10/11 为主要目标；macOS 保留相同的核心与窗口接口，但尚未在 Windows 以外平台实际验证。Linux 会安全降级，便于后续扩展。

## 当前功能与边界

- 透明、无边框、置顶桌宠；支持缩放、悬停、点击、拖动、释放及位置保存。
- 宠物包自动校验、扫描、切换与重新加载；随项目提供 Pillow 生成的 `sample_pet`。
- 系统托盘提供显示/隐藏、暂停、切换宠物、重新加载、设置和退出。
- 本机 TCP 事件接口只监听 `127.0.0.1`，支持 `agent.working`、`agent.success` 等通用事件。
- 第一阶段不实现自动行走、重力、多宠物、在线商店、账户或云同步。
- 已实现应用内部的透明 alpha 命中判断；**系统级按像素点击穿透尚未实现**，不要将它视作安全或无干扰的输入方案。
- macOS 系统空闲、会话事件与登录启动项目前是安全 fallback；macOS 未在 Windows 环境验证，正式发布前仍需在 macOS 实机测试。

## 环境与安装

需要 Python 3.12+。无需 Qt Creator、完整 Qt SDK、Node.js 或 C++ 编译器。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
pip install -e .
python -m petnest
```

也可以双击或在命令行运行：

```powershell
.\run.bat
```

macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
pip install -e .
python -m petnest
```

```bash
chmod +x run.sh build_macos.sh
./run.sh
```

安装完整性检查不创建 GUI：

```bash
python -m petnest --check
```

## 测试与开发工具

```bash
python -m pytest -q
python -m compileall src tools
python tools/validate_pet.py pets/sample_pet
python tools/create_sample_pet.py pets/sample_pet
python tools/preview_animation.py pets/sample_pet idle
python tools/normalize_frames.py input_frames output_frames --width 256 --height 256 --align bottom --dry-run
```

`normalize_frames.py` 默认输出到新目录并连续编号，保留透明背景，不覆盖源帧。`preview_animation.py` 仅打开动作预览窗口，不启动完整桌宠。

## 宠物包

一个目录式宠物包至少需要 `pet.json` 和 `animations/idle/*.png`。所有帧必须是同一尺寸的 RGBA PNG；路径必须位于宠物包目录内，不能使用 `../` 逃逸。

```text
pets/my_pet/
├─ pet.json
├─ preview.png
└─ animations/
   ├─ idle/001.png
   └─ wave/001.png
```

`pet.json` 的关键字段如下：

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 当前必须为 `1`。 |
| `id`、`name`、`version` | 宠物包身份信息。 |
| `canvas.width`、`canvas.height` | 所有帧统一画布大小。 |
| `display` | 默认/最小/最大缩放和 alpha 命中阈值。 |
| `animations` | 动作名到 `path`、`fps`、`loop`、`next`、`priority`、`interruptible` 的映射。 |
| `bindings` | 事件到动作的映射，例如 `mouse.click` → `click`。 |
| `fallbacks` | 动作缺失时按顺序尝试的替代动作，不能形成循环。 |

新增动作只需把 PNG 帧放在新目录，并在 `animations` 中增加定义；如要由事件触发，再在 `bindings` 中增加映射。替换图片后使用托盘中的“重新加载当前宠物”，或重启应用。将验证通过的包放入 `pets/` 后即可在托盘“切换宠物”菜单选择。

可从示例开始：

```bash
python tools/create_sample_pet.py pets/my_pet
python tools/validate_pet.py pets/my_pet
```

## 外部事件

在设置中启用外部事件接口（默认端口 `18486`）后，任何本机工具都可发送一行 JSON。服务只绑定 `127.0.0.1`，不接收局域网连接；请求大小、字段与速率均受限，端口占用不会使桌宠崩溃。

```powershell
python tools/emit_event.py agent.working --source codex
python tools/emit_event.py agent.success --source build
python tools/emit_event.py agent.error --source script
```

消息格式：

```json
{"event":"agent.working","source":"codex","payload":{"task":"build"}}
```

`payload` 不会被 PetNest 默认显示或写入日志；建议只传递非敏感状态信息。

## 打包

第一阶段使用 PyInstaller `--onedir` 并带入 `pets/` 资源。Windows 必须在 Windows 上构建，macOS 必须在 macOS 上构建；PyInstaller 不支持可靠的跨平台交叉打包。

```powershell
.\build_windows.bat
```

```bash
./build_macos.sh
```

macOS 正式分发还需要签名和公证；本项目第一阶段产物不保证已签名。

## 隐私与日志

PetNest 只在用户配置目录保存宠物 ID、窗口位置和显示偏好；日志写入用户日志目录并轮转。不会记录键盘内容、文件内容、窗口标题、完整命令、Agent 对话或外部事件 payload。外部服务仅在用户启用时启动。

## 许可证

本项目采用 [MIT License](LICENSE)。

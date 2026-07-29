# PetNest

PetNest 是一个基于 Python 3.12+ 与 PySide6 的跨平台轻量桌面宠物播放器。它播放由 `pet.json` 配置的透明 PNG 序列帧，不绑定特定角色、AI 工具或素材风格。

目前以 Windows 10/11 为主要目标；macOS 保留相同的核心与窗口接口，但尚未在 Windows 以外平台实际验证。Linux 会安全降级，便于后续扩展。

## 当前功能与边界

- 透明、无边框、置顶桌宠；支持缩放、悬停、点击、拖动、释放及位置保存。
- 宠物包自动校验、扫描、切换与重新加载；随项目提供 Pillow 生成的 `sample_pet`。
- 系统托盘提供显示/隐藏、暂停、切换宠物、导入精灵图、逐动作时长编辑、重新加载、设置和退出。
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
python tools/import_spritesheet.py path/to/spritesheet.png --pet-id my_codex_pet
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
| `animations` | 动作名到 `path`、`fps`、`loop`、`next`、`priority`、`interruptible` 的映射；可选 `frame_durations_ms`（每帧毫秒数）和 `speed_multiplier`。 |
| `bindings` | 事件到动作的映射，例如 `mouse.click` → `click`。 |
| `fallbacks` | 动作缺失时按顺序尝试的替代动作，不能形成循环。 |

新增动作只需把 PNG 帧放在新目录，并在 `animations` 中增加定义；如要由事件触发，再在 `bindings` 中增加映射。替换图片后使用托盘中的“重新加载当前宠物”，或重启应用。将验证通过的包放入 `pets/` 后即可在托盘“切换宠物”菜单选择。

可从示例开始：

```bash
python tools/create_sample_pet.py pets/my_pet
python tools/validate_pet.py pets/my_pet
```

## 导入 Codex 精灵图

PetNest 的运行时始终读取 PNG 序列帧。为了方便使用现有素材，导入器会把一张 Codex 标准精灵图自动裁成独立 PNG 帧，再生成普通 PetNest 宠物包；运行时不会依赖 Codex 格式。

### 支持规则

- 只读取本机通过文件选择器或命令行指定的 PNG，不会上传、联网或复制到包目录以外的位置。
- 输入必须是原始透明 PNG，尺寸固定为 `1536 × 1872`，即 `8` 列 × `9` 行、每格 `192 × 208` 像素。
- 输入必须具有 alpha 通道。不要使用聊天截图、拼贴图、缩放后的图片或 JPG。
- 导入默认不覆盖同 ID 的已有宠物包；请改用新 ID，或先手动备份并移除旧包。

这是 Codex `8 × 9` 标准图集的行到 PetNest 动作的默认映射。PetNest 会保留已选格位的默认逐帧时长；普通 PNG 序列帧宠物包不限制某一动作只能使用 6 或 8 帧。受这张固定图集的 8 列限制，单次导入的一行最多选择 8 格；需要更多帧时，可直接向动作目录添加 PNG 序列帧。对标准时长表范围外的手动格位，导入器会按该动作的 FPS 生成默认时长。导入后可直接编辑生成包的 `pet.json` 调整绑定、FPS、优先级或 fallback。

| 图集行 | 原动作 | 导入后的 PetNest 动作 | 说明 |
| --- | --- | --- | --- |
| 0 | idle | `idle` | 默认循环动画。 |
| 1 | running-right | `drag` | 拖动期间循环播放。 |
| 2 | running-left | `codex_running_left` | 保留为自定义动作，不默认绑定。 |
| 3 | waving | `click` | 单击时播放一次。 |
| 4 | jumping | `drop` | 释放拖动时播放一次。 |
| 5 | failed | `error` | 外部错误时播放一次。 |
| 6 | waiting | `waiting` | 等待状态循环。 |
| 7 | running | `working` | 工作状态循环。 |
| 8 | review | `hover` | 悬停状态循环。 |

标准 `8 × 9` 图集没有 `success` 行；生成的包会将 `agent.success` 安全 fallback 到 `idle`。

### 从桌面界面导入

在系统托盘中右键 PetNest 图标，选择「导入精灵图…」。对话框会先显示上面的本地文件、尺寸和默认映射规则。选择 PNG、填写小写宠物 ID（例如 `codex_cat`）后，选择一种导入方式：

- **自动跳过无内容帧**（默认）：扫描每个格位的 alpha 像素，按从左到右的顺序导入所有非空格位；不会修改原图。
- **手动选择所需帧**：选择左侧动作后显示该行缩略图；有内容的格位会预选，也可以手动保留透明格位作为停顿帧。

点击「导入」后成功时会创建：

```text
pets/codex_cat/
├─ pet.json
├─ preview.png
└─ animations/
   ├─ idle/001.png ... （数量由选择的格位决定）
   ├─ drag/001.png ... （数量由选择的格位决定）
   └─ ...
```

PetNest 会重新扫描并自动切换到这个宠物。

### 调整动作时长

在系统托盘中选择「编辑动画时长…」。列表会说明每个动作在什么时机展示、帧数、当前播放方式和实际总时长。选择一个动作后，再明确选择一种互斥方式：

- **按总时长播放**：输入目标总时长（毫秒）；数值越小，播放越快，原有帧间节奏保持不变。
- **手动编辑每帧时长**：逐帧填写毫秒数；此模式会忽略总时长缩放，表格合计即为实际总时长。

保存后 PetNest 会自动重载当前宠物，并通过托盘提示已应用的动作、方式和时长；不需要手动点击「重新加载当前宠物」。时长设置会写入当前宠物包的 `pet.json`，因此连同整个宠物文件夹一起分享时会保留；不会修改 PNG 资源。

### 命令行导入

适合批处理或不启动桌宠时使用：

```powershell
python tools/import_spritesheet.py "C:\\assets\\codex-cat.png" --pet-id codex_cat --name "Codex Cat"
python tools/validate_pet.py pets/codex_cat
```

也可以用 `--pets-root` 指定其他宠物目录。宠物 ID 必须以小写字母开头，后续只允许小写字母、数字、`-` 或 `_`。

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

## 系统空闲动作

在「设置」中启用「系统空闲动作」后，PetNest 每秒通过系统接口读取最后一次鼠标或键盘输入的时间差；它不会记录按键、鼠标位置或任何输入内容。默认规则是：30 秒无操作触发 `bored`，3 分钟无操作触发 `sleep`，恢复系统输入触发一次 `wake`。

宠物包可在 `animations` 中提供 `bored`、`sleep`、`wake` 动作；缺少其中任何资源时会安全回退到 `idle`。该功能在 Windows 使用全系统空闲时间，不限于宠物窗口；其他平台暂不支持时不会影响桌宠正常运行。

## 打包

Windows 使用 PyInstaller `--onedir` 生成应用目录，再用 Inno Setup 生成 `PetNest-Setup.exe`。构建机需要先安装 Inno Setup 6；Windows 必须在 Windows 上构建，macOS 必须在 macOS 上构建；PyInstaller 不支持可靠的跨平台交叉打包。

```powershell
.\build_windows.bat
```

完成后安装包位于 `dist\installer\PetNest-Setup.exe`。安装向导可选择程序安装目录，并提供“将宠物库保存到自定义位置”的可选高级项；默认宠物库位于 `%LOCALAPPDATA%\PetNest\pets`。

```bash
./build_macos.sh
```

macOS 正式分发还需要签名和公证；本项目第一阶段产物不保证已签名。

## 隐私与日志

PetNest 只在用户配置目录保存宠物 ID、窗口位置和显示偏好；日志写入用户日志目录并轮转。不会记录键盘内容、文件内容、窗口标题、完整命令、Agent 对话或外部事件 payload。外部服务仅在用户启用时启动。

## 许可证

本项目采用 [MIT License](LICENSE)。

# PetNest

PetNest 是一个播放 `pet.json` 透明 PNG 序列帧的桌面宠物项目，不绑定特定角色、AI 工具或素材风格。仓库同时提供 PySide6 标准客户端和 Godot 4.7 高级客户端。

目前以 Windows 10/11 为主要目标；macOS 支持 PySide6 标准版，并已补齐 Godot 高级版的通用 `.app` 导出、透明桌面窗口、按宠物轮廓点击穿透、全局键鼠空闲时间、登录启动和共享资源布局。高级版仍需在签名后的 macOS 实机产物上完成最终发行验收。Linux 会安全降级，便于后续扩展。

## 当前功能与边界

### 客户端版本

- **标准版（PySide6）**：提供当前成熟的设置、精灵图导入、动画时长编辑、系统光标和跨平台基础能力。
- **高级版（Godot 4.7 / GDScript）**：共享同一宠物库、设置、局域网协议和特效资源，提供 GPU 高刷新率、透明区域鼠标穿透、自动行走、转向、程序化跳跃、鼠标跟随和 60 FPS 省电模式。

高级版当前已覆盖宠物播放、状态机、拖动/点击、托盘菜单、原生设置窗口、缩放、暂停、多宠物切换、Windows/macOS 全局鼠标与键盘空闲动作、倒计时、动画时长编辑、精灵图自动/手动选帧导入、系统光标主题、程序与远程资源更新入口、开机启动、本机事件接口、局域网发现与互动、本地 PNG 特效及互动气泡。详见 [`docs/godot-advanced-client-plan.md`](docs/godot-advanced-client-plan.md)。

- 透明、无边框、置顶桌宠；支持缩放、悬停、点击、拖动、释放及位置保存。
- 宠物旁可显示工作日上下班倒计时；可在设置中开关并调整上下班时间。
- 宠物包自动校验、扫描、切换与重新加载；随项目提供 Pillow 生成的 `sample_pet`。
- 系统托盘提供显示/隐藏、暂停、切换宠物、导入精灵图、逐动作时长编辑、重新加载、设置和退出。
- 鼠标样式可在 Windows 和 macOS 替换主题包含的普通箭头、文本、忙碌、移动及缩放光标；macOS 通过 WindowServer 光标注册表原生替换，并在关闭功能或退出时恢复此前的系统样式。
- macOS 原生光标实现参考 [Mousecape](https://github.com/alexzielenski/Mousecape) 的公开架构，依赖未公开的 WindowServer 接口；当前已在 macOS 15.7.7 验证，系统升级后仍需重新做替换与恢复测试。
- 本机 TCP 事件接口只监听 `127.0.0.1`，支持 `agent.working`、`agent.success` 等通用事件。
- 标准版第一阶段不实现自动行走和重力；高级版已提供自动行走与程序化跳跃。两个版本均不包含在线商店、账户或云同步。
- 高级版在 Windows 由原生逐像素窗口、在 macOS 由 Godot `mouse_passthrough_polygon` 实现透明区域点击穿透；标准版仍使用应用内部 alpha 命中判断。
- macOS 高级版通过 `IOHIDSystem/HIDIdleTime` 只读取距上次全局键盘或鼠标输入的时长，不安装按键内容钩子；辅助程序不可用时安全退回鼠标移动检测。

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

### Godot 4.7 高级版开发

构建机需要 Godot 4.7.1 stable 和同版本的目标平台导出模板；最终用户运行导出的 EXE 或 `.app` 时不需要安装 Godot 编辑器。可通过 `PETNEST_GODOT_EXE` 指向 Godot 可执行文件：

```powershell
$env:PETNEST_GODOT_EXE = "D:\Tools\Godot\4.7.1\Godot_v4.7.1-stable_win64_console.exe"
& $env:PETNEST_GODOT_EXE --path clients\godot --editor
& $env:PETNEST_GODOT_EXE --headless --path clients\godot --script res://tests/smoke_test.gd
.\clients\godot\build-windows.ps1
```

macOS 高级版开发与构建：

```bash
export PETNEST_GODOT_EXE="/Applications/Godot.app/Contents/MacOS/Godot"
"$PETNEST_GODOT_EXE" --path clients/godot --editor
sh clients/godot/build-macos.sh
```

高级版导出到 `dist\PetNestGodot\PetNestGodot.exe`，构建脚本同时复制 `effects` 和 Windows 原生透明显示器到高级版目录。Godot 负责动画状态、自动行走、跳跃和高刷新率调度；Windows 由独立的 `UpdateLayeredWindow` 逐像素 Alpha 窗口显示最终 PNG 帧，并由 DWM 合成到桌面。该路径保留半透明边缘，不使用洋红色键，也避开部分显卡驱动上透明交换链产生的黑底、黑色剪影或闪烁。开发运行会自动发现仓库资源；也可设置 `PETNEST_PETS_ROOT` 指定宠物库。

高级版托盘或宠物右键菜单可直接打开设置、局域网互动、动画时长编辑器、精灵图导入器、程序更新和远程资源更新，也可直接预览已安装特效。Godot 与 PySide6 使用同一 UDP `18487` 协议，可以互相发现并发送招呼、爱心、文字或特效 ID。原生导入器支持标准 8×9（1536×1872）以及可选扩展 8×11（1536×2288）透明 PNG，可自动跳过透明格位，也可手动选择每个动作的帧，并且不会覆盖已有同名宠物。默认安装只提供中性的 `sample_pet`。

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

## 导入 Lottie 动效

PetNest 保留 Lottie JSON 作为源文件，但运行时优先播放导入生成的透明 PNG 缓存。这样动效可以保留原始文件便于以后重新生成，同时播放不需要每帧重新计算矢量路径；局域网互动只传递动效 ID，不传输 JSON 或图片。

命令行导入示例：

```powershell
python tools/import_lottie_effect.py "E:\assets\heart.json" `
  --effect-id heart-burst --effects-root effects --name "满天爱心"
```

生成的目录结构如下：

```text
effects/heart-burst/
├─ effect.json   # 动效 ID、尺寸、FPS、时长、帧数和 layer
├─ source.json   # 原始 Lottie 源文件
└─ frames/       # 运行时播放的 RGBA PNG 帧
```

导入过程会先写入临时目录，全部帧渲染并校验成功后才切换到最终目录；同 ID 默认不会覆盖已有动效，确认替换时才使用 `--overwrite`。当前使用 `rlottie-python`，安装依赖后即可在 Windows、macOS 和 Linux 上生成缓存。

`effect.json` 的 `layer` 可设为 `over`（盖在宠物上层，默认）或 `under`（显示在宠物下层）。例如：

```json
{"id":"heart-burst","frames":"frames","layer":"over"}
```

## 局域网互动入口

托盘菜单中的“局域网互动…”提供附近设备、昵称和三种互斥发送方式：快捷互动、文字、动效。应用默认开启局域网发现，也可在设置或互动页面关闭“允许附近设备发现我”。昵称保存在用户设置中；未设置时使用 `用户-短设备码`。互动消息只携带类型、目标设备 ID、发送方名称和文字或动效 ID，不传输宠物图片、Lottie JSON 或 PNG 资源。动效接收端按本地同 ID 的 `effect.json` 播放，因此双方需要预先安装同名动效包。

发现和发送使用同一局域网内的 UDP 广播/单播，固定端口为 `18487`。如果两个设备处于不同网段、自动广播发现不到，可在互动窗口点击“手动添加 IP”，输入对方 IPv4；PetNest 会发送一次定向握手，成功后才把设备加入列表，并每 8 秒定向刷新一次。连续 24 秒没有回应才会移除设备。手动地址只在本次运行中使用，不会保存。两个网段之间仍必须允许路由互通，且双方防火墙放行 UDP `18487`。接收端会限制消息大小、内容类型和单个设备的发送频率；收到打招呼、爱心或文字时在宠物旁显示短气泡，收到已安装的动效时按清单的 `layer` 播放。

Windows 安装器会请求管理员权限并创建一条仅绑定 `PetNest.exe` 的 UDP `18487` 入站防火墙规则，默认只允许「专用网络」。安装页可选开启「公用网络」；不建议在咖啡店、机场等不可信网络中开启。卸载时会删除 PetNest 创建的规则。若规则创建失败，安装器会明确提示，程序本身仍可正常启动。

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

PetNest 默认启用「系统空闲动作」，每秒通过系统接口读取最后一次鼠标或键盘输入的时间差；它不会记录按键、鼠标位置或任何输入内容。默认规则是：20 秒无操作触发 `bored`，35 秒无操作触发 `sleep`，恢复系统输入触发一次 `wake`。

宠物包可在 `animations` 中提供 `bored`、`sleep`、`wake` 动作；缺少其中任何资源时会安全回退到 `idle`。高级版在 Windows 和 macOS 都使用全系统空闲时间，不限于宠物窗口；平台辅助程序不可用时不会影响桌宠正常运行。

## 打包

Windows 使用 PyInstaller `--onedir` 生成标准版；检测到 Godot 4.7.1 时同时导出高级版，再用 Inno Setup 生成 `PetNest-Setup.exe`。构建机需要先安装 Inno Setup 6；Windows 必须在 Windows 上构建，macOS 必须在 macOS 上构建；PyInstaller 不支持可靠的跨平台交叉打包。

```powershell
.\build_windows.bat
```

完成后安装包位于 `dist\installer\PetNest-Setup.exe`。安装向导可选择 Godot 高级版组件，并分别创建标准版和高级版快捷方式；宠物库由两个客户端共享，默认位于 `%LOCALAPPDATA%\PetNest\pets`。设置 `PETNEST_BUILD_GODOT=0` 可只构建标准版；本机缺少 Godot 时也会自动跳过高级版。

```bash
./build_macos.sh
```

macOS 构建同时生成标准版 `dist/PetNest.app`、高级版 `dist/PetNest Advanced.app` 和便于传输的 `dist/PetNest-Advanced-macOS.zip`。高级版只预置中性的 `sample_pet`。默认执行临时签名；正式分发请设置 `PETNEST_CODESIGN_IDENTITY` 使用 Developer ID，并在发行前完成 Apple 公证和 macOS 实机透明/输入回归。

## 隐私与日志

PetNest 只在用户配置目录保存宠物 ID、窗口位置和显示偏好；日志写入用户日志目录并轮转。不会记录键盘内容、文件内容、窗口标题、完整命令、Agent 对话或外部事件 payload。外部服务仅在用户启用时启动。

## 许可证

本项目采用 [MIT License](LICENSE)。

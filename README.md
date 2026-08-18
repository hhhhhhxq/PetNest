# PetNest

PetNest 是一个基于 Python 3.12+ 与 PySide6 的跨平台轻量桌面宠物播放器。它播放由 `pet.json` 配置的透明 PNG 序列帧，不绑定特定角色、AI 工具或素材风格。

目前以 Windows 10/11 为主要目标；macOS 已支持基础桌宠运行和自定义系统光标，并在 macOS 实机完成开发环境验证。Linux 会安全降级，便于后续扩展。

## 当前功能与边界

- 透明、无边框、置顶桌宠；支持缩放、悬停、点击、拖动、释放及位置保存。
- 宠物旁可显示工作日上下班倒计时；可在设置中开关并调整上下班时间。
- 宠物包自动校验、扫描、切换与重新加载；随项目提供 Pillow 生成的 `sample_pet`。
- 系统托盘提供显示/隐藏、暂停、切换宠物、宠物与动作交换中心、逐动作时长编辑、重新加载、设置和退出；旧的精灵图/下班动画入口仍保留兼容。
- Codex 用量面板可读取当前 ChatGPT/Codex 账号的滚动周额度、账号 Token 汇总，并统计当前电脑在本额度周期内的 Token。
- 附近设备可私聊、进入普通局域网群聊，或自行加入固定的“局域网预警组”；预警组支持聊天和带全屏红色闪烁的危险预警，会话记录不落盘。
- 鼠标样式可在 Windows 和 macOS 替换主题包含的普通箭头、文本、忙碌、移动及缩放光标；macOS 通过 WindowServer 光标注册表原生替换，并在关闭功能或退出时恢复此前的系统样式。
- macOS 原生光标实现参考 [Mousecape](https://github.com/alexzielenski/Mousecape) 的公开架构，依赖未公开的 WindowServer 接口；当前已在 macOS 15.7.7 验证，系统升级后仍需重新做替换与恢复测试。
- 本机 TCP 事件接口只监听 `127.0.0.1`，支持 `agent.working`、`agent.success` 等通用事件。
- 第一阶段不实现自动行走、重力、多宠物、在线商店或云同步；Codex 用量面板不接管登录、不保存认证凭据。
- 已实现应用内部的透明 alpha 命中判断；**系统级按像素点击穿透尚未实现**，不要将它视作安全或无干扰的输入方案。
- macOS 系统空闲、会话事件与登录启动项目前是安全 fallback；正式发布前仍需完成签名产物的 macOS 回归测试。

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

## Codex 用量与账号区分

在系统托盘中选择「Codex 用量…」即可打开面板。PetNest 通过本机已安装的 Codex app-server 读取当前登录账号的账号类型、套餐、滚动额度窗口和 Token 汇总；不直接读取或保存 Codex 的认证文件。

本机 Token 从 Codex 会话中的 `token_count` 事件累加，并用当前账号额度窗口的重置时间做匹配，避免在普通切换账号或进入新周期时混入旧记录。当额度重置时，当前周期从新窗口重新计算；已过期周期会从本机日志补算并归档。面板的「周期」下拉框可查看当前周期和各个往期快照；局域网设备的往期数据为该周期最后一次同步到的快照。

历史以“账号 + 额度重置时间”分区保存，账号键为邮箱 SHA-256 摘要的前 24 个十六进制字符，界面和历史文件中只出现脱敏邮箱。切换账号后刷新，账号下拉框会分开展示当前账号和其他账号。

Codex 对输入、缓存输入、输出和不同模型采用不同用量权重，不能用总 Token 直接等比换算周额度；本地 app-server 的滚动窗口只返回账号级的已用百分比。因此面板可精确显示本机 Token，但“本机消耗额度”显示的是本机请求期间观察到的账号已用百分比变化。如果同一账号同时在其他电脑使用，这个百分比变化无法精确拆分到单台电脑。

多台电脑在局域网内互相发现，或在「Codex 用量」中点击「连接电脑…」、从托盘「互动…」→「连接电脑 IP」完成定向握手后，双方都会立即互换各自当前账号的本机 Token 快照；连接保持期间每 5 分钟重新同步，在用量面板手动刷新也会触发同步。接收方无需登录过对方的账号：局域网出现的新账号也会加入账号下拉框，并标注为“局域网 / 本机未登录”。不同账号和额度周期分别存放，排名时只组合当前所选账号、周期一致的数据，不会重复累加。

用量面板的「同账号设备用量排名（预估）」会在同一账号、同一额度周期内按各电脑 Token 总量降序排列。每台设备的预估额度占用按 `设备 Token ÷ 已同步且有匹配记录的设备 Token 合计 × 账号当前已用额度` 动态折算；这只是已知设备之间的比例，不代表 Codex 官方的单机归因，也无法确定未同步设备的占用。排名同时显示每台电脑的 Token、模型请求数、最常用模型，以及实际产生 Token 的模型回合中“极快”（`priority`）和“标准”（`default`）的占比。切换顶部「账号」或「周期」会切换相应排名。

设备快照会一并同步本机日志扫描状态、已扫描文件数和读取失败数。没有匹配记录时界面显示原因，不再把“未发现会话文件”“日志不可读”“当前账号/周期无匹配事件”或旧版未知状态统一表现成确定的 `0 Token`。Codex 会话日志本身不包含账号 ID，PetNest 只能用额度类型和重置时间关联账号周期；普通账号切换可被分开，但重置时间极近的两个账号仍可能存在歧义，界面会明确提示这一关联依据。

局域网包只包含账号哈希、脱敏账号名、套餐、账号已用百分比、设备 ID/显示名、额度周期、分类 Token 计数、模型汇总、速度模式计数和日志扫描诊断，不包含原始邮箱、提示词、回复、会话文件、文件路径或认证凭据。每次收到的有效快照都会按账号、额度周期和设备 ID 写入本机 `codex-usage-history-devices.json`，重启后仍可读取，旧周期不会被新周期覆盖。该通道复用 UDP `18487`，不提供端到端加密；只应在可信局域网内使用。自动发现的临时设备会在重启后重新发现；手动验证成功的局域网伙伴会保存到 `known-lan-peers.json`，以后启动时自动定向重连。

Windows 下会依次尝试 ChatGPT/Codex 安装目录、`codex.exe`、`codex.cmd` 和 `codex`。若 Microsoft Store 的受保护可执行文件拒绝访问，会自动继续尝试后续候选；批处理启动器通过系统命令处理器运行。

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

## 宠物与动作交换中心

在托盘的「宠物与动作…」中可以完成三类操作：

- **导出动作分享包**：选择宠物后会列出它的全部动作，包括普通动作和全屏动作；可搜索、按类型筛选、多选、预览，再自动生成一个 ZIP。逐帧时长会随动作一起导出；「同时分享相关绑定」默认关闭，避免影响接收方已有快捷键。
- **导入动作**：可直接选择别人分享的动作 ZIP、完整宠物文件夹/ZIP，或历史版下班动画包。完整宠物来源会列出其中的动作，用户只勾选需要的部分即可。动作冲突可逐项选择「替换」「重命名」或「跳过」，不需要编辑任何 JSON。
- **导入宠物**：完整宠物文件夹或 ZIP 会自动识别，外层文件夹名和 ZIP 文件名都没有要求；新增或更新同 ID 宠物时，更新默认先生成备份再整包替换，也可以勾选保留本地独有动作。透明精灵图仍可在同一窗口中导入，继续使用现有的尺寸检测、动作映射、帧选择和时长编辑能力。

更新或安装会先在临时目录校验，失败时不会留下半成品。当前宠物正在显示下班提醒时，交换中心会暂时锁定该宠物的资源；关闭提醒后即可继续。旧版下班动画包会自动转换成普通的两个全屏动作，原有下班倒计时行为不受影响。

分享时直接把页面生成的 ZIP 发给别人即可；接收方不需要知道包内文件名，也不需要手写清单文件。

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

托盘菜单中的“局域网互动…”提供附近设备、昵称、快捷互动、短文字、动效和聊天。设备列表顶部的“局域网群聊”会把一条消息分别发送给发送当时已连接的所有附近设备；新加入的设备不会补收此前消息。群聊与每台设备的私聊记录分开显示，都可发送最多 2,000 字的文字、常用表情和图片。原图不会被修改；发送前会缩放至最长边 1,600 像素并转为不超过 1.5 MB 的 JPEG。聊天记录只保留在当前 PetNest 进程内，关闭后不保存。

“局域网预警组”是所有兼容客户端都认识的固定频道，没有群主、邀请或踢人机制。每台设备只能决定自己是否加入；加入后可参与组内聊天，并可从桌宠右键菜单选择“⚠ 发送危险预警”。发送前会列出在线接收人并要求二次确认。接收方只在桌宠所在屏幕显示约 1.5 秒、3 次峰值的红色半透明警示和发送者昵称，不播放声音、不抢焦点、不拦截鼠标。预警使用独立 UDP 消息和送达确认，不由聊天文字触发；重复包不会重复闪屏，发送频率也受到限制。旧版客户端没有预警组入口，仍可使用原有私聊、普通群聊和互动。

应用默认开启局域网发现，也可在设置或互动页面关闭“允许附近设备发现我”。收到群聊时，桌宠旁默认显示带发送人名称的消息气泡；可在互动窗口关闭“群聊消息显示宠物气泡”，关闭后消息仍会正常接收并进入本次运行的群聊记录，私聊提示不受影响。该选项保存在本机。昵称保存在用户设置中；未设置时使用 `用户-短设备码`。快捷互动消息只携带类型、目标设备 ID、发送方名称和文字或动效 ID，不传输宠物图片、Lottie JSON 或 PNG 资源。动效接收端按本地同 ID 的 `effect.json` 播放，因此双方需要预先安装同名动效包。

发现、快捷互动、危险预警和 Codex 用量同步使用 UDP，聊天使用有长度分帧的 TCP，两者都使用固定数字端口 `18487`。自动发现会枚举本机所有有效 IPv4 接口，分别向有线、Wi-Fi 等接口的广播地址发送握手，同时保留 limited broadcast 兼容发送；它不会主动扫描整个地址段，也无法保证跨越 VLAN 或路由器发现其他子网。

如果两个设备处于不同网段、自动广播发现不到，可在互动窗口点击“连接电脑 IP”输入对方 IPv4。定向握手成功后会保存设备 ID、昵称和最近端点，并每 8 秒续期；应用重启后自动重新连接。保存伙伴离线时仍保留在列表中，可更新地址或忘记；更新地址必须重新验证原设备身份，不能把 DHCP 复用后的 IP 静默绑定给其他设备。两个网段之间必须允许路由互通，且双方防火墙需同时放行 UDP 和 TCP `18487`。接收端会核对已握手的设备 ID、IP 与端口，并限制消息大小、内容类型和单个设备的发送频率。局域网聊天和预警没有端到端加密，只应在可信办公网络使用，不要发送密码、令牌或其他敏感内容。

Windows 安装器会请求管理员权限并创建仅绑定 `PetNest.exe` 的 UDP/TCP `18487` 入站防火墙规则，默认只允许「专用网络」。安装页可选开启「公用网络」；不建议在咖啡店、机场等不可信网络中开启。卸载时会删除 PetNest 创建的规则。若规则创建失败，安装器会明确提示，程序本身仍可正常启动。

## Firebase 远程伙伴

互动窗口同时提供“远程伙伴”页。两台设备不需要位于同一局域网：一方复制自己的 10 位伙伴码，另一方点击“添加远程伙伴”并输入该码即可建立关系。快捷互动、文字和动效仍复用局域网互动的最小消息格式；Firebase 只中继互动类型、双方身份摘要、文字或动效 ID，不上传宠物图片与动效资源。未运行期间收到的消息会在下次启动时补收，消息最长保留 7 天。

远程伙伴默认保持开启，但只有找到有效 Firebase 配置后才会访问网络；未配置或连接失败不会影响局域网互动和桌宠的其他功能。客户端使用 Firebase Anonymous Auth，用户不需要注册、输入账号或看到登录页面。刷新令牌单独保存在用户配置目录的 `firebase-remote-credentials.json` 中，不写入普通设置或日志。Firebase Web API Key 不是服务账号密钥；禁止把 Admin SDK 凭据或服务账号 JSON 放进安装包。

部署自己的 Firebase 后端：

1. 在 Firebase 控制台启用 Authentication 的 Anonymous 登录，并创建 Realtime Database。
2. 在 `firebase/` 目录先运行 `firebase use --add` 选择项目，再运行 `firebase deploy --only database`，部署仓库提供的 `database.rules.json`。这些规则限制用户只能读取自己的账号节点，并校验配对请求和互动消息。
3. 在 Firebase 控制台下载原版 `google-services.json`，保持这个文件名不变。确认其中包含 `project_info/firebase_url`；如果没有，请先创建 Realtime Database，再重新下载。
4. 开发时把 `google-services.json` 放在项目根目录。该路径已加入 `.gitignore`，不要使用 `git add -f` 提交。Windows 和 macOS 打包脚本会在本地构建时自动把它放入安装包；已经安装的版本也可以直接从下列用户配置目录读取它。

用户配置目录分别为：

- Windows：`%APPDATA%\PetNest`
- macOS：`~/Library/Application Support/PetNest`
- Linux：`${XDG_CONFIG_HOME:-~/.config}/PetNest`

开发和自动部署环境也可在启动进程时提供 `PETNEST_FIREBASE_API_KEY` 与 `PETNEST_FIREBASE_DATABASE_URL` 环境变量。Firebase 客户端 API Key 只标识项目，不负责数据库授权；不要把服务账号、Admin SDK 私钥、FCM 服务端密钥等真正的 Secret 放入客户端或安装包。普通互动内容只受 HTTPS 传输保护，并非端到端加密；不要通过文字互动发送密码、令牌或其他敏感信息。

PetNest 会直接从原版 `google-services.json` 读取 `project_info/firebase_url`、`project_info/project_id` 和首个客户端的 `api_key/current_key`，不依赖 Gradle 插件。原来的简化版 `firebase.json` 仍兼容，可参考 `firebase/firebase.example.json`。配置优先级为：环境变量、用户目录 `firebase.json`、用户目录 `google-services.json`、安装包内或项目根目录的 `google-services.json`。

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

宠物包可在 `animations` 中提供 `bored`、`sleep`、`wake` 动作；缺少其中任何资源时会安全回退到 `idle`。该功能在 Windows 使用全系统空闲时间，不限于宠物窗口；其他平台暂不支持时不会影响桌宠正常运行。

## 打包

Windows 使用 PyInstaller `--onedir` 生成应用目录，再用 Inno Setup 生成带版本号的 `PetNest-Setup-<version>.exe`。构建机需要先安装 Inno Setup 6；Windows 必须在 Windows 上构建，macOS 必须在 macOS 上构建；PyInstaller 不支持可靠的跨平台交叉打包。

```powershell
.\build_windows.bat
```

完成后安装包位于 `dist\installer\PetNest-Setup-<version>.exe`。安装向导可选择程序安装目录，并提供“将宠物库保存到自定义位置”的可选高级项；默认宠物库位于 `%LOCALAPPDATA%\PetNest\pets`。Windows 和 macOS 都可以在设置页通过“检查程序更新…”下载并安装 GitHub Release 中的新版本。

```bash
./build_macos.sh
```

macOS 构建会生成 `dist/release/PetNest-macOS-x64-<version>.zip` 并做 ad-hoc 签名。面向陌生用户免提示分发仍需要 Apple Developer ID 签名和公证。

## 隐私与日志

PetNest 只在用户配置目录保存宠物 ID、窗口位置和显示偏好；日志写入用户日志目录并轮转。不会记录键盘内容、文件内容、窗口标题、完整命令、Agent 对话或外部事件 payload。外部服务仅在用户启用时启动。

## 许可证

本项目采用 [MIT License](LICENSE)。

# 下班全屏躺下循环动作设计

## 目标

把下班全屏动画从两阶段扩展为可选三阶段：

```text
work_finish_walk → work_finish_lie_down → work_finish_lie_loop
```

`work_finish_lie_loop` 表示宠物完成躺下过渡后的持续循环动作。第三阶段完全可选；旧包或未选择循环图片时继续停在 `work_finish_lie_down` 最后一帧，与当前行为一致。

## 动作与源包命名

- 旧版来源 manifest 字段：`lie_loop`
- 来源文件夹推荐名：`lie-loop`，实际目录由 `lie_loop.path` 指定，不硬编码目录拼写
- 安装到宠物包后的动作：`work_finish_lie_loop`
- `scope`：`fullscreen`
- `loop`：始终为 `true`
- `canvas`：与 walk、lie_down 共用来源 manifest 的全屏 canvas

来源 manifest 示例：

```json
{
  "name": "平安下班",
  "canvas": {"width": 1920, "height": 1080},
  "walk": {"path": "walk", "fps": 12},
  "lie_down": {"path": "lie-down", "fps": 12},
  "lie_loop": {
    "path": "lie-loop",
    "fps": 8,
    "frame_durations_ms": [160, 160, 220]
  }
}
```

## 导入兼容

`walk` 与 `lie_down` 仍为必需阶段。`lie_loop` 按以下规则解析：

- 字段完全缺失：合法旧包，循环帧数为 0。
- 字段存在：必须是对象，且 path、fps、PNG、alpha、canvas、逐帧时长通过与其他阶段相同的安全校验。
- 字段存在但目录为空、没有 PNG、路径逃逸或时长数量不符：导入失败，不静默当作缺失。
- UI 未传循环图片时不生成 `lie_loop` 字段，也不创建空文件夹。
- 安装新版包时，若目标宠物已有 `work_finish_lie_loop` 而新包没有该动作，应移除旧循环动作，避免用户以为已经取消循环但仍播放旧素材。
- 安装失败沿用原子回滚，恢复三个动作及 pet.json。

检查摘要与安装结果增加 `lie_loop_frames`；旧包返回 0。导入页成功文案在非零时显示循环帧数，为零时明确显示“躺下后保持最后一帧”。

## 动作解析

`resolve_work_finish_animation()` 返回：

- `walk`
- `lie_down`
- `lie_loop`，可为 `None`
- `is_specialized`

只有 `work_finish_walk` 与 `work_finish_lie_down` 成对且均为 fullscreen 时才采用专属全屏动画。`work_finish_lie_loop` 只有在专属动作对有效、其自身也是 fullscreen 时才加入；单独存在的循环动作不会启用。

普通宠物动作回退保持现状：进入阶段按 walk/drag/directional drag/idle，躺下阶段按 sleep/idle；普通回退不凭空生成第三阶段。

## 播放时间线

播放器加载三组帧与逐帧时长：

1. `walking`：固定 4 秒内移动到屏幕中心，按 walk 时间线循环。
2. `lying`：从第 0 帧开始非循环播放完整 lie_down 时间线。
3. lie_down 播放结束后：
   - 有 lie_loop 帧：进入 `lying_loop`，从循环第 0 帧开始并按自己的时长无限循环。
   - 无 lie_loop 帧：进入 `holding`，持续显示 lie_down 最后一帧。

若 walk 缺失但 lie_down 可用，仍直接进入 lie_down；若所有可显示帧均缺失，动画层隐藏但控制面板照常显示。

`current_frame_index` 始终表示当前阶段内部索引，切换到 `lying_loop` 时重置为 0。循环阶段的计时起点是 lie_down 总时长结束点，不能继续使用包含过渡时长的偏移导致首帧跳过。

## 编辑与展示

- 动作时长编辑器增加 `work_finish_lie_loop` 中文说明“全屏下班提醒 · 躺下循环”。
- 动作交换中心把它视为普通 fullscreen 动作，可单独导出和安装。
- 下班动画专用导入仍以三阶段整体安装，确保替换/删除语义一致。
- 本次不改变全屏动画尺寸、进入方向、控制面板、30 分钟超时或工作状态逻辑。

## 安全与错误处理

- 文件数与解压总量沿用当前上限；第三阶段文件计入同一总量。
- ZIP 路径、符号链接、压缩比、PNG 类型和尺寸检查不降低。
- 可选仅表示字段可以缺失，不表示错误字段可以被忽略。
- 新包不含循环动作时会显式删除目标宠物的旧 `work_finish_lie_loop`，但不会删除其他任何动作目录。
- 所有动作目录替换都限定在目标宠物的 `animations` 下并使用现有备份/回滚机制。

## 验收标准

- 三阶段包导入后生成三个 fullscreen 动作，循环动作 `loop=true`。
- 躺下过渡结束后，循环从第 0 帧开始并持续重复。
- 缺少 `lie_loop` 的旧包仍可导入，且停在 lie_down 最后一帧。
- 新包不含循环素材时会清除该宠物之前安装的旧循环动作。
- 空目录、损坏图片、尺寸不符、非法路径和错误时长均阻止安装并保留原宠物。
- 专属动作不完整时不单独启用 lie_loop。
- 导入摘要、成功反馈和动作编辑器能正确显示第三阶段。
- 相关导入、动作解析、播放窗口、动作交换及完整测试套件通过。

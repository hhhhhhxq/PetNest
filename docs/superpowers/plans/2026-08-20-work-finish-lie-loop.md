# 下班全屏躺下循环动作实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 按任务执行，所有生产改动先运行对应失败测试。

**目标：** 为下班全屏动画增加可选 `work_finish_lie_loop` 第三阶段，缺失时保持躺下最后一帧。

**架构：** 旧 manifest 适配器把可选 `lie_loop` 转换为第三个 fullscreen 动作；动作安装事务支持在同一次 pet.json 原子提交中删除未随新包提供的旧循环动作；播放器在走入和躺下过渡后选择循环或停帧。

**技术栈：** Python 3.12、PySide6、Pillow、pytest、pytest-qt

---

### 任务 1：旧包格式适配与摘要

**文件：**
- 修改：`src/petnest/core/action_transfer.py`
- 修改：`src/petnest/core/work_finish_importer.py`
- 测试：`tests/test_action_transfer.py`
- 测试：`tests/test_work_finish_importer.py`

- [x] 扩展测试 bundle，分别覆盖缺失 `lie_loop` 与含 3 帧 `lie_loop`。
- [x] 断言三阶段包生成 `work_finish_lie_loop`、`loop=true`、逐帧时长与 fullscreen canvas；旧包动作集合仍只有两个。
- [x] 运行测试确认适配器忽略或拒绝第三阶段的现状失败。
- [x] 将必需阶段循环与可选阶段解析分开；字段存在时复用路径、FPS、PNG、尺寸和时长校验。
- [x] 扩展 `WorkFinishBundleSummary`/`WorkFinishImportResult` 的 `lie_loop_frames`，旧包为 0。
- [x] 运行两个测试文件确认通过。

### 任务 2：缺失循环动作的原子删除

**文件：**
- 修改：`src/petnest/core/action_installer.py`
- 修改：`src/petnest/core/work_finish_importer.py`
- 测试：`tests/test_action_installer.py`
- 测试：`tests/test_work_finish_importer.py`

- [x] 为 `install_actions(..., remove_actions=(...))` 写失败测试：候选配置删除指定动作、保留其他动作、旧目录进入 superseded，rollback 恢复原始配置。
- [x] 运行测试确认构造器尚不接受 `remove_actions`。
- [x] 在安装计划构建后验证删除名安全、不得与安装目标重叠，并从候选 animations 删除旧定义。
- [x] WorkFinishImporter 在 pack 缺少第三动作时传入 `remove_actions=("work_finish_lie_loop",)`；存在时按 replace 安装。
- [x] 验证旧双阶段包能移除旧循环动作，安装失败恢复三个旧动作。

### 任务 3：三阶段动作解析与播放时间线

**文件：**
- 修改：`src/petnest/core/work_finish_animation.py`
- 修改：`src/petnest/ui/work_finish_reminder.py`
- 测试：`tests/test_work_finish_animation.py`
- 测试：`tests/test_work_finish_reminder.py`

- [x] 扩展 `WorkFinishAnimationSet` 测试，专属三件套返回 loop，旧两件套返回 None，孤立 loop 被忽略。
- [x] 写播放器失败测试：lie_down 结束瞬间进入 `lying_loop` 第 0 帧，之后按循环时长取模；无 loop 仍进入 holding。
- [x] 加载第三组 pixmap/durations，并用 `lie_elapsed_ms - lie_total` 作为循环时间。
- [x] `_current_pixmap()` 按 walking/lying/lying_loop/holding 选择正确帧组。
- [x] 运行解析和 Qt 窗口测试确认通过。

### 任务 4：导入反馈与动作说明

**文件：**
- 修改：`src/petnest/ui/work_finish_import_dialog.py`
- 修改：`src/petnest/ui/animation_timing_editor.py`
- 测试：`tests/test_work_finish_import_dialog.py`

- [x] 写导入页测试：有循环显示“循环 N 帧”，无循环显示“躺下后保持最后一帧”，已有第三动作也触发替换确认。
- [x] 更新摘要文案、existing 检查列表和动作编辑器中文说明。
- [x] 运行 UI 测试确认通过。

### 任务 5：验证与提交

- [x] 运行下班动画、动作安装、动作传输、包校验相关测试。
- [x] 运行 `python -m pytest -q` 完整套件。
- [x] 运行 `python -m compileall -q src tests tools` 与 `git diff --check`。
- [x] 审查暂存边界，排除未跟踪素材与用户文件。
- [x] 提交为 `feat: 支持下班后躺下循环动画`。

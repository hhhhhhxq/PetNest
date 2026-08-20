# 方向拖动动作命名与资源迁移实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 按任务实现；所有生产改动先有失败测试。

**目标：** 对称命名 Codex 拖动方向动作，迁移所有线上错误资源并重新发布资源目录。

**架构：** 导入器写出 `drag_right/drag_left`，状态机仍通过抽象 `drag` fallback 启动；PetWindow 负责实时方向选择并兼容旧别名。资源库从已校验源目录确定性重建受影响商品，目录生成器沿 fallback 计算能力。

**技术栈：** Python 3.12、PySide6、pytest、ZIP/JSON、Git

---

### 任务 1：导入命名与旧包运行时兼容

**文件：**
- 修改：`src/petnest/core/spritesheet_importer.py`
- 修改：`src/petnest/ui/spritesheet_import_content.py`
- 修改：`src/petnest/ui/pet_window.py`
- 测试：`tests/test_spritesheet_importer.py`
- 测试：`tests/test_spritesheet_import_content.py`
- 测试：`tests/test_pet_window.py`

- [x] 先将导入测试改为要求 `drag_right/drag_left`、禁止 `codex_running_left`，并要求 `drag` fallback。
- [x] 运行相关测试，确认因旧映射失败。
- [x] 修改行映射、页面文案与左向旧名兼容候选。
- [x] 运行导入和 PetWindow 测试，确认新旧包都能选择正确方向。

### 任务 2：下班动画方向动作回退

**文件：**
- 修改：`src/petnest/core/work_finish_animation.py`
- 测试：`tests/test_work_finish_animation.py`

- [x] 写入只有 `drag_right/drag_left` 的失败测试，要求优先选择 `drag_right`。
- [x] 运行测试确认当前回退到 idle。
- [x] 添加方向拖动动作回退并运行测试通过。

### 任务 3：商店能力解析

**文件：**
- 修改：`F:/Desktop Projects/petnest-resources-work/tools/build_store_catalog.py`
- 测试：`F:/Desktop Projects/petnest-resources-work/tests/test_build_store_catalog.py`

- [x] 增加绑定 `drag` 且 fallback 指向 `drag_right/drag_left` 的目录能力测试。
- [x] 运行资源目录测试确认 `drag` 能力缺失。
- [x] 实现带循环保护的 fallback 解析并确认测试通过。

### 任务 4：迁移并重新发布受影响商品

**文件：**
- 修改：`pets/{desk-nap-cat,joker-bear-plush,lulu,miffy}` 对应动作目录与 `pet.json`
- 生成：`F:/Desktop Projects/petnest-resources-work/store/pets/<id>/{package.zip,cover.png,idle-preview.png}`
- 生成：`F:/Desktop Projects/petnest-resources-work/store/catalog.json`

- [x] 验证所有源目录与目标目录的绝对路径均在预期仓库内，再重命名两个动作目录。
- [x] 结构化更新四个 `pet.json` 的 animations、路径、fallbacks 和导入元数据。
- [x] 同时把 miffy 的旧 `drop/hover/success` 映射迁移为 `hover/review/review`。
- [x] 用 `publish_pet.py` 在临时目录生成商品并替换四个目标商品文件。
- [x] 重建 catalog，确认其他商品文件哈希保持不变。
- [x] 将 V2 A/B 环视行合并为 `look_directions/001–016`，并重新发布 lulu。

### 任务 5：验证、提交与上线

- [x] 运行 PetNest 相关测试和完整资源仓库测试。
- [x] 校验四个源包、所有线上 ZIP、目录哈希和错误名称扫描。
- [x] 运行两仓库 `git diff --check`，审查未包含用户无关改动。
- [x] 分别提交 PetNest 与资源仓库改动。
- [x] 推送资源仓库 `main` 到 `origin/main`，并核对远端提交哈希。

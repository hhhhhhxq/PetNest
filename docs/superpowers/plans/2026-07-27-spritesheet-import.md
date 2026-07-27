# 精灵图导入实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 从本地 Codex `8 × 9` 透明 PNG 精灵图创建可用的 PetNest 宠物包。

**架构：** Pillow 导入核心负责严格校验和安全写入；CLI 与 Qt 对话框共同调用该核心，避免 UI 与图像切分逻辑耦合。

**技术栈：** Python 3.12+、Pillow、PySide6、pytest、pytest-qt。

---

### 任务 1：导入核心与命令行

- [ ] 为尺寸、alpha、重复 ID、72 帧切分、默认动作映射和生成包校验编写失败测试。
- [ ] 实现 `src/petnest/core/spritesheet_importer.py` 与 `tools/import_spritesheet.py`。
- [ ] 运行 `python -m pytest tests/test_spritesheet_importer.py -q`，预期通过。

### 任务 2：桌面导入入口与说明

- [ ] 为导入对话框的规则文本和成功导入回调编写失败的 pytest-qt 测试。
- [ ] 实现 `SpriteSheetImportDialog`，在托盘和应用装配中接入导入、扫描与切换。
- [ ] 运行相关 UI 测试与完整测试套件。

### 任务 3：使用说明

- [ ] 在 README 写入图集规则、动作映射、GUI 与 CLI 操作，以及不上传素材的隐私说明。
- [ ] 运行 `python -m compileall -q src tools`、完整 pytest、导入命令行烟测和 `git diff --check`。

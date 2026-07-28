# 动画时长模式实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将动作播放方式改为明确互斥的总时长模式和逐帧模式。

**架构：** 设置模型持久化显式模式；应用层根据模式构造动画定义；对话框只编辑当前模式对应的数据并显示应用反馈。

**技术栈：** Python 3.12、PySide6、pytest。

---

### 任务 1：设置迁移与应用

**文件：** `src/petnest/models/settings.py`、`src/petnest/core/settings_manager.py`、`src/petnest/app.py`、`tests/test_settings_manager.py`、`tests/test_app_and_platforms.py`

- [ ] 编写失败测试，证明旧覆盖迁移为正确模式且逐帧模式不叠加总时长倍率。
- [ ] 添加模式字段及迁移，并按模式构造加载后的动作定义。
- [ ] 运行相关测试。

### 任务 2：模式选择界面

**文件：** `src/petnest/ui/animation_editor_dialog.py`、`tests/test_animation_editor_dialog.py`

- [ ] 编写失败测试，证明模式单选、控件互斥和当前模式可见。
- [ ] 实现总时长/逐帧单选区域与保存后应用反馈。
- [ ] 运行完整测试与编译检查。

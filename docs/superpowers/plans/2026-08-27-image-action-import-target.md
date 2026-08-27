# 图片动作导入目标修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 确保图片动作导入始终写入用户选择槽位所声明的动作，而不是该动作的运行时 fallback。

**架构：** 在 `action_slots` 中新增不遍历 fallback 的导入目标解析函数，保留 `resolve_slot` 的运行时语义。图片导入页面与动作包构建器共同使用新解析函数，保证界面提示、草稿键和最终输出一致。

**技术栈：** Python 3.11、PySide6、pytest、Pillow

---

### 任务 1：锁定槽位解析语义

**文件：**
- 修改：`tests/test_action_slots.py`
- 修改：`src/petnest/core/action_slots.py`

- [ ] **步骤 1：编写失败的测试**

增加一个带 `system.bored -> bored` 绑定、`bored -> idle` fallback 且仅有 `idle` 动画的宠物，断言运行时解析为 `idle`，导入目标解析为 `bored` 且不请求改写绑定。

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_action_slots.py -q`

预期：FAIL，原因是导入目标解析入口尚不存在。

- [ ] **步骤 3：编写最少实现代码**

在 `action_slots.py` 新增 `resolve_slot_import_target(package, slot)`：合法事件绑定直接作为动作名；没有合法绑定时使用 `canonical_action`，并按现有规则返回待创建绑定；非事件槽位不创建绑定。将函数加入 `__all__`。

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv\Scripts\python.exe -m pytest tests\test_action_slots.py -q`

预期：全部 PASS。

### 任务 2：让图片动作构建与界面使用导入目标

**文件：**
- 修改：`tests/test_image_action_builder.py`
- 修改：`tests/test_image_action_import_content.py`
- 修改：`src/petnest/core/image_action_builder.py`
- 修改：`src/petnest/ui/image_action_import_content.py`

- [ ] **步骤 1：编写失败的动作包回归测试**

构造 `system.bored -> bored`、`bored -> idle`、仅有 `idle` 的目标宠物，调用 `build_image_action_pack` 后断言 `pack.actions == {"bored": ...}`、不存在 `idle`，且不请求改写已有绑定。

- [ ] **步骤 2：编写失败的界面回归测试**

在图片导入内容中选择 `system_bored`，断言 `action_name()` 和界面目标提示都指向 `bored`，不是 `idle`。

- [ ] **步骤 3：运行测试验证失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_image_action_builder.py tests\test_image_action_import_content.py -q`

预期：回归用例 FAIL，实际目标为 `idle`。

- [ ] **步骤 4：编写最少实现代码**

将图片动作构建器和图片导入页面中的 `resolve_slot` 替换为 `resolve_slot_import_target`，不改动其他调用者。

- [ ] **步骤 5：运行测试验证通过**

运行：`.venv\Scripts\python.exe -m pytest tests\test_image_action_builder.py tests\test_image_action_import_content.py -q`

预期：全部 PASS。

### 任务 3：完整验证

**文件：**
- 验证：`src/petnest/core/action_slots.py`
- 验证：`src/petnest/core/image_action_builder.py`
- 验证：`src/petnest/ui/image_action_import_content.py`
- 验证：相关测试文件

- [ ] **步骤 1：运行相关测试集合**

运行：`.venv\Scripts\python.exe -m pytest tests\test_action_slots.py tests\test_image_action_builder.py tests\test_image_action_import_content.py tests\test_action_installer.py -q`

预期：全部 PASS，输出无错误。

- [ ] **步骤 2：检查差异与格式**

运行：`git diff --check`

预期：无输出，退出码为 0。

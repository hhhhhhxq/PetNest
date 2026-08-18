# 宠物与动作中心反馈与默认宠物实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让拥有宠物选择器的页面默认指向当前宠物，并在动作真正应用成功后给出明确通知、清空本次导入表单。

**架构：** 统一窗口把同一个 `current_pet_id` 传给动作导入、编辑和导出页面。动作页只负责磁盘安装与即时错误；应用层在运行时重载成功后调用窗口完成方法，窗口再清空导入表单并显示最终成功信息。

**技术栈：** Python 3.12、PySide6、pytest、pytest-qt。

---

### 任务 1：统一当前宠物默认选择

**文件：**
- 修改：`src/petnest/ui/action_import_page.py`
- 修改：`src/petnest/ui/action_export_page.py`
- 修改：`src/petnest/ui/pet_action_exchange_dialog.py`
- 测试：`tests/test_pet_action_exchange_dialog.py`

- [ ] **步骤 1：编写失败测试**

构造两只宠物、传入第二只为 `current_pet_id`，断言：

```python
assert dialog.action_import_page.target_combo.currentData() == "second"
assert dialog.animation_editor_page.current_package().identifier == "second"
assert dialog.action_export_page.pet_combo.currentData() == "second"
```

- [ ] **步骤 2：运行测试确认导入和导出页错误选择第一项**

运行：`.venv\Scripts\python.exe -m pytest tests/test_pet_action_exchange_dialog.py::test_exchange_dialog_defaults_pet_selectors_to_current_pet -q`

预期：FAIL，导入或导出选择器返回第一只宠物。

- [ ] **步骤 3：添加构造参数和安全回退**

`ActionImportPage` 增加关键字参数 `current_pet_id: str | None = None`；`ActionExportPage` 在保持现有 `parent` 位置参数兼容的前提下增加关键字参数。构造完成后查找目标 ID，找不到时使用第一项，空列表保持 `-1`。

- [ ] **步骤 4：让统一窗口传递同一个 desired_id**

在 `PetActionExchangeDialog` 构造三个页面时都传入已经计算的 `desired_id`。

- [ ] **步骤 5：运行选择器测试**

运行：`.venv\Scripts\python.exe -m pytest tests/test_pet_action_exchange_dialog.py tests/test_action_import_page.py tests/test_action_export_page.py tests/test_animation_editor_page.py -q`

预期：全部 PASS。

### 任务 2：区分磁盘安装与运行时应用结果

**文件：**
- 修改：`src/petnest/ui/action_import_page.py`
- 修改：`src/petnest/ui/pet_action_exchange_dialog.py`
- 修改：`src/petnest/app.py`
- 测试：`tests/test_action_import_page.py`
- 测试：`tests/test_pet_action_exchange_app.py`

- [ ] **步骤 1：编写安装异常提示测试**

把页面使用的 `install_actions` 替换为抛出 `ActionInstallError("disk locked")`，断言 footer 包含错误且 `QMessageBox.warning` 收到同一原因；来源包仍保留。

- [ ] **步骤 2：运行测试确认当前实现只有 footer**

运行：`.venv\Scripts\python.exe -m pytest tests/test_action_import_page.py::test_action_import_page_shows_warning_when_install_fails -q`

预期：FAIL，warning 没有被调用。

- [ ] **步骤 3：实现磁盘错误和应用中状态**

捕获 `ActionInstallError`/`ActionPackError` 后同时更新 footer 与显示 warning。磁盘提交成功后只显示 `正在应用 N 个动作…` 并发出信号，不在页面内提前显示最终成功。

- [ ] **步骤 4：编写应用成功回调测试**

当前宠物重载成功和非当前宠物提交成功时，断言统一窗口的 `complete_action_install()` 被调用且 `QMessageBox.information` 显示目标宠物与动作数量；回滚路径断言不调用完成方法。

- [ ] **步骤 5：实现应用层最终通知**

添加应用私有方法生成成功消息、调用窗口完成方法并显示 information。只从当前宠物重载成功分支和非当前宠物完成分支调用。

### 任务 3：成功后清空导入表单

**文件：**
- 修改：`src/petnest/ui/action_import_page.py`
- 修改：`src/petnest/ui/pet_action_exchange_dialog.py`
- 测试：`tests/test_action_import_page.py`
- 测试：`tests/test_pet_action_exchange_dialog.py`

- [ ] **步骤 1：编写表单重置失败测试**

加载来源并选择动作后调用 `complete_install("已导入 2 个动作到平安。")`，断言：

```python
assert page._pack is None
assert page.source_input.text() == ""
assert page.source_kind_label.text() == "尚未读取来源"
assert page.action_list.count() == 0
assert page.conflict_table.rowCount() == 0
assert not page.import_bindings.isChecked()
assert page.target_combo.currentData() == selected_target
assert page.footer_state().status == "已导入 2 个动作到平安。"
assert not page.footer_state().primary_enabled
```

- [ ] **步骤 2：运行测试确认完成方法尚不存在**

运行：`.venv\Scripts\python.exe -m pytest tests/test_action_import_page.py::test_action_import_page_clears_source_after_apply_success -q`

预期：FAIL，`complete_install` 不存在。

- [ ] **步骤 3：实现页面与窗口完成方法**

页面先调用现有 `_close_pack()` 释放临时来源，再清空来源控件、列表、冲突表和绑定选项，最后保存成功状态并同步 footer。窗口方法只转发给页面。

- [ ] **步骤 4：运行定向测试**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_action_import_page.py tests/test_action_export_page.py tests/test_animation_editor_page.py tests/test_pet_action_exchange_dialog.py tests/test_pet_action_exchange_app.py -q
```

预期：全部 PASS。

### 任务 4：完整验证与运行时更新

**文件：**
- 检查本计划涉及的全部源码和测试。

- [ ] **步骤 1：运行完整测试**

运行：`.venv\Scripts\python.exe -m pytest -q`

预期：零失败；只允许既有 Windows 符号链接权限 skip。

- [ ] **步骤 2：检查差异和工作区**

运行：`git diff --check`、`git status --short --untracked-files=no`，确认没有带入无关素材。

- [ ] **步骤 3：重启 PetNest**

结束当前由项目虚拟环境运行的 PetNest 父子进程，使用 `PYTHONPATH=src` 和隐藏窗口重新启动，确认日志出现新的“PetNest 已启动，宠物包：pingan”且无新 ERROR/CRITICAL。

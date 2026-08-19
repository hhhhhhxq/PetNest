# 下班动画 drag 回退实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 执行此计划。

**目标：** 专属下班动作对缺失时，将进入阶段回退顺序改为 `walk → drag → idle`。

**架构：** 只修改纯函数 `resolve_work_finish_animation()` 的普通宠物动作选择链；专属动作成对规则及躺下回退保持不变。

**技术栈：** Python 3.12、pytest。

---

### 任务 1：增加 drag 回退

**文件：**
- 修改：`src/petnest/core/work_finish_animation.py`
- 测试：`tests/test_work_finish_animation.py`

- [ ] **步骤 1：编写失败测试**

构造无 `walk`、有普通 `drag` 的宠物包，断言 `resolved.walk.name == "drag"`；另测同时存在 `walk` 与 `drag` 时优先 `walk`，`fullscreen drag` 不进入普通回退。

- [ ] **步骤 2：验证红灯**

运行：`.venv\Scripts\python.exe -m pytest tests/test_work_finish_animation.py -q`

预期：无 `walk` 时当前实现返回 `idle`，新增测试失败。

- [ ] **步骤 3：最小实现**

```python
_pet_action(package, "walk") or _pet_action(package, "drag") or idle
```

- [ ] **步骤 4：验证绿灯与完整测试**

运行：`.venv\Scripts\python.exe -m pytest tests/test_work_finish_animation.py -q`，随后运行 `.venv\Scripts\python.exe -m pytest -q`。

- [ ] **步骤 5：合并提交**

将规格、计划、源码和测试加入暂存区，使用 `git commit --amend` 合并到最新提交，不纳入 `build_windows.bat` 或 `tests/test_installer_script.py`。

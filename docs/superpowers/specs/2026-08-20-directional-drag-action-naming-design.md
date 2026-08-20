# 方向拖动动作命名与资源迁移设计

## 目标

Codex 图集的 `running-right` 与 `running-left` 行在 PetNest 中统一表示拖动方向动作，分别命名为 `drag_right` 与 `drag_left`。不再生成来源型名称 `codex_running_left`，并修正线上资源库中已有的错误命名。

## 运行时模型

- 新导入：`running-right → drag_right`，`running-left → drag_left`。
- 宠物包继续绑定 `mouse.drag_start → drag`，并声明 `drag → drag_right → drag_left → idle` 回退，使方向尚未确定时也有安全动作。
- 实际移动时继续按当前水平增量选择 `drag_left / walk_left` 或 `drag_right / walk_right`，再回退到通用 `drag / walk / idle`。
- 为本机已经安装的旧包保留一个只读兼容候选：向左拖动时若没有 `drag_left`，可读取 `codex_running_left`。新导入和线上资源不再写出旧名。
- 普通 `drag`、`walk_left/right` 属于合法自定义命名，不批量改写。

## 受影响调用方

- 精灵图导入器与导入页面：展示并生成对称名称，元数据同步更新。
- 下班动画普通动作回退：在 `walk`、`drag` 不存在时允许使用 `drag_right`，最后才考虑 `drag_left` 与 `idle`。
- 商店目录能力检测：绑定目标不存在但 fallback 能解析到方向拖动动作时，仍声明 `drag` 能力。

## 资源迁移

扫描 `F:\Desktop Projects\petnest-resources-work\store\pets\*\package.zip` 的目录名、`animations`、路径、bindings、fallbacks 与导入元数据。仅迁移精确旧名和由 Codex 图集产生的通用右向 `drag`：

- `desk-nap-cat`
- `joker-bear-plush`
- `lulu`
- `miffy`

这四个源包执行：

- `drag → drag_right`
- `codex_running_left → drag_left`
- `mouse.drag_start` 保持抽象目标 `drag`
- 添加或更新 `drag: [drag_right, drag_left, idle]`
- 同步 `import_metadata.selected_columns_by_action`

`miffy` 还来自更早的旧映射，额外执行：

- 原 row 4 `drop → hover`
- 原 row 8 `hover → review`
- 删除 `mouse.drag_end` 绑定
- `agent.success → review`
- `success` fallback 改为 `review`

`lulu` 的 V2 环视资源同时规范化为单一数据集合：

- 删除普通动画 `look_directions_a/b`
- 合并为非循环动作 `look_directions`
- `001–008` 保持 row 9 的 `000°–157.5°`
- `009–016` 接续 row 10 的 `180°–337.5°`
- 导入元数据仍保留 A/B 两行的格位选择，供来源追踪与手动导入界面使用

通过资源仓库的确定性发布工具重新生成 ZIP、封面和 idle 预览，随后重建 `store/catalog.json`。未命中错误名称的商品保持字节不变。

## 安全边界

- 不覆盖 PetNest 工作区中与本任务无关的现有修改。
- 不修改含义明确的 `walk_left/right`、手工 `drag` 或全屏动作。
- 资源仓库当前必须为干净 `main`；提交前再次验证 diff 仅包含目标商品、目录工具测试和 catalog。
- 推送前运行两仓库相关测试、完整资源仓库测试、包校验、ZIP 命名扫描和 `git diff --check`。
- 只推送资源仓库；PetNest 主仓库代码在本地提交，不擅自推送。

## 不在本次范围

16 向角度选帧仍需要独立观察目标与渲染覆盖机制。本次先把资源与导入输出规范化为一个 `look_directions` 文件夹，但不宣称已经完成 Codex v2 环视运行时功能。

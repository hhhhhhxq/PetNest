# 下班动画进入阶段增加 drag 回退设计

## 背景

当前下班提醒只有在 `work_finish_walk` 与 `work_finish_lie_down` 同时存在且均为 `fullscreen` 时才使用专属动作。专属动作对缺失或不完整时，进入阶段只按 `walk → idle` 回退。Codex 8×9 精灵图导入器不会生成 `walk`，而是把 `running-right` 行映射为普通宠物动作 `drag`，导致这类宠物的进入阶段直接使用 `idle`，浪费了已有的移动帧。

## 目标行为

- 保持完整专属动作对的最高优先级和成对要求不变。
- 专属动作对缺失或不完整时，进入阶段按 `walk → drag → idle` 选择普通 `pet` 动作。
- 躺下阶段保持 `sleep → idle`，不使用 `drop`。
- 只有 `scope == "pet"` 的普通 `walk`、`drag`、`idle` 可以进入普通回退链；同名 `fullscreen` 动作不参与。
- 不修改宠物包格式、精灵图行映射、事件绑定或动作导入流程。

## 选择规则

```text
if work_finish_walk 与 work_finish_lie_down 都存在且均为 fullscreen:
    进入 = work_finish_walk
    躺下 = work_finish_lie_down
else:
    进入 = 第一个存在的 pet 动作：walk、drag、idle
    躺下 = 第一个存在的 pet 动作：sleep、idle
```

如果包无有效 `idle` 且其它候选也不存在，对应阶段保持 `None`；合法 PetNest 宠物包本身要求存在 `idle`，因此正常包不会走到这一损坏包边界。

## 测试

- 同时存在普通 `walk` 和 `drag` 时优先 `walk`。
- 缺少普通 `walk`、存在普通 `drag` 时使用 `drag`。
- `drag` 为 `fullscreen` 时跳过并回退 `idle`。
- 专属全屏动作对完整时继续优先使用专属动作，不受普通 `drag` 影响。
- 专属动作对不完整时忽略残缺专属动作，并进入普通 `walk → drag → idle` 回退。

# 精灵图导入设计

PetNest 新增一个本地精灵图导入器，用于将 Codex 标准 `8 × 9` PNG 图集转换为独立、可编辑的 PetNest 宠物包。输入不会上传或联网；导入器只读取用户在本机选择的 PNG，并在 `pets/<pet-id>/` 创建新包。

导入器只接受带 alpha 通道、尺寸为 `1536 × 1872` 的 PNG；它按 `192 × 208` 网格裁出每行 8 帧。默认映射为：idle→idle、running-right→drag、running-left→codex_running_left、waving→click、jumping→drop、failed→error、waiting→waiting、running→working、review→hover。缺少的 success 动作通过 pet.json fallback 回到 idle。

核心 `SpriteSheetImporter` 负责校验、无覆盖地写入帧、生成 `pet.json` 和预览图。命令行工具适合自动化；托盘菜单的“导入精灵图”打开本地文件对话框，预先显示规则与动作映射，确认后导入、扫描并切换到新宠物。

所有导入失败均保留原包和既有宠物。临时目录只在验证成功后改名为最终包目录。

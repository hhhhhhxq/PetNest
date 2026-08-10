# 线上资源仓库与同步实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 executing-plans 在隔离 worktree 中逐任务实现此计划。步骤使用复选框跟踪进度。

**目标：** 将 PetNest 当前的光标、互动动效和倒计时背景发布到私有 `petnest-resources` 仓库，并让 Worker 暴露可匿名读取的资源索引与文件内容；客户端保留本地资源作为离线兜底。

**架构：** 私有资源仓库保存最终可下发的文件和 `manifest.json`，不保存 GitHub Token。Cloudflare Worker 通过服务端 Secret 读取私有仓库并代理 `/v1/manifest.json` 与 `/v1/files/*`。PetNest 后续通过 manifest 下载并缓存资源；所有代码工作在本 worktree，当前主工作区的未提交改动保持不动。

**技术栈：** Python 3.12+、现有 PySide6 应用、GitHub Contents API、Cloudflare Workers JavaScript、SHA-256 校验。

**工作目录：** PetNest 实现分支为 `F:/Desktop Projects/PetNest-resource-sync`；资源仓库暂存克隆为 `F:/Desktop Projects/petnest-resources-work`。

---

### 任务 1：建立资源仓库发布结构

**文件：**
- 创建：`F:/Desktop Projects/petnest-resources-work/manifest.json`
- 创建：`F:/Desktop Projects/petnest-resources-work/tools/build_manifest.py`
- 修改：`F:/Desktop Projects/petnest-resources-work/README.md`
- 复制：当前工作区 `assets/cursors/**`、`assets/countdown/**`、`effects/**` 到资源仓库 `resources/**`

- [x] 从当前 PetNest 工作区收集最终资源，保留现有主题目录和动效目录格式。
- [x] 生成类型化 manifest：每个资源包含 `id`、`type`、`version`、`files`、`sha256`，路径统一使用 POSIX 分隔符。
- [x] 使用脚本校验每个资源的元数据和文件存在性。
- [x] 运行 `python tools/build_manifest.py --root . --catalog-version 2026.8.11`，确认 manifest 可重复生成且无路径穿越。

### 任务 2：完成 Worker 的可重复源代码

**文件：**
- 创建：`F:/Desktop Projects/PetNest-resource-sync/worker/src/index.js`
- 创建：`F:/Desktop Projects/PetNest-resource-sync/worker/README.md`

- [x] 将当前 Cloudflare Dashboard 中已验证的 Worker 代码保存到仓库镜像，配置 `OWNER`、`REPO`、`BRANCH` 常量。
- [x] 保持 Token 只从 `env.GITHUB_TOKEN` 读取，不写入源文件。
- [x] 覆盖根路径、manifest 路径、资源文件路径、非法路径和缺少 Secret 的响应。
- [x] 用本地 Node.js 语法检查验证脚本可解析。

### 任务 3：实现客户端资源协议与本地缓存

**文件：**
- 创建：`F:/Desktop Projects/PetNest-resource-sync/src/petnest/core/remote_resource_manifest.py`
- 创建：`F:/Desktop Projects/PetNest-resource-sync/src/petnest/core/remote_resource_cache.py`
- 创建：`F:/Desktop Projects/PetNest-resource-sync/tests/test_remote_resource_manifest.py`
- 创建：`F:/Desktop Projects/PetNest-resource-sync/tests/test_remote_resource_cache.py`

- [x] 解析 manifest 并拒绝未知 schema、绝对路径、`..` 路径、重复资源 ID 和 SHA-256 格式错误。
- [x] 使用临时文件下载、校验 SHA-256、原子替换，网络失败时保留上一份缓存。
- [x] 为 cursor/effect/countdown 三类资源提供统一文件映射接口；不在此任务改动主应用启动流程。
- [x] 先写失败测试，再实现最小代码，运行新增测试和全量相关测试。

### 任务 4：发布资源并验证 Worker

**文件：**
- 修改：私有 GitHub 仓库 `hhhhhhxq/petnest-resources` 的资源文件、manifest 和 README

- [x] 将任务 1 生成的资源提交并推送到私有仓库。
- [ ] 通过 Worker URL 请求 `/v1/manifest.json` 和至少一个 cursor、effect、countdown 文件（需要当前 Worker 的准确公开 URL）。
- [ ] 对返回内容重新计算 SHA-256，与 manifest 中记录一致。
- [x] 不把 Token、`.env`、Cloudflare Account ID 或本地临时文件提交。

---

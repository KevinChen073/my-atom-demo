# MVP1 落地映射

状态：本地 MVP1 实现说明，2026-10-31。范围依 [PRD](PRD.md) 与 [系统架构](ARCHITECTURE.md)；界面依据 [MVP1-UI](MVP1-UI.md)，冲突遵循 [ADR-002](decisions/ADR-002-change-control.md)。运行步骤见仓库 [README](../README.md)。本页描述已实现的代码，不把 Atoms 平台兼容性视为实测事实。

2026-11-01 范围变更提示：[ADR-006](decisions/ADR-006-single-main-run-scope.md) 将目标收束为单次主线；[ADR-010](decisions/ADR-010-structured-card-single-send.md) 将等待态改为结构化卡片与底部单一发送；[ADR-013](decisions/ADR-013-source-validation-targeted-repair.md) 将源码校验纳入定向文件修复回路。未列出的 MVP2 能力以 [系统架构](ARCHITECTURE.md) 为准。

## 主流程

| 阶段 | 实现与持久点 |
| --- | --- |
| Intake | FastAPI 校验访客身份、需求长度与项目内单活动运行；SQLite 生成 run、`trace_id` 和首个事件。 |
| Clarify / WaitClarify | 模型输出最多三题的澄清卡；LangGraph `interrupt()` 等待。答案须逐题明确提交；修改原需求会重跑 Clarify，旧 `card_id/spec_version` 失效。 |
| Plan / WaitPlan | 模型生成有页面、功能、数据、验收点及限制的计划卡；对浏览器存储等超出 MVP1 执行边界的实现项重生成，避免批准无法构建的计划。用户可提交修改意见生成新版计划，或回到澄清。只有服务端记录 `approved_spec_version` 后进入文件写入。 |
| Prepare / CodeLoop / ValidateSource | 幂等复制固定 React+TS+Vite 模板。模型每轮只返回一份候选；首次生成完整文件映射，反馈能定位文件时只返回该文件，不能定位时全量重生。校验节点记录受控问题、反馈、文件和候选缓存引用；合并后的整份候选通过校验才原子写入工作区。 |
| BuildTest / Diagnose | 实际执行 `npm ci --ignore-scripts` 与 `npm run build`（包含 `tsc -b`）；超时或取消会停止子进程。构建诊断能定位生成文件时只让模型重生该文件。源码校验与构建共用最多 60 轮自动修复、无进展和重复错误停机规则。命令退出码、时长、日志与失败诊断保留。 |
| PackageCandidate / PreviewCheck / CommitVersion / NeedsUser | 构建通过后先保存候选并检查入口和静态预览资源，再原子提交可用版本与 manifest；失败候选不占 5 版额度。源码或构建自动修复停机时展示小结及人工动作。 |

LangGraph `thread_id=run_id`，使用 SQLite checkpointer；项目、决策、事件和模型输出分别保存在应用 SQLite 表。事件有逐 run 单调 `seq`，网页轮询 `after_seq` 增量补齐并按序去重。服务重启会恢复进行中的 run；人工确认、文件写入和版本保存另有幂等门禁，避免把 checkpoint 当作唯一去重手段。

## Harness 与本地边界

- `ModelGateway` 从服务器 `.env` 读取 `MODEL_API_KEY`，使用 OpenAI 兼容 SDK 和可配置的 DeepSeek 模型地址；澄清/计划默认 high 思考，代码输出默认非思考模式（`MODEL_CODE_REASONING_EFFORT=none`）。每个阶段缓存结构化输出；截断时有界增加输出上限，超时、429、5xx 有界退避重试。单 run 限模型调用次数、token 和时长；服务无用量字段时保守计数。响应事件只记录 `finish_reason`、用量、长度和配置，不记录正文或推理内容。
- 2026-11-01 时长计费按 [ADR-007](decisions/ADR-007-active-execution-budget.md) 改为累计 Agent 执行时间。工作线程领取任务时开启，等待用户后暂停；累计秒数与执行心跳写入 SQLite，重启后不把离线时间算入。旧 run 的执行时间为未知，不能由创建/异常时间反推。
- 工具权限由固定节点决定：澄清/计划不能写生成文件；CodeLoop 只请求允许范围内的候选，ValidateSource 校验后才写工作区；BuildTest 只运行固定命令。模型只收到受控问题与定向文件反馈，不会收到 `.env`。
- `LocalRunner` 与宿主共用执行环境，仅用于本机可信测试。生成源码限制是防误用措施，不能替代沙箱。`APP_ENV` 非 `local` 时拒绝运行此 Runner。
- 当前 CodeLoop 是**最小受控循环**：源码校验修正与构建失败回退；没有按计划任务逐项自主选工具的通用编码 Agent。候选原文在受控缓存，LangGraph checkpoint 只持久化引用、反馈与修复计数。若后续扩展工具集合与逐任务循环，应依系统架构的 allowlist、预算和 checkpoint 约束实现并补 TC。

## MVP1 验收边界

已实现项目恢复、真实模型生成、固定模板构建、结果卡、源码版本与失败反馈。MVP1 不提供隔离交互预览、生成应用自身业务数据持久化、SSE 或公开发布；这些仍是 [PRD §6](PRD.md#6-分期与验收) 的后续验收条件。确定性 TC 在 [MVP1 用例](../tests/cases/MVP1.md)，本机执行记录在 `D:\AI\ATOM笔试\docs\MVP1-VERIFICATION.md`。

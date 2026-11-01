# ADR-010：结构化决策卡与底部单一发送

- 状态：Accepted（用户于 2026-11-01 指定按[交互讨论稿](../DESIGN-DISCUSSION-STRUCTURED-DECISION-SINGLE-SEND.md)修改；输入区位置与计划呈现已由 [ADR-011](ADR-011-decision-turn-composer.md) 修订）
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[MVP1 UI](../MVP1-UI.md)、[ADR-002](ADR-002-change-control.md)、[ADR-006](ADR-006-single-main-run-scope.md)、[ADR-008](ADR-008-manual-build-recovery.md)、[设计入口](../../design/design.md)、[TC](../../tests/cases/SINGLE-SEND.md)。

## 决定

澄清、计划与构建失败待处理卡只呈现当前事实、采集结构化答案或提供非提交导航。用户统一在对话底部按“发送”提交一条消息；不在卡内重复放确认、批准、修复或原样重建的提交按钮。发送记录包含原文、答案快照、当前 `card_id/spec_version`、消息 UUID 和幂等键。服务端先持久化消息，再异步解释，时间线显示原文、解释中状态与最终解释结果。旧卡可读但不能再提交。

解释器只处理**当前等待阶段**的回答、修改、提问与明确批准，不判断新建项目、sidecar 聊天或跨阶段回退。模型只能提出候选意图及答复，不能直接改变状态或调用生成工具。服务端确定性门禁规定：澄清必答项必须显式完成；需求修改优先于旧答案确认；计划修改优先于批准，问题或条件先回答；“可以”“确认”“继续”不能批准；只有明确指向当前计划且没有修改或未决问题的语句可设置 `approved_spec_version`。`Prepare` 继续二次核对批准版本。

构建失败只允许当前卡白名单内的单次修复、指定方向修复或原样重建。含糊“继续”及互斥动作混写不会执行。环境故障不能触发改码。每次人工动作保持 [ADR-008](ADR-008-manual-build-recovery.md) 的诊断和预算边界。

## 持久化与恢复

`POST /api/runs/{id}/messages` 先写 `submissions` 和事件，再返回 `202`。解释结果、最终决定、运行状态与事件在事务中落库；同消息键同载荷重放原结果，键与载荷冲突返回 409。`card_id/spec_version` 是乐观锁；卡片更新后旧消息不获执行。`GET /api/runs/{id}/messages` 和单条读取支持刷新/断线后对账；启动时恢复仍为 `interpreting` 的消息，已提交决定按既有 Graph/checkpoint 恢复。等待用户的时间不累计 Agent 执行预算。

未发送草稿只在当前浏览器会话保存，按项目、run、卡片及版本隔离。连接异常保留原文和原键供查询或重试；409 显示最新卡片及旧草稿，不自动迁移批准。正式工作台使用消息接口；旧 `/decisions` 暂留兼容测试和旧调用，后续移除需单独迁移。

## 对既有决策的修订

本 ADR 依据用户直接指向讨论稿的请求，按 [ADR-002](ADR-002-change-control.md) 视为确认。它替代 PRD、MVP1 UI 和 V7 Harness 中“卡内主确认按钮”“底部文字只作修改意见”“不做任何消息意图分类”的条款；保留 [ADR-006](ADR-006-single-main-run-scope.md) 的单 run、阶段上限、无全局意图路由及无跨阶段自动回退，也保留 [ADR-008](ADR-008-manual-build-recovery.md) 的修复白名单和诊断边界。

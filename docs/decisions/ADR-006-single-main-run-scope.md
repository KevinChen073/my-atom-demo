# ADR-006：单次主线交付范围

- 状态：Accepted（用户于 2026-11-01 明确限定）
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[ADR-002](ADR-002-change-control.md)。流程审查记录保存在本机 `D:\AI\ATOM笔试\docs\WORKFLOW-EDGE-NODE-REVIEW-2026-11-01.md`。

## 决定

当前 Agent 工作流只处理**一个简单需求在一个 run 内从澄清到可用交付物**的主线。先完成至少 1 次、最多 3 次的需求澄清（每次 1–3 题），再确认计划、生成代码、构建检查、预览检查和保存版本。澄清阶段内的补问、计划阶段内的修改，以及构建失败后的有限修复，仍属于本次 run 的局部循环。

当前不实现复杂需求驱动的跨阶段自动回退，也不判断一条新消息应新建内容、修改现有内容或进入 sidecar 聊天。计划阶段发现关键需求缺失、超出固定模板或发生范围冲突时，明确停止当前 run，向用户说明原因；用户重写需求后由确定性的新建命令启动新 run。完成交付后的迭代同样启动新 run，不在已结束的 Graph 上继续。交付物快照的“代码版本回滚”是独立的版本管理操作，不属于工作流阶段回退。

## Edge 边界

- 保留：`Clarify → WaitClarify → Clarify`（最多 3 张卡）、`Plan → WaitPlan → Plan`（仅修改同阶段计划）、`BuildTest → Diagnose → CodeAgent`（可修复错误且未达上限）。
- 移除目标图中的自动 `Plan/WaitPlan → Clarify`、`NeedsUser → Plan`，也不增加 `IntentRouter`、`SidecarChat` 或“新建/修改”语义分类 Node。
- 需求不完整、取消、预算停止和预览隔离失败结束当前 run。**构建失败**的人工定向恢复已由 [ADR-008](ADR-008-manual-build-recovery.md) 修订：保留候选与诊断，等待用户明确动作后可在同一 run 内再做一次构建或受限源码修复。

## 后续修订

[ADR-010](ADR-010-structured-card-single-send.md) 在用户确认后加入**当前阶段内**的消息解释层，专门把同一卡片的回答、修改、问题和明确批准映射到受限决定；这不增加本 ADR 排除的全局新建/修改/sidecar 路由，也不改变主 Graph 的跨阶段边界。

## 实施差距

2026-11-01 已移除计划卡 `return_to_clarification` 与 `WaitPlan → Clarify`；澄清卡限制为每 run 1–3 张、每张 1–3 道不重复问题，确认后由 `ClarityGate` 决定继续澄清或进入计划。历史事件仍可读取。当前澄清节点是结构化模型调用与校验的有界循环，不宣称已经实现任意工具型 ReAct。

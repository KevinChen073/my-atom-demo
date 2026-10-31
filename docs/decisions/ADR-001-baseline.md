# ADR-001：首版产品与技术基线

- 状态：Accepted（由用户在需求中指定）；日期：2026-10-30
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)；Spike 过程记录位于本机 `D:\AI\ATOM笔试\docs\ATOMS-SPIKES.md`

后续决定：[ADR-004](ADR-004-generated-deliverable-boundaries.md) 已将“生成交付物的业务数据存储与回滚”单独收敛到浏览器 `localStorage` 与最多 5 个可用快照；本 ADR 第 3 条的 SQLite 仅适用于 MYATOM 平台自身持久化，不再解释为生成应用的业务数据库。

## 背景

笔试要求真实可交互、持久化、可在线访问的 Atoms 类 Demo。时间和预算有限，目标是先做可验证的端到端纵向流程，再增加差异化表达。Atoms 的云运行细节尚未在目标账户验证。

## 决定

1. 固定 React + TypeScript + Vite Web 模板与 Python + LangGraph 单 Agent 主流程。
2. 核心门禁为需求澄清与 Build Plan 用户确认；UI 用预定义决策卡，暂不引入完整 A2UI/AG-UI。
3. 本地先使用本地服务与 SQLite，后续通过模型、存储、产物、Runner、Preview、密钥适配接口迁移。
4. 基础设施和隔离沙箱实现保持待定；先执行 Spike。无可信隔离时不公开运行生成代码。
5. MVP1–5 节奏、主题与记忆候选按 PRD 执行。

## 取舍与后果

固定模板降低生成不确定性和测试成本，但不能覆盖任意技术栈。单 Agent 便于追踪预算/恢复，但复杂任务可能更慢。轻量卡片缩短交付时间，后续扩展协议需要 schema 迁移。适配层带来少量前置设计成本，以换取平台不可用时可迁移；不承诺零迁移成本。

## 后续验证

执行 Atoms Spike 后，若证据要求改变这些决定，先按 [ADR-002](ADR-002-change-control.md) 征求用户确认，再增写新的 ADR 指向本记录，不静默重写历史。

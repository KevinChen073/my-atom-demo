# MYATOM 确定性文档

| 文档 | 内容 |
| --- | --- |
| [PRD](PRD.md) | 产品范围、核心流程、MVP 和验收 |
| [系统架构](ARCHITECTURE.md) | LangGraph、Harness、存储、预览和安全边界 |
| [MVP1 落地映射](MVP1-IMPLEMENTATION.md) | 当前代码实现、节点持久点与未实现边界 |
| [MVP1 界面设计](MVP1-UI.md) | 工作台、决策卡与恢复交互 |
| [MVP2 落地映射](MVP2-IMPLEMENTATION.md) | 实时事件、预览票据与受控业务数据 |
| [MVP2 界面设计](MVP2-UI.md) | 对话、按阶段出现的成果区、预览/代码与连接恢复 |
| [主工作台视觉方向 v2](WORKBENCH-V2.md) | 用户确认的对话 + 预览布局、项目状态导航与两张设计图 |
| [多项目界面设计](../design/README.md) | 6 个主页面、项目切换与跳转逻辑、Token 和页面示意图 |
| [ADR-001](decisions/ADR-001-baseline.md) | 已确定的技术与产品选择 |
| [ADR-002](decisions/ADR-002-change-control.md) | 与基线冲突的变更须先经用户确认 |
| [早期设计探索](DESIGN-STANDARD.md) | 视觉取舍、Token 与交互规范；布局以 v2 为准 |
| [ADR-003](decisions/ADR-003-desktop-only-builder.md) | MYATOM 建造工作台取消移动端适配 |
| [ADR-005](decisions/ADR-005-conversation-first-results.md) | 对话优先、隐藏内部过程记录及成果区渐进呈现 |
| [ADR-006](decisions/ADR-006-single-main-run-scope.md) | 一次简单需求的主线交付；不做复杂需求跨阶段回退或 sidecar 意图识别 |
| [ADR-007](decisions/ADR-007-active-execution-budget.md) | 15 分钟只累计 Agent 执行时间，等待用户与停机不计时 |
| [ADR-008](decisions/ADR-008-manual-build-recovery.md) | 构建失败小结、人工定向修复与历史检查点恢复 |
| [ADR-009](decisions/ADR-009-build-repair-harness.md) | 自动构建修复最多 60 轮及无进展、复现停机规则 |
| [ADR-010](decisions/ADR-010-structured-card-single-send.md) | 结构化卡片与单一发送、阶段内意图解释和确定性门禁 |
| [ADR-011](decisions/ADR-011-decision-turn-composer.md) | 当前卡与输入区同处一条对话、简要计划和键盘发送 |
| [ADR-012](decisions/ADR-012-user-facing-run-progress.md) | 长任务按真实节点更新进展、执行计时与完成后折叠 |
| [ADR-013](decisions/ADR-013-source-validation-targeted-repair.md) | 源码校验回路、按文件定向重生与共享修复预算 |
| [ADR-014](decisions/ADR-014-atoms-deployment-and-model-credentials.md) | 已选定 GitHub → Azure 公开交付路线，生产适配仍待验收 |
| [ADR-017](decisions/ADR-017-azure-persistent-state-and-artifacts.md) | Azure PostgreSQL 平台状态与 Blob 交付文件的持久化决定 |
| [Azure 持久化实施与迁移](AZURE-PERSISTENCE.md) | 数据归属、迁移顺序、故障对账与未验证边界 |
| [ADR-016](decisions/ADR-016-build-check-observability-and-recovery.md) | 构建检查逐轮打点、独立异常中心展示与模型输出失败后的显式恢复 |
| [Azure 部署验收](../tests/cases/DEPLOYMENT-AZURE.md) | 源码、容器、持久状态、隔离运行、预览及公开端到端闸门 |
| [单一发送 TC](../tests/cases/SINGLE-SEND.md) | 消息、并发、恢复与交互验收 |
| [长任务进展 TC](../tests/cases/RUN-PROGRESS.md) | 澄清轮次、计划/执行清单、计时与结果折叠 |

Atoms 官方资料整理与兼容性 Spike 是过程记录，位于本机 `D:\AI\ATOM笔试\docs`，不随本仓库分发。尚未实测的平台能力不能写为已支持；若实测推翻既有设计，依 ADR-002 处理。

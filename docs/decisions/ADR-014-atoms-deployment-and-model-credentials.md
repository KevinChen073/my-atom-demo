# ADR-014：GitHub 源部署、Atoms 迁移与模型凭证方案

> `atom-deploy` 分支例外：用户于 2026-11-01 另行确认受限 Atoms 适配，见 [ADR-018](ADR-018-atom-single-process-static-branch.md)。本 ADR 的 GitHub → Azure 主路线仍用于其他分支；这条 Atoms 分支不能据此被称为已上线。

- 状态：**Accepted（部署路线于 2026-11-01 经用户选择）**；尚未完成生产适配或 Azure 发布。
- 详细流程与验收：[GitHub 到 Atoms 部署方案](../ATOM-GITHUB-TO-DEPLOYMENT-PROPOSAL.md)。
- 受约束基线：[PRD](../PRD.md)、[系统架构](../ARCHITECTURE.md)、[ADR-001](ADR-001-baseline.md)、[ADR-002](ADR-002-change-control.md)、[ADR-004](ADR-004-generated-deliverable-boundaries.md)。
- 后续存储决定：[ADR-017](ADR-017-azure-persistent-state-and-artifacts.md) 已选 PostgreSQL 平台库和私有 Blob 交付文件；本 ADR 的路线选择继续有效。

## 背景

现有仓库的目标不是一般网站展示，而是 Python + LangGraph 单 Agent 真实生成代码、持久恢复、隔离运行和可操作预览。用户提供的 Atoms 当前答复不支持直接克隆已有仓库按原技术栈部署，只支持在平台能力内重建后 Publish。既有 Spike 的完整通过项仅 S0；开发环境 Python 路由的部分成功不足以推断原仓可发布。用户进一步询问以 GitHub 为代码源能否减少修改，并将模型范围收束为 DeepSeek 与 OpenAI 兼容 API。

## 决定

1. 本地 Git 仓库保持权威源，选择 **GitHub → Azure** 为 MYATOM 公开交付主路径；Azure Container Apps 是主 API 与独立服务的部署候选，持久数据库、产物存储、隔离 Runner 和预览网关仍需分别实现与验收。Atoms 仅保留为可选迁移研究，不作为本轮上线前置依赖。GitHub Pages 不能单独运行本项目。
2. 以现行 PRD 的真实闭环为发布目标。GitHub 源外部部署仍须完成生产数据库、隔离 Runner/预览和公开 URL 验收。Atoms 全部重建须通过导入、Python/LangGraph、可信 Runner 隔离和公开 URL 四道闸门。任何缩减真实生成/隔离验收的方案须另行获批。
3. 模型配置由主应用设置界面收集，默认 DeepSeek；后端只支持 DeepSeek 与 OpenAI 兼容 API，均走 OpenAI 风格客户端，按 provider 选择不同参数。暂不支持 Anthropic 原生 Messages API。模型、地址和预算在服务端校验；`MODEL_PROVIDER` 在当前 `.env.example` 中存在但未被当前代码读取，不能称为现成切换功能。
4. 按本次用户要求，API Key 可在前端**录入**，但不能由前端直接调用供应商或写入浏览器持久存储。首版为用户临时 Key，服务重启或中断后需要重新录入；运营者 Key 可在平台 Keys 中提供受限演示模式。若需访客自带 Key 跨请求自动恢复，须先验证身份隔离、服务端加密存储、撤销与恢复。

## 取舍与后果

- Atoms 全部重建的操作入口简洁，但目前无法证明 Runner 与公开端到端闭环；发布按钮本身不能解决安全隔离。
- 混合架构可保留 Atoms 工作台，但引入跨服务身份、稳定预览域名与运维成本；逐项验证后才决定。
- GitHub 源外部部署保持现有 Python/LangGraph 结构，迁移量较少，但仍需生产数据库、隔离 Runner、公开域名、费用控制和真实验收，不能将本地版本直接开放。
- ChatGPT Sites 可作为可公开访问的前端及轻量 Worker/D1/R2 层，但托管 Worker 不运行现有 Python/LangGraph，也不提供可信生成代码 Runner；完整 MYATOM 使用 Sites 仍要连接外部执行服务，增加跨服务集成。此项为插件能力核对，不代表已建站。
- 缩减为两类 OpenAI 风格 API 后无需维护 Anthropic Messages 适配器，但不同兼容服务的 JSON mode、思考参数与用量仍须逐项探测，不能仅更换 `base_url`。
- 访客自带 Key 减少运营者模型费用，却增加凭证生命周期、前端脚本安全、故障恢复和多用户隔离要求；首版临时使用并在中断后重新录入，运营者模式可补充受限演示。

## 实施闸门

用户已选择 GitHub → Azure 路线，不再以 Atoms Publish 作为上线门槛。实施仍以现行 PRD 的真实生成、持久恢复和隔离预览为准；先通过 [Azure 部署验收 TC](../../tests/cases/DEPLOYMENT-AZURE.md) 的容器、状态、Runner、凭证与公开端到端闸门，再把公开 URL 称作交付。选择路线不等于授权提交/推送未审查代码、创建云资源或公开运行当前同宿主 Runner；这些执行动作按 [根目录约束](../../AGENTS.md) 处理。

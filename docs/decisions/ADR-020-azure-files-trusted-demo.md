# ADR-020：Azure Files `data/` 与受信演示运行模式

- 状态：部分修订；数据库与 checkpoint 条款由 [ADR-021](ADR-021-azure-sql-platform-state.md) 修订，Azure Files、挂载门禁和文件恢复条款由 [ADR-023](ADR-023-azure-sql-text-artifacts.md) 取代；第 3/5 条的每项目独立预览域由 [ADR-026](ADR-026-shared-origin-project-storage.md) 取代（2026-11-01）。以下保留原决定供追溯；同容器构建与受信访问边界仍有效。
- 取代：[ADR-017](ADR-017-azure-persistent-state-and-artifacts.md) 中的 Blob 与隔离 Runner 方案
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[部署说明](../AZURE-PERSISTENCE.md)、[验收](../../tests/cases/DEPLOYMENT-AZURE.md)

## 决定

1. Azure 平台结构化数据继续使用 PostgreSQL Flexible Server：项目、run、事件、版本指针、预览票据、异常及 LangGraph checkpoint。新环境从空库开始，不迁入本地历史数据。
2. 一个 Azure Files 文件共享挂载到主 API 容器的 `/app/data`，通过 `MYATOM_DATA_DIR` 指向它。`artifacts/` 为可用版本源码与构建文件，`candidates/` 为待提交候选，`projects/` 为运行工作区，`npm-cache/` 为缓存。文件仍由服务端受控路径和项目权限访问。没有挂载时启动失败；容器自身可写层不承载权威文件。
3. 受信演示模式 `APP_ENV=azure_demo` 在主 API 容器运行固定 React + TypeScript + Vite 模板的源码校验和构建。容器须提供 Node/npm；单副本、单 API 工作进程。工作台和预览共用 8000 端口，依 Host 路由区分；预览使用每项目稳定的 `p-<uuid>.<PREVIEW_BASE_DOMAIN>` HTTPS origin，避免跨项目共享 `localStorage`。
4. 此模式**不是代码执行沙箱**。生成代码与持有数据库连接及模型密钥的 API 同容器，进程环境清理、源码限制、资源/时间上限只能减小风险，不能证明隔离。必须把 Azure 入口限制为受信人员（Container Apps 身份认证或 IP 允许列表），并验证限制实际生效；不得把此模式面向匿名公网用户开放。评审测试链接须附授权访问方式。要开放任意访客生成，必须另做隔离 Runner 与安全验收。
5. `APP_ENV=container_smoke` 仍只开放健康检查；`APP_ENV=azure_demo` 须显式设置 `MYATOM_TRUSTED_DEMO=1`、PostgreSQL URL、HTTPS 工作台 origin、独立预览域且检测到 `data/` 为挂载点，否则拒绝启动。`APP_ENV=production` 仍拒绝启动。模型密钥只来自服务端密钥配置。

## 提交与恢复

候选在挂载卷内写入，完成构建和静态探针后原子更名为 `artifacts/<project>/<run>`，再在 PostgreSQL 事务中提交版本及当前指针。文件写入或数据库提交失败时不得改动旧版指针；未引用目录通过清理账本重试。Azure Files 与 PostgreSQL 没有跨服务原子事务，需在真实 Azure 测试域注入中断并核对 hash、版本指针和恢复行为。多副本/多工作进程、共享卷并发和公网代码执行不在本次受信演示范围。

## 取舍

该决定减少 Blob SDK 和独立 Runner 的接线工作，但把生成代码执行风险留在主容器。Azure Files 仍是独立的持久云文件服务，不等同于容器临时磁盘；挂载、权限、费用和重启读回需要实际验证。[Container Apps 存储说明](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)将容器文件系统列为临时、Azure Files 列为持久。历史 `BlobArtifactStore` 代码仅作未接线研究，不参与此路线。

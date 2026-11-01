# ADR-017：Azure 平台状态与交付文件的持久化边界

- 状态：Superseded by [ADR-020](ADR-020-azure-files-trusted-demo.md)（2026-11-01，用户明确改选 Azure Files `data/` 与主 API 容器内构建）。以下保留原方案供追溯，不再作为当前实施依据。
- 关联：[PRD](../PRD.md#5-持久化与版本)、[架构](../ARCHITECTURE.md)、[ADR-004](ADR-004-generated-deliverable-boundaries.md)、[ADR-014](ADR-014-atoms-deployment-and-model-credentials.md)、[实施与迁移](../AZURE-PERSISTENCE.md)、[验收](../../tests/cases/DEPLOYMENT-AZURE.md)

## 背景

本地 MYATOM 用三个 SQLite 文件保存平台状态、LangGraph checkpoint 与预览票据，用 `data/` 目录保存工作区和交付文件。Azure Container Apps 容器文件系统是临时的；把当前启用 WAL 的 SQLite 直接放在 Azure Files 网络挂载上不满足多实例与可靠恢复要求。[Container Apps 存储说明](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)与 [SQLite WAL 约束](https://sqlite.org/wal.html)分别说明容器临时存储的生命周期和 WAL 的同主机要求。

## 决定

1. Azure 生产平台状态以 **Azure Database for PostgreSQL Flexible Server** 为权威库。项目、run、用户决定、事件、幂等账本、版本指针、异常及构建检查、预览会话共用同一服务的受控 schema；LangGraph 改用 PostgreSQL checkpointer。主 API 有读写权限，独立异常后台仅有必要表/视图的读取权限。数据库 schema 迁移在部署阶段显式执行，不由多个 API 副本同时启动迁移。
2. **Azure Blob Storage 私有容器**保存不可变交付快照：源码、模板/依赖锁、构建产物、manifest 与必要的诊断文件。隔离 Runner 的构建工作区和候选目录是临时文件；通过构建与静态预览检查后先上传完整候选、核对 hash，再提交 PostgreSQL 中的 `versions` 和 `active_version_id`。数据库事务失败时保留旧版；未引用的 Blob 由定期清理处理。数据库先删除版本元数据，产物清理进入持久队列，清理可重试。
3. Blob key 由受校验的项目 ID、run ID、内容 digest 和相对路径构成；容器不公开。预览网关经版本权限检查后读取 Blob，不把存储凭证或原始 Blob URL交给生成应用。Blob 访问优先使用 Container Apps 托管身份与最小 RBAC；数据库连接及模型密钥由服务端密钥配置提供，不进代码仓库、浏览器、生成项目或日志。
4. 本地模式继续使用 SQLite 与本地文件，生成应用的**业务数据**继续使用其独立预览 origin 的 `localStorage`。平台数据库和 Blob 只保存 MYATOM 平台状态及交付代码；不改变 [ADR-004](ADR-004-generated-deliverable-boundaries.md) 的业务数据边界。
   Azure 作为独立新环境从空库和空 Blob 容器开始；按用户 2026-11-01 的决定，不迁入本地历史项目、运行、checkpoint、版本或产物。本地旧数据保持原状。
5. 首个 Azure 测试域只允许一个主工作进程/副本，直到跨副本任务领取、续租与幂等恢复完成验收。生产适配未完成时继续拒绝 `APP_ENV=production`；不能把目前的 `container_smoke` 健康检查当作持久化通过。

## 取舍与失败处理

- 选择 PostgreSQL 是为了保留跨表事务、独立运维只读访问与持久 checkpoint。Azure Files 可保存一般文件，但不承载当前 SQLite WAL 数据库；不把容器临时盘当权威存储。[SQLite 网络文件系统说明](https://www.sqlite.org/useovernet.html)给出锁与同步风险。
- Blob 适合不可变版本文件，但数据库与 Blob 没有跨服务原子事务。因此使用“先上传并校验文件，后提交版本指针”的顺序；上传中断可幂等重试，孤儿文件可清理，任何失败都不得删除旧可用版。
- 持久数据库和对象存储会产生持续费用与网络配置工作；容量、备份、保留期和预算在创建资源前核对。没有 Azure 测试资源时，只能验证本地契约，不能宣布云端读回或恢复已通过。

## 验收出口

执行 [AZ-03](../../tests/cases/DEPLOYMENT-AZURE.md) 的项目、待决卡、checkpoint、事件、版本及文件跨实例读回；故障注入覆盖上传前后、数据库提交前后及旧版清理；执行 [AZ-07](../../tests/cases/DEPLOYMENT-AZURE.md) 的异常后台只读访问。全部证据同时包含数据库记录和 Blob 文件 hash，不能只测 `/api/health`。

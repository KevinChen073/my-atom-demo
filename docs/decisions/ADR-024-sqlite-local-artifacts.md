# ADR-024：本地交付版本也完整存入 SQLite

- 状态：Accepted（2026-11-01，按用户本轮明确要求）；线上版本文件继续遵守 [ADR-023](ADR-023-azure-sql-text-artifacts.md)。
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[Azure 持久化](../AZURE-PERSISTENCE.md)、[版本边界](ADR-004-generated-deliverable-boundaries.md)。

## 决定

本地平台项目、事件、运行和交付版本的源码、文本构建文件、manifest、当前指针均以 SQLite 为权威数据源；LangGraph checkpoint 和预览票据仍使用本地 SQLite 文件。线上上述持久状态统一进入 Azure SQL。两端的 `data/projects` 候选、构建目录和日志只是可删除的临时工作区，不作为可用版本的恢复依据；生成应用自己的业务数据继续位于预览 origin 的 `localStorage`。

本地 `version_files` 与 `versions`、当前指针、五版淘汰在同一 SQLite 事务中提交。读取预览、源码和迭代基线只走数据库。候选文件沿用 [ADR-023](ADR-023-azure-sql-text-artifacts.md) 的严格 UTF-8、路径、数量和体积上限。已存在的本地磁盘版本在首次打开本地库时按 manifest 校验并导入 SQLite；早期缺少 `build_files` 清单的版本，从原 `dist/` 文件计算清单再校验导入。原磁盘目录暂不自动删除，以免在核对前丢失旧备份；导入后应用不再依赖它们。原文件缺失或校验失败的旧版不能宣称可预览，需人工核对。

验收以删除临时/旧产物目录后重启仍可读源码、预览和回滚，以及部分文件校验失败时不移动当前版本指针为准。线上 Azure SQL 迁移和跨重启读回仍需实测。

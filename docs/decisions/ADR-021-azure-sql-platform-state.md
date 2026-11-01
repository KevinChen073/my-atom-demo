# ADR-021：Azure SQL 承载平台状态与 LangGraph checkpoint

- 状态：Accepted（2026-11-01；用户因成本选择复用现有 Azure SQL）
- 修订：[ADR-020](ADR-020-azure-files-trusted-demo.md) 第 1、5 条及其中的 PostgreSQL 事务描述；文件条款最终由 [ADR-023](ADR-023-azure-sql-text-artifacts.md) 修订，同容器构建和受信演示边界保留
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[部署说明](../AZURE-PERSISTENCE.md)、[验收](../../tests/cases/DEPLOYMENT-AZURE.md)

## 决定

1. Azure 受信演示复用**专用 Azure SQL Database**，保存项目、run、事件、待决决策、可用版本指针、预览票据、异常与构建检查，以及 LangGraph checkpoint 和 pending writes。Azure 从空库开始，不迁入本地历史。不得把已存在的非 MYATOM 业务表自动接管。
2. 主 API 使用 `MYATOM_AZURE_SQL_CONNECTION_STRING`；独立异常后台使用单独的 `OPS_AZURE_SQL_CONNECTION_STRING` 和只读数据库账号。后台账号仅可 `SELECT` 脱敏 `ops_*` 视图，不能读取业务表或写入。数据库连接串只放服务端密钥配置；强制加密并验证服务端证书。
3. 保留本地 SQLite 和本地可选 PostgreSQL 开发/回归路径，但 Azure 的 `azure_demo` 只接 Azure SQL，不以本地 SQLite 或 PostgreSQL 静默降级。Azure SQL schema 需显式执行 `python -m backend.migrate_azure_sql`；应用启动只验版本，不自动改表。
4. LangGraph 图的 Node/Edge 不变。Azure SQL saver 必须保持 checkpoint、parent、pending writes、写入幂等与重启恢复语义；不能用进程内记忆替代。驱动采用微软 `mssql-python`，每次事务独立连接，不跨线程共享连接。
5. 文件产物、候选、工作区和 npm 缓存继续放在挂载到 `/app/data` 的 Azure Files。成功构建先提交不可变文件，再由 Azure SQL 事务提交版本和当前指针。两服务没有跨服务原子事务；失败保留旧版，通过持久清理账本对账。

> 第 5 条为历史决定，现由 [ADR-023](ADR-023-azure-sql-text-artifacts.md) 取代：已提交版本文本进入 Azure SQL 同一事务，容器目录只保存临时构建文件。

## 成本与验收

复用已有 Azure SQL Database 可避免为 MYATOM 再开一套 PostgreSQL 服务；**不等于 Azure SQL 必然更便宜**，另建数据库也可能产生独立计算费用。上线前核对当前 SQL Database 的 SKU、计算层级及自动暂停状态、版本文本所增加的存储与备份、Container Apps 的实际账单和预算提醒。不得因节省数据库费用而把 checkpoint 放到临时容器盘。[微软成本模型](https://learn.microsoft.com/en-us/azure/azure-sql/database/cost-management)说明计算、存储和备份分别计费；具体金额用[当前订阅的定价计算器](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/pricing-calculator)与账单核对。

本仓单元/模拟测试只验证适配器语句和本地路径。Azure SQL 真实连接、schema、并发幂等、LangGraph 中断重启、读写权限、容器替换后恢复及成本必须在同一 Azure 测试域取得证据；未通过前只称部署候选，不能称在线可用。

参考：[微软 Python SQL 驱动](https://learn.microsoft.com/en-us/sql/connect/python/mssql-python/installation)、[LangGraph checkpointer 接口](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/checkpointers.mdx)、[Azure SQL 瞬时故障](https://learn.microsoft.com/en-us/azure/azure-sql/database/troubleshoot-common-connectivity-issues)。

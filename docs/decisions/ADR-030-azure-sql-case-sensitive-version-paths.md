# ADR-030：Azure SQL 版本文件路径区分大小写

- 状态：Accepted（2026-11-02，用户确认按线上问题 `2a393360-05b4-4978-818f-f1529cfd3eb7` 的排查方案修复）
- 关联：[ADR-023](ADR-023-azure-sql-text-artifacts.md)、[架构](../ARCHITECTURE.md)、[迁移与部署](../AZURE-PERSISTENCE.md)、[Azure 验收](../../tests/cases/DEPLOYMENT-AZURE.md)

## 证据

该 run 的源码校验、Vite 构建与静态预览检查均通过，在 `CommitVersion` 写 Azure SQL 时出现 `IntegrityError`，事务回滚，项目没有可用版本。候选包含 `src/app.css` 和 `src/App.css`。`version_files.relative_path` 继承数据库的 `SQL_Latin1_General_CP1_CI_AS` 排序规则，两条路径在 SQL 中相等；Linux 文件系统、Python manifest 与源码校验却把它们视为两个文件。

## 决定

1. Azure SQL schema v3 将 `version_files.relative_path` 改为 `Latin1_General_100_BIN2`，重建 `(version_id, relative_path)` 主键。原有版本文本与路径保持不变；新建库仍依次执行 v1、v2、v3。SQLite 路径规则不变。
2. 迁移必须由数据库 DDL 管理员显式执行，先核对现有 schema v2、备份与运行身份；应用身份不得获得长期 DDL 权限。迁移成功以 `MAX(version)=3`、列排序规则为 `Latin1_General_100_BIN2`、两种大小写路径可在同一版本中分别写入并精确读回为判定。应用启动只验 schema，不自动改表。
3. Azure SQL 文件提交的约束错误归为 `version_commit_failed`，工作台显示“版本保存失败”和受控原因，异常记录保留 Trace ID 与 `CommitVersion` 阶段，不展示原始 SQL 或文件内容。事务失败不产生可用版本。
4. 已失败 run 不因迁移而自动重放。未提交候选仅在当前容器临时目录中；需要另外设计受控恢复，或由用户开始新一轮。不得直接把旧失败 run 标为成功。

## 实施与验证

先提交并构建兼容 schema v3 的镜像，再由管理员在 Azure SQL 执行 v3 迁移；核对只读探针与事务内的大小写路径写读冒烟，最后切换容器修订并复测工作台。若迁移失败，不切换至要求 v3 的镜像。真实模型从需求到交付的端到端验收仍单独记录。

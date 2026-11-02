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

2026-11-02 已提交并构建兼容 schema v3 的镜像；管理员在 `my-atom-dev` 执行 v3 迁移，读回 schema `3`、BIN2 列与主键。事务内同版写入两种大小写路径并精确读回，回滚后未留下测试版本。容器修订 `myatom-azure-check--0000012` 已使用镜像 `smoke-37f5fd33b4de117712d0c94ed808c9aab0ded9a9`；线上健康接口、首页和历史项目读回正常。真实模型从需求到交付、版本回滚及重启恢复仍按 [Azure TC AZ-03](../../tests/cases/DEPLOYMENT-AZURE.md) 单独验收。

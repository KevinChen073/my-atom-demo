# Azure 受信演示环境：Azure SQL 保存平台状态与版本文本

数据库决定见 [ADR-021](decisions/ADR-021-azure-sql-platform-state.md)，版本文本存储设计见 [ADR-023](decisions/ADR-023-azure-sql-text-artifacts.md)，同容器受信执行边界见 [ADR-020](decisions/ADR-020-azure-files-trusted-demo.md)，共享预览 origin 目标见 [ADR-026](decisions/ADR-026-shared-origin-project-storage.md)。产品边界见 [PRD](PRD.md)，验收见 [Azure TC](../tests/cases/DEPLOYMENT-AZURE.md)。本地与 Azure 是独立数据环境；Azure 从专用空库与空容器目录开始，**不搬迁本地历史项目、checkpoint、版本或文件**。schema v2 与版本文件读写已在本仓接线；用户确认 Azure SQL 已迁移 v2，旧镜像已在 Azure 健康模式运行。2026-11-01 容器内只读探针返回 `database=my-atom-dev`、`user=myatom-azure-check`、`schema_version=2`；写入、重启恢复与新镜像的完整工作台验收尚未完成。详见 [部署记录](AZURE-SMOKE-DEPLOY-2026-11-01.md)。

| 数据 | 本地 | Azure 受信演示 |
| --- | --- | --- |
| 项目、run、事件、版本指针、异常、预览票据 | SQLite | 现有 Azure SQL Database；schema v2 显式迁移 |
| LangGraph checkpoint 与 pending writes | SQLite | Azure SQL saver；重启后按 `thread_id` 读取 |
| 已提交源码、构建资源、manifest | SQLite `version_files` 与 `versions` | Azure SQL `version_files` 与 `versions`；重启读回待 Azure 实测 |
| 未提交候选、工作区、npm 缓存 | 本地 `data/` | 容器自身 `/app/data`；重启后可丢失，不算可用版本 |
| 生成应用业务数据 | 本地代码已实现工作台共享 origin 的 `localStorage`，键 `myatom.app.<项目 UUID>.*` | Azure 默认 HTTPS FQDN 同 origin 的 `localStorage` 与同一项目键前缀；不进入平台数据库，前缀不提供安全隔离，线上待验收 |

## 运行配置与门禁

- 用户提供的目标是资源组 `rg-myatom-quickstart`、SQL Server `my-atom.database.windows.net`，截图显示数据库 `my-atom`。这些是**待现场核对的资源信息**；尚未读取数据库层级、空库状态、网络规则、账号权限或账单。迁移脚本只接受专用空库或本仓已标记的 schema，不能直接对未知现有数据执行。
- `python -m backend.migrate_azure_sql` 将空库迁移到 schema v2，也允许**没有版本记录**的 v1 库升级；v1 若已有版本记录则拒绝升级，必须先完成文件受控导入。迁移命令只建 MYATOM 表和视图，**不会创建或购买 Azure SQL Database**。应用启动只检查 schema v2，不自动改表。已有任何用户表且未标记 MYATOM schema 的数据库会被拒绝，不能直接接管。容器运行身份只有读写权限，迁移须由数据库管理员单独执行，不能给运行身份长期加 `db_ddladmin`。
- `APP_ENV=azure_demo`、`MYATOM_TRUSTED_DEMO=1`、`MYATOM_AZURE_SQL_CONNECTION_STRING` 为服务端配置。SQL 连接要求 `Encrypt=yes;TrustServerCertificate=no`。Azure 模式不设置 `MYATOM_DATABASE_URL`。访客模型 Key 在工作台自行输入，Azure 只在当前页面会话内存保留、刷新后重填；服务器 Key 不下发。两类凭证均不得进仓库、日志或生成文件。见 [ADR-025](decisions/ADR-025-browser-model-settings.md)。
- `MYATOM_DATA_DIR=/app/data` 指向容器自带的可写目录；**不配置外部 volumeMount**。启动只验证目录可写。该目录只承载临时工作区、候选和缓存；可用版本的源文件与预览文件必须在 Azure SQL。若应用连接 Azure SQL 失败，不得降级到 SQLite。
- 目标配置 `WORKBENCH_ORIGIN=https://<Container App 默认 FQDN>`；预览使用该 origin 下的 `/preview/...`，不再配置 `PREVIEW_BASE_DOMAIN` 或 wildcard DNS/TLS。本地与 Azure 代码已改为共用工作台 origin；Azure 入口限制与在线验收仍为门禁。
- 主 API 和同容器构建仅 **1 副本、1 worker**。Ingress 必须通过身份认证或 IP 允许列表限制为受信人员，并实际拒绝未授权访问。该模式没有代码执行安全隔离；`APP_ENV=production` 仍拒绝启动。
- 启动检查 Azure SQL 配置、schema、HTTPS 域、受信开关和 `/app/data` 可写性。仅 `/api/health` 成功不代表构建或预览可用。

### 授权完成后的最小实测顺序

1. 在 `my-atom-dev` 查询编辑器只读核对 `sys.database_principals`，确认容器身份已存在且有预期角色；不要把门户登录成功当成容器连接成功。当前本轮门户查询编辑器的 `QueryEditor.ReactView` 加载失败，因此授权状态仍以用户报告为准。
2. 由数据库管理员在**专用测试库**执行 `backend/sql/azure_sql_v1.sql`、`backend/sql/azure_sql_v2.sql`，分别按 `GO` 分批；迁移前核对库为空，迁移后查 `SELECT MAX(version) FROM dbo.myatom_schema_version` 应为 `2`。`myatom-azure-check` 运行身份只有读写权限，不能以它执行 DDL。若 v1 库已有版本记录，先停止并做受控文件导入，不能直接运行 v2。
   若执行旧 v1 在 `checkpoint VARBINARY(MAX)` 处报语法错误，使用本仓已改为 `[checkpoint]` 的 v1 文件重新执行，勿手工删表。v1 各建表/索引语句按存在性检查设计，可在同一专用库上续跑；先核对 `SELECT MAX(version) FROM dbo.myatom_schema_version`，确认 v1 标记成功后再执行 v2。Python 自动迁移器会拒绝接管“已有部分表但没有版本标记”的库，此时应由管理员核对并续跑 v1，而不是清空已有数据。
3. 旧镜像的 Azure SQL 只读探针已返回 `database=my-atom-dev`、`user=myatom-azure-check`、`schema_version=2`。单 IP 防火墙规则依赖当前副本出口 IP，重建后须重新核对，不把旧探针结果当成新副本连通证明。
4. 在共享路径预览的代码迁移、模型 Key 风险处理和受信入口限制就绪后，才启动 `APP_ENV=azure_demo`，创建一个小应用，记录 `version_id`，替换容器副本并确认代码、预览、回滚与 checkpoint 均仍可读。真实结果按 [Azure TC](../tests/cases/DEPLOYMENT-AZURE.md)记录；目前尚未执行完整应用验收。

## 文件与版本顺序

`data/projects/<project>/<run>/workspace` 和 `data/candidates/<run>/<digest>` 位于容器临时目录。Runner 在主容器执行受限模板构建，不能视为沙箱。

源码检查 → 构建 → 候选静态资源探针 → 严格 UTF-8 读取受控文本文件并校验路径、大小、hash → **同一 Azure SQL 事务**保存版本、全部文件行、当前指针、事件与最多 5 版清理。数据库提交失败保留旧版；候选目录失败不产生可用版本。预览网关、代码视图和迭代 Prepare 直接按版本从 SQL 读文件；容器重启后不依赖本地目录恢复旧版。未完成的候选在重启后可能丢失，须明确诊断或重建，不能冒充已交付版本。生成应用业务 `localStorage` 不随代码回滚。

## 数据库登录与密码

2026-11-01 门户只读核对：SQL Server `my-atom` 已将当前门户账号设为 Microsoft Entra 管理员，并启用了**仅 Entra 身份验证**；服务器下已有 `my-atom` 和 `my-atom-dev` 数据库。当前配置禁用 SQL 管理员及 SQL 用户密码登录，因此重置 SQL 管理员密码不能解决本轮 Entra 交互登录错误。[微软 Entra 配置说明](https://learn.microsoft.com/en-us/azure/azure-sql/database/authentication-aad-configure)。

已在 SQL Database `my-atom-dev` 的门户查询编辑器以当前账号执行只读 `SELECT DB_NAME(), SUSER_SNAME(), USER_NAME()`，返回数据库 `my-atom-dev`、外部 Microsoft 账号登录和 `dbo`。这证明门户自身的登录路径可访问该数据库，不证明本机 `mssql-python` 的认证路径可用。[微软查询编辑器](https://learn.microsoft.com/en-us/azure/azure-sql/database/connect-query-portal)。凭证或令牌不得发到聊天、写入仓库或日志。

本机 Windows 的 `mssql-python` 在 `Authentication=ActiveDirectoryInteractive` 下会走 ODBC 交互登录。明确 `UID` 后仍出现 `FA004 / 0x534 / state 11`；改用 `ActiveDirectoryDeviceCode` 时，登录应用以 `AADSTS500200` 拒绝当前个人 Microsoft 账号。租户用户资料显示该账号是 B2B 外部身份，虽然门户查询编辑器能以该账号连接，驱动使用的登录应用仍不能完成认证。因此本机直连写入测试暂时 **Blocked**；不要继续重试个人账号设备码，也不要把此问题当作 SQL schema/权限失败。[微软 ODBC 交互登录说明](https://learn.microsoft.com/en-us/sql/connect/odbc/using-azure-active-directory)、[微软 Entra 错误码](https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes)。

Azure Container App `myatom-azure-check` 的系统分配托管身份已启用；容器连接串使用 `Authentication=ActiveDirectoryMSI`。在 `azure_demo` 模式下，在线创建项目后通过详情与列表接口读回，确认该身份可执行至少这组数据库写读操作。Azure SQL 防火墙规则当前仅允许容器的单个出口 IP；出口 IP 变化会再次阻断连接。交付物版本文件读写、容器重建后恢复与异常后台只读授权尚未在线验证。本机直连用例若仍需运行，则须改用该租户可登录的组织账号。[实测记录](AZURE-SMOKE-DEPLOY-2026-11-01.md)、[Container Apps 托管身份](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity)、[Azure SQL 创建 Entra 用户](https://learn.microsoft.com/en-us/azure/azure-sql/database/authentication-aad-configure)。

## 证据与待验

- 历史 [PostgreSQL CI](https://github.com/KevinChen073/my-atom-demo/actions/runs/41297467225)只证明旧适配器，不证明 Azure SQL。Azure SQL schema、LangGraph checkpoint/待决卡恢复、预览票据、异常后台只读权限和并发幂等需重新实测。
- 历史 [镜像 CI](https://github.com/KevinChen073/my-atom-demo/actions/runs/41298422604)只证明旧镜像默认健康模式。新镜像、SQL 文件存储、同容器构建、HTTPS 预览、容器重启后从 SQL 读回和访问限制，均按 [AZ-01～AZ-08](../tests/cases/DEPLOYMENT-AZURE.md)重新验收。
- 独立异常后台使用单独 Azure SQL 只读账号，仅授权 `ops_exception_records`、`ops_run_metrics`、`ops_event_timeline`、`ops_build_checks` 四个视图；主 API 不提供跨项目异常读取。
- 复用现有 Azure SQL 避免新增 PostgreSQL 服务，但文本文件会增加 SQL 存储、备份和读写量；账单仍取决于 SQL 计算层级、存储、备份与 Container Apps，须查看实际订阅费用。
- 本地定向用例可直接运行；真实数据库冒烟需把 `TEST_AZURE_SQL_CONNECTION_STRING` 配在测试进程的密钥环境中，并显式设置 `TEST_AZURE_SQL_DISPOSABLE=1`，测试只允许指向可写的专用测试库。密钥不写入命令历史、仓库或日志。

参考：[Azure SQL Python 驱动](https://learn.microsoft.com/en-us/sql/connect/python/mssql-python/installation)、[Azure SQL 瞬时故障](https://learn.microsoft.com/en-us/azure/azure-sql/database/troubleshoot-common-connectivity-issues)、[Azure SQL 成本构成](https://learn.microsoft.com/en-us/azure/azure-sql/database/cost-management)、[Container Apps 临时文件](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)、[Container Apps 身份认证](https://learn.microsoft.com/en-us/azure/container-apps/authentication)。

# Azure 持久化实施与迁移（2026-11-01）

决策见 [ADR-017](decisions/ADR-017-azure-persistent-state-and-artifacts.md)，产品边界见 [PRD §5](PRD.md#5-持久化与版本)，上线出口见 [Azure 部署 TC](../tests/cases/DEPLOYMENT-AZURE.md)。本文是实施顺序和数据契约；**PostgreSQL 开发适配与专项冒烟已写入代码，v2 迁移及本轮修改仍待真实 PostgreSQL 复测；Blob 仍未连入版本/预览，生产 Runner/预览未接通**。

## 两条部署路径

| 路径 | MYATOM 平台数据库 | 交付文件 | 当前可运行范围 |
| --- | --- | --- | --- |
| 本地 | 默认 SQLite；可选 PostgreSQL 做迁移验证 | 本地 `data/` | 主 API、Agent、同宿主 Runner、`.localhost` 预览与独立异常后台，仅可信本机 |
| Azure 目标 | Azure Database for PostgreSQL，显式 schema 迁移 | 私有 Azure Blob，独立隔离 Runner | 目标为完整后端容器、稳定 HTTPS 预览和独立异常后台；生产接线及实测未完成，当前仍拒绝生产启动 |

两条路径共享项目、run、版本及 Agent 的业务契约；通过数据库、文件和 Runner 适配器切换。**Azure 从空库、空 Blob 容器开始，不搬迁本机历史项目、checkpoint、版本或文件**；本地旧数据继续只在本地。生成应用自己的业务数据仍只在其预览 origin 的 `localStorage`，不进入上述关系型数据库。

## 数据归属

| 本地实现 | Azure 新环境的对应实现 | Azure 新数据的恢复要求 |
| --- | --- | --- |
| `data/myatom.sqlite3`：`projects`、`runs`、`events`、`decisions`、`submissions`、`node_outputs`、`operations`、`versions`、`artifact_cleanup`、`exception_records`、`build_check_attempts` | PostgreSQL 平台 schema | 保持所有 ID、事件 `seq`、幂等键、已确认卡、预算、`active_version_id` 和最多 5 个可用版本 |
| `data/checkpoints.sqlite3`：LangGraph checkpointer | PostgreSQL `PostgresSaver` | 用原 `thread_id=run_id` 读回；在等待卡或可恢复节点继续，不重复外部写入 |
| `data/preview_access.sqlite3`：短期票据/会话 | PostgreSQL；新域名独立签发 | 新网关重新签发，不复用本地 `.localhost` 票据 |
| `data/artifacts/<project>/<run>/`：不可变源码及 `dist` | 私有 Blob 容器 | 逐文件 hash/大小与 manifest 一致，可读取和预览旧版 |
| `data/projects/.../workspace`、`data/candidates/...`、npm cache | 隔离 Runner 的临时空间 | 不作为已交付版本的权威数据；恢复时从已确认计划和持久候选引用/文件重建 |
| 生成应用预览域 `localStorage` | 仍在该浏览器预览域 | 不纳入平台迁移或代码回滚；稳定 HTTPS origin 的刷新读回单独实测 |

## 实施顺序

1. **数据库 schema 与连接**：建 PostgreSQL schema 迁移，逐表实现当前事务、顺序、索引和幂等语义；将 SQLite 的 `rowid`、`INSERT OR IGNORE`、`json_extract` 与 `BEGIN IMMEDIATE` 改成明确的 PostgreSQL 等价写法。主 API 与独立运维服务使用不同数据库角色；运维角色仅能查询安全异常视图及必要的脱敏指标。迁移脚本和 API 启动分离。
2. **检查点与任务领取**：接 `langgraph-checkpoint-postgres` 的 `PostgresSaver`，先单工作副本。验证在澄清/计划等待、代码检查、人工修复、额度确认四处重启恢复；跨副本扩容前增加任务领取/租约和超时回收。
3. **文件接口**：抽出 `ArtifactStore` 的 `publish/read/delete/list` 契约。本地实现保持现有路径；Azure 实现用私有 Blob、受控 key、上传后校验和不可变提交标记。`versions.manifest` 只引用已验证文件。预览必须经过平台权限与票据校验读取，而不能生成公开容器 URL。
4. **版本提交**：构建成功 → 候选静态探针 → Blob 完整上传与 hash 复核 → PostgreSQL 事务写版本、运行状态、当前指针与事件。旧版淘汰写清理队列后异步删除文件；失败保留旧指针。后台定期清理未被版本引用的过期候选。
5. **真实 Azure 验收**：在全新空库与空 Blob 容器配置私网或受限网络、托管身份、服务端密钥和备份策略；在测试域执行 [AZ-03/AZ-07](../tests/cases/DEPLOYMENT-AZURE.md)，再连同隔离 Runner、HTTPS 预览完成公开端到端。无真实 Azure 资源时标记“未执行”。

仓库的 [`BlobArtifactStore`](../backend/blob_artifacts.py) 接收已构建候选，逐文件只创建不覆盖、读回核验，最后写完成标记；读文件要求数据库持有的标记 SHA-256。离线契约测试可通过，但尚未连接 Runner/预览或真实 Blob。Azure 可选依赖列在 [`requirements-azure.txt`](../requirements-azure.txt)，当前容器冒烟镜像未启用它们。

### PostgreSQL 开发适配与验证

- [`postgres_v1.sql`](../backend/sql/postgres_v1.sql) 定义平台表、单项目活动 run 唯一索引、按 run 串行的事件序号前提、预览票据和四个脱敏运维视图；[`postgres_v2.sql`](../backend/sql/postgres_v2.sql) 增加迭代基线字段。用 `python -m backend.migrate_postgres`（连接地址通过服务端 `MYATOM_DATABASE_URL`）在部署阶段依序迁移并执行 LangGraph `PostgresSaver.setup()`；主 API 启动不迁移 schema。迁移角色需建表/建索引权限，运行角色只需平台表和 checkpoint 表的读写权限。v1 → v2 应保持项目、run、版本、事件原值，新增字段对旧 run 为 `create`/空基线。
- 本机设置 `APP_ENV=local` 和 `MYATOM_DATABASE_URL` 后，主 API、LangGraph checkpoint 与本地预览票据使用同一 PostgreSQL 库，生成应用仍经本机 Runner/`.localhost` 预览。没有配置时完全沿用 SQLite。设置数据库地址但使用 `APP_ENV=production` 会拒绝启动；这条开发接线不代表公网部署可用。
- 独立异常后台设置 `OPS_DATABASE_URL` 使用另一数据库账号，优先于 `OPS_DB_PATH`。数据库管理员仅授予它 `USAGE ON SCHEMA public` 以及 `SELECT ON ops_exception_records, ops_run_metrics, ops_event_timeline, ops_build_checks`；**不要授予底层表、所有表或默认表权限**。运维连接再执行只读事务，后台代码只查询这四个视图。部署前用真实只读账号验证安全视图可查、`projects` 等底层表不可读、写操作被拒绝。
- [`postgres-smoke.yml`](../.github/workflows/postgres-smoke.yml) 使用一次性 PostgreSQL 服务运行 [专项测试](../tests/test_postgres_platform.py)：v1→v2 升级与重复迁移、schema/checkpoint 初始化、项目/事件/版本指针跨连接读回、票据一次性兑换、待决卡跨 API 实例恢复、运维角色只读。上一轮 CI 的等待卡用例曾因假模型计划与 `localStorage` 规则冲突而失败，本轮已修正用例输入，**新结果仍待工作流实际运行**。Azure PostgreSQL、Blob 与实例替换仍未验证；本地历史数据按本轮决定不搬迁。

## 故障注入与对账

| 注入点 | 必须观察到的结果 |
| --- | --- |
| 上传第 N 个 Blob 时失败 | 版本表与当前指针不变；再次提交复用/核对同 digest 文件；孤儿文件可清理 |
| Blob 已上传、数据库事务前崩溃 | 旧版仍可用；重启后可继续提交或清理孤儿；不得出现指向未完成文件的版本 |
| 数据库版本事务提交后、清理旧文件前崩溃 | 新版本与当前指针可读；清理队列仍在，重启后继续；旧版文件不会先于元数据被删 |
| API/worker/运维服务分别重启 | 项目、卡片、事件序号、checkpoint、文件 hash、回滚指针一致；运维服务只读且能跨项目查 Trace |

## 官方依据

- [Azure Database for PostgreSQL 网络选项](https://learn.microsoft.com/en-us/azure/postgresql/network/how-to-networking)
- [Azure Blob Python 上传与授权](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-upload-python)
- [Azure Container Apps 存储生命周期](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)
- [LangGraph PostgreSQL checkpointer](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py)
- [SQLite WAL 网络文件系统限制](https://sqlite.org/wal.html)

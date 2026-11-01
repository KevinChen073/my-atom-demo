# Azure 受信演示环境：PostgreSQL 与持久 `data/`

当前决定见 [ADR-020](decisions/ADR-020-azure-files-trusted-demo.md)，产品边界见 [PRD](PRD.md)，可执行验收见 [Azure TC](../tests/cases/DEPLOYMENT-AZURE.md)。本地与 Azure 是两套独立数据环境；Azure 从空库与空文件共享开始，**不搬迁本地历史项目、checkpoint、版本或文件**。

| 数据 | 本地 | Azure 受信演示 |
| --- | --- | --- |
| 项目、run、事件、版本指针、异常、预览票据 | SQLite，或本地可选 PostgreSQL | Azure Database for PostgreSQL Flexible Server；schema v2 显式迁移 |
| LangGraph checkpoint | SQLite checkpointer，或本地可选 PostgreSQL | PostgreSQL checkpointer |
| 源码、构建产物、候选与工作区 | 本地 `data/` | Azure Files 挂载到容器 `/app/data`，`MYATOM_DATA_DIR=/app/data` |
| 生成应用的业务数据 | 项目预览 origin 的 `localStorage` | 项目 HTTPS 预览 origin 的 `localStorage`；不进入平台数据库或文件共享 |

## 运行配置与门禁

- `APP_ENV=azure_demo`、`MYATOM_TRUSTED_DEMO=1`：只用于受信演示。`MYATOM_DATABASE_URL` 为服务端 PostgreSQL 连接，`MODEL_API_KEY` 为服务端密钥；两者不得进仓库、日志、生成文件或浏览器。
- `WORKBENCH_ORIGIN=https://<工作台域>`，`PREVIEW_BASE_DOMAIN=<预览域>`。必须为每项目配置 `p-<uuid>.<预览域>` 的稳定 HTTPS 主机；需验证 wildcard DNS/TLS 与 Container Apps Host 转发。预览票据、会话和文件访问仍受版本校验。默认 `.localhost` 路径只用于本地。
- 主 API 和同容器构建只允许 **1 副本、1 worker**。Ingress 必须经过身份认证或 IP 允许列表且实测阻断未授权访问。此模式没有安全代码执行隔离，不可对匿名公网开放；`APP_ENV=production` 仍拒绝启动。
- 启动时检查 PostgreSQL 配置、HTTPS 域、显式受信开关和 `/app/data` 挂载；缺任一项即失败。仅 `/api/health` 成功不代表持久化、构建或预览可用。

## 文件与版本顺序

`data/projects/<project>/<run>/workspace` 由固定模板复制产生；`data/candidates/<run>/<digest>` 存放已构建候选；`data/artifacts/<project>/<run>` 是可用快照。工作区、候选和产物都在 Azure Files 挂载卷上。Runner 在同一主容器执行 `npm ci --ignore-scripts` 和模板受限构建，运行时间、文件数量和输出大小继续受 Harness 限制。它不构成沙箱。

成功顺序为：源码检查 → 构建 → 候选静态资源探针 → 将候选原子更名为不可变产物 → PostgreSQL 事务提交版本、事件及当前指针。数据库事务失败保留旧版；产物清理按数据库持久队列重试。跨 PostgreSQL 与 Azure Files 无原子事务，真实环境须检查中断、重启、只读回旧版、五版本淘汰和 hash 一致性。生成应用业务 `localStorage` 不随代码回滚。

## 已验证与待验

- [PostgreSQL CI](https://github.com/KevinChen073/my-atom-demo/actions/runs/41297467225) 已在一次性 PostgreSQL 16 上通过 schema v1→v2、checkpoint/待决卡恢复、事件/版本读回和运维只读视图；这不等于 Azure Flexible Server 实测。
- 本地专项测试覆盖启动配置与 Host 路由；容器镜像、Azure Files 挂载权限、同容器构建、真实 HTTPS 预览、重启读回和访问限制仍需按 [AZ-01～AZ-07](../tests/cases/DEPLOYMENT-AZURE.md) 执行。没有 Azure CLI/订阅资源时不得写成已部署。
- 独立异常后台继续使用单独服务和 PostgreSQL 只读账号，不能通过主 API 跨项目读取异常。

参考：[Container Apps 存储挂载](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)、[Azure Files 挂载教程](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts-azure-files)、[Container Apps 身份认证](https://learn.microsoft.com/en-us/azure/container-apps/authentication)、[自定义域与证书](https://learn.microsoft.com/en-us/azure/container-apps/custom-domains-certificates)。

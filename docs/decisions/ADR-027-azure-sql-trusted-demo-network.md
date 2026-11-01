# ADR-027：Azure SQL 受信演示网络访问

- 状态：Accepted（2026-11-02；用户确认开启 Azure 服务访问并移除旧容器单 IP 规则）
- 关联：[架构](../ARCHITECTURE.md)、[Azure 持久化](../AZURE-PERSISTENCE.md)、[部署记录](../AZURE-SMOKE-DEPLOY-2026-11-01.md)、[Azure 验收](../../tests/cases/DEPLOYMENT-AZURE.md)、[ADR-021](ADR-021-azure-sql-platform-state.md)

## 决定

受信演示环境的 Azure SQL 逻辑服务器 `my-atom` 保持“公用网络访问：所选网络”，开启“允许 Azure 服务和资源访问此服务器”。移除依赖 Container App 当前出口 IP 的 `myatom-container-egress-20261101` 规则，保留已有的本机管理客户端规则。此决定只适用于受信演示环境，不改变工作台 Container App 的入口 IP 允许列表、单副本限制或数据库身份授权。

该开关添加服务器级 `0.0.0.0` 防火墙规则。**任何 Azure 订阅中的资源都可以从网络层尝试连接该 SQL 服务器**，并非只允许本订阅或本资源组；实际读取或修改数据仍须通过 Azure SQL 身份验证并取得数据库内权限。主 API 继续以系统分配托管身份和 `Authentication=ActiveDirectoryMSI` 连接专用库 `my-atom-dev`。不得把 Azure RBAC 的资源管理角色当作数据库读写权限，也不得在客户端或仓库保存 SQL 凭证。[微软网络控制说明](https://learn.microsoft.com/en-us/azure/azure-sql/database/network-access-controls-overview)、[微软防火墙规则说明](https://learn.microsoft.com/en-us/azure/azure-sql/database/firewall-configure)。

## 权衡与验收

此方案免去 Container App 新修订切换出口 IP 后反复更新 SQL 防火墙规则，代价是 SQL 公共端点的网络可达范围显著扩大。它不适合作为匿名公网生产环境的网络边界；若升级为生产服务，应改用受限虚拟网络/专用终结点，重新验收连接、预览和身份权限。

2026-11-02 门户保存后刷新，开关仍为开启，旧容器单 IP 规则已消失，本机管理客户端规则仍在。旧规则移除后，线上 `azure_demo` 的 `/api/health`、独立访客项目创建、详情读回和列表读回通过；等待防火墙传播窗口后又以新访客会话通过同一读写冒烟，复测项目为 `d7928e21-e3a8-4fba-bd05-53ac8d682719`。这验证了当前容器到 SQL 的基本读写，不证明真实模型生成、版本文本、checkpoint 重启恢复、异常后台只读授权或未授权 IP 拒绝。证据和待验项见[部署记录](../AZURE-SMOKE-DEPLOY-2026-11-01.md)与[Azure 验收](../../tests/cases/DEPLOYMENT-AZURE.md)。

回退时先建立可验证的替代连接路径，再关闭“允许 Azure 服务和资源访问此服务器”；若回到单 IP 规则，须按当前容器出口 IP 重建并重复数据库读写冒烟。

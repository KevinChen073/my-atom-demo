# GitHub → Azure 受信演示验收（2026-11-01）

当前边界见 [ADR-020](../../docs/decisions/ADR-020-azure-files-trusted-demo.md)。本表区分容器启动、持久数据与获授权评审可用；每项记录 Azure 资源、Git 提交、镜像摘要、时间、脱敏日志和实际结果。没有真实 Azure 资源时标记“未执行”。

| ID | 操作与通过判定 | 当前状态 |
| --- | --- | --- |
| AZ-01 源码与凭证 | 核对 Git/镜像；`.env`、`data/`、数据库、真实密钥和用户数据不进入仓库或镜像。 | 部署分支已推送并做本地密钥检查；CI 已构建镜像，镜像内容专项审计未执行。 |
| AZ-02 容器入口 | Dockerfile 构建，默认 `container_smoke` 只开放 `/api/health`；`azure_demo` 缺 PostgreSQL、HTTPS 域或持久挂载时拒绝启动；正常关停后可重启。 | [镜像 CI](https://github.com/KevinChen073/my-atom-demo/actions/runs/41298422604) 已通过默认健康模式 200/主页 503；`azure_demo` 与 Azure 挂载未执行。 |
| AZ-03 持久状态与文件 | 空 PostgreSQL 库迁移到 v2；Azure Files 挂载 `/app/data`。创建项目、待决卡与版本，记录文件 hash；替换容器后核对事件、checkpoint、版本指针、源码、预览文件。模拟文件写入中断和数据库提交中断，旧版仍可读。 | 一次性 PostgreSQL 16 的迁移/恢复 CI [已通过](https://github.com/KevinChen073/my-atom-demo/actions/runs/41297467225)；真实 Azure Files 与容器替换未执行。 |
| AZ-04 受信执行边界 | 仅 1 副本/1 worker；Container Apps 身份认证或 IP 允许列表实际拒绝未授权请求。已授权账号可构建固定模板；验证超时、取消、构建失败、密钥不出现在生成源码/日志。明确标记同容器构建**不是安全沙箱**。 | 本地代码门禁已加入；真实入口限制与同容器构建未执行。 |
| AZ-05 HTTPS 预览 | 工作台与每项目 `p-<uuid>.<预览域>` 分别使用有效 HTTPS 域；跨版本 `localStorage` 刷新读回，同项目稳定、跨项目不能读回；票据过期、重载、CSP 和 iframe 实测。 | Host 路由与 URL 生成已接线；真实 DNS/TLS 与浏览器未执行。 |
| AZ-06 模型与预算 | 测试域只用服务端测试 Key；真实模型生成、用量、预算停机、脱敏及错误归因通过。 | Azure 模型调用未执行。 |
| AZ-07 异常后台 | 运维服务单独部署，PostgreSQL 只读角色只查安全视图；管理员认证、Trace ID、跨项目查询与写入拒绝通过。 | 一次性 PostgreSQL 只读用例通过；Azure 后台未部署。 |
| AZ-08 获授权端到端 | 评审用受控账号或允许 IP 打开在线链接，完成真实生成、预览操作、刷新恢复与回滚；无权限访问被拒绝。记录失败路径与升级后复测。 | 未执行：尚无 Azure 测试域或在线链接。 |

**出口**：AZ-01 至 AZ-08 在同一 Azure 测试域取得证据后，才能称为受信演示可交付。若要面向匿名公网提供生成能力，需先增加隔离 Runner 并重新制定安全验收。业务用例沿用 [PRD §7](../../docs/PRD.md#7-测试与-tc-维护) 与 [MVP2 TC](MVP2.md)。

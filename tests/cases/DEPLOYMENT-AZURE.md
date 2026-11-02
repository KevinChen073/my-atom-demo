# GitHub → Azure 受信演示验收（2026-11-01）

当前边界见 [ADR-020](../../docs/decisions/ADR-020-azure-files-trusted-demo.md)、[ADR-021](../../docs/decisions/ADR-021-azure-sql-platform-state.md)、[ADR-023](../../docs/decisions/ADR-023-azure-sql-text-artifacts.md)、[ADR-026](../../docs/decisions/ADR-026-shared-origin-project-storage.md) 与 [ADR-027](../../docs/decisions/ADR-027-azure-sql-trusted-demo-network.md)。本表区分容器启动、持久数据库、版本文本与获授权评审可用；每项记录 Azure 资源、Git 提交、镜像摘要、时间、脱敏日志和实际结果。没有真实 Azure 资源时标记“未执行”。共享 origin 的项目 ID 前缀仅是逻辑命名空间，不作为安全隔离通过证据；专项用例见 [共享预览 TC](SHARED-ORIGIN-PREVIEW.md)。

| ID | 操作与通过判定 | 当前状态 |
| --- | --- | --- |
| AZ-01 源码与凭证 | 核对 Git/镜像；`.env`、`data/`、数据库、真实密钥和用户数据不进入仓库或镜像。 | 部署分支已推送并做本地密钥检查；CI 已构建镜像，镜像内容专项审计未执行。 |
| AZ-02 容器入口 | Dockerfile 构建，默认 `container_smoke` 只开放 `/api/health`；`azure_demo` 缺 Azure SQL、HTTPS 工作台 origin 或可写 `/app/data` 时拒绝启动；不配置外部文件挂载。 | [镜像 CI](https://github.com/KevinChen073/my-atom-demo/actions/runs/41322698049)成功；Azure `azure_demo` 在线健康接口和首页均 HTTP 200。缺配置拒绝启动只经离线测试。 |
| AZ-03 持久状态与版本文本 | 核对专用 Azure SQL 库为空或已是本仓 schema 后迁移到 v3；确认 `version_files.relative_path` 为 `Latin1_General_100_BIN2`，同一版本中 `src/app.css` 与 `src/App.css` 分别写入并按原路径读回。创建项目、待决卡与版本，核对 `version_files` 的路径、UTF-8 内容和 hash；替换容器并清空临时目录后，项目、事件、checkpoint、pending writes、源码、预览与版本指针仍可读，旧版可回滚并作为下一轮基线。注入文件行写入失败、数据库提交中断和瞬时断连，不能出现部分可用版本；第 6 版清理旧文件行。 | **部分通过（2026-11-02）**：Trace `2a393360-05b4-4978-818f-f1529cfd3eb7` 在旧 schema 的大小写路径冲突处提交失败且无版本，见 ADR-030。管理员会话核对 v2、原排序规则、改表权限和 0 个版本后执行 v3；读回 `MAX(version)=3`、`Latin1_General_100_BIN2`、主键存在。事务内两路径写入及精确读回得 `2 / a / A`，回滚后 `versions=0`、`version_files=0`。镜像 `smoke-37f5fd33b4de117712d0c94ed808c9aab0ded9a9` 部署为修订 `0000012`，工作台首页、历史项目与健康接口可访问。真实 Agent 提交版本、重启后预览/回滚、故障注入及第 6 版清理仍未执行。 |
| AZ-04 受信执行边界 | 仅 1 副本/1 worker；Container Apps 身份认证或 IP 允许列表实际拒绝未授权请求。已授权账号可构建固定模板；验证超时、取消、构建失败、密钥不出现在生成源码/日志。明确标记同容器构建**不是安全沙箱**。Azure SQL 开启所有 Azure 服务网络访问后，核对数据库身份仍是必需条件，不将该开关当作本订阅私有网络边界。 | Azure 单副本上限及工作台入口单 IP 允许列表已配置；SQL 旧容器出口单 IP 规则已移除，允许 Azure 服务访问开关已开启并通过项目写读。其他 IP 拒绝、数据库最小权限审计和在线构建尚未实测。 |
| AZ-05 HTTPS 共享预览 | 工作台与预览使用同一个 Container Apps 默认 HTTPS FQDN 的不同路径；生成应用仅使用 `myatom.app.<项目 UUID>.*` 键，同项目跨版本刷新读回，正常操作不串键；票据过期、重载、CSP、iframe 和服务端版本归属实测。受控脚本验证跨前缀/工作台 Key 可读，按已知风险记录，不能标“跨项目安全隔离通过”。 | 共享路径与存储适配器代码已上线，本地定向测试通过；尚无在线交付版本，真实浏览器预览未执行。 |
| AZ-06 模型与预算 | 测试域使用用户主动提供的测试 Key；真实模型生成、用量、预算停机、脱敏及错误归因通过；共享 origin 下浏览器保存 Key 的暴露风险须先有明确处理决定。 | 用户已确认两端点击保存后写入浏览器 `localStorage`。2026-11-02 新修订 `0000010` 在线以虚构 Key 保存、刷新读回、清除、再次刷新确认缺失均通过；`/api/model/defaults` 的 `api_key` 为空。真实模型调用、预算和在线密钥审计未执行，故本项仍未整体通过。 |
| AZ-07 异常后台 | 运维服务单独部署，Azure SQL 只读角色仅可查四个安全视图；管理员认证、Trace ID、跨项目查询与写入拒绝通过。 | Azure SQL 权限及后台未实测。 |
| AZ-08 获授权端到端 | 评审用受控账号或允许 IP 打开在线链接，完成真实生成、预览操作、刷新恢复与回滚；重启或重新部署后仍能预览、读取源码、回滚与迭代；无权限访问被拒绝。记录失败路径与升级后复测。 | 工作台首页可在允许 IP 的浏览器打开；真实生成、预览、刷新恢复与回滚未执行，因此本项仍未通过。 |

**AZ-03 补充边界**：超过 64 文件、单文件 512 KiB 或整版 2 MiB 时不得提交版本；非 UTF-8、二进制、非法路径及 manifest/hash 不一致须失败且保留旧版。已有 v1 版本只有文件指针时，v2 迁移必须报告并完成受控导入或将其标为不可用，不能把缺文件版本展示为可回滚。异常后台只读账号不得读取 `version_files`。

**出口**：AZ-01 至 AZ-08 在同一 Azure 测试域取得证据、共享 origin 的模型 Key 冲突得到处理后，才能称为受信演示可交付。若要面向匿名公网提供生成能力，需先增加隔离 Runner 与真正的浏览器 origin 边界并重新制定安全验收。业务用例沿用 [PRD §7](../../docs/PRD.md#7-测试与-tc-维护)；[MVP2 TC](MVP2.md) 是 ADR-004 之前的历史口径，当前专项以 [共享预览 TC](SHARED-ORIGIN-PREVIEW.md) 为准。

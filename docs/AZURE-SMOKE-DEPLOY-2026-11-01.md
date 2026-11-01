# Azure 容器镜像发布与启动冒烟记录（2026-11-01）

状态：**完整工作台已在受信 IP 范围上线，项目创建与 Azure SQL 读回冒烟通过；真实模型生成与产物预览仍待用户提供测试 Key 后验证。** 以下前两节保留当时健康模式的历史记录，最新结果见文末。关联 [部署指南](AZURE-CONTAINER-APPS-QUICKSTART.md)、[Azure 持久化方案](AZURE-PERSISTENCE.md)和 [ADR-023](decisions/ADR-023-azure-sql-text-artifacts.md)。

| 检查项 | 实际结果 |
| --- | --- |
| 源码 | `deploy/azure-preparation` 分支提交 `0c2f7237caacccfc5673505113b574c372569250`；只为镜像工作流增加 GHCR 发布权限和推送步骤，主工作区未提交的 Azure SQL 改动未包含在该镜像内 |
| GitHub Actions | [Azure demo image smoke](https://github.com/KevinChen073/my-atom-demo/actions/runs/41307852684) 成功；先运行 Python 测试、Docker 构建和容器健康冒烟，再推送镜像 |
| 镜像仓库 | [公开 GHCR 包](https://github.com/KevinChen073/my-atom-demo/pkgs/container/my-atom-demo)，固定标签 `ghcr.io/kevinchen073/my-atom-demo:smoke-0c2f7237caacccfc5673505113b574c372569250`；另有会移动的 `:smoke` 标签 |
| Azure 容器应用 | 复用 `rg-myatom-quickstart` 中的 `myatom-azure-check`；修订 `myatom-azure-check--0000003` 运行中、健康，镜像指向上述固定标签 |
| 入口与探针 | HTTPS 对外入口目标端口 `8000`；启动、存活、就绪探针均为 `HTTP GET /api/health :8000`。默认探针检查 `/`，而本镜像故意对 `/` 返回 503，故必须覆盖默认路径 |
| 对外验证 | [健康地址](https://myatom-azure-check.kindrock-ede6f587.eastasia.azurecontainerapps.io/api/health) 返回 `ok: true`、`app_env: container_smoke`、`model_configured: false`；根路径返回“容器启动检查模式，应用功能尚未开放” |

本次只验证了 GitHub 构建并发布镜像、Azure 拉取镜像、容器启动与 HTTPS 健康访问。GitHub 工作流目前**不会自动更新 Azure 修订**；本次 Azure 镜像、端口和探针由门户配置。后续要做自动部署，须单独建立 GitHub 到 Azure 的受限部署身份与部署步骤并验证。

## 2026-11-01 后续部署记录

| 检查项 | 实测结果 |
| --- | --- |
| 新源码 | `deploy/azure-preparation` 已推送 `4055e56`（Azure SQL、版本文本、模型设置）及 `ad56bfa`（修复预置 SQL 连接串导致健康模式退出） |
| 镜像 CI | [修复镜像工作流](https://github.com/KevinChen073/my-atom-demo/actions/runs/41316205814) 成功；包含测试、Docker 构建、容器健康检查和 GHCR 发布 |
| Azure 镜像 | `ghcr.io/kevinchen073/my-atom-demo:smoke-ad56bfa3be7b205e3f2010412cb6d0925a2cf4d8` 已部署到 `myatom-azure-check--0000007`；修订显示 Running / Healthy |
| 对外冒烟 | `/api/health` 返回 HTTP 200、`app_env=container_smoke`；根路径返回 HTTP 503，工作台有意不开放 |
| Schema | 用户确认 `my-atom-dev` 已迁移到 v2；Azure 门户只读查询 `SELECT 1 FROM dbo.myatom_schema_version WHERE version=2` 返回 1 行 |
| 容器到 SQL | 容器内 `python -m backend.azure_sql_probe` 第一次返回数据库暂不可用；重试明确返回 SQL 防火墙拒绝出口 IP `20.239.117.15`。只读连接和应用数据读写尚未通过 |

首次新镜像 `4055e56` 在已预置 Azure SQL 连接串的健康模式下启动退出（`RuntimeError: 当前运行环境不允许连接 Azure SQL`）。已恢复旧镜像、修复并通过新增的健康模式测试后重新发布。当前镜像保持健康检查模式；用户确认暂无独立 HTTPS 预览域，并决定暂不修改 Azure SQL 防火墙。因此容器到 SQL 的连接冒烟暂停，不能据此声称 Azure SQL 接线通过。容器出口 IP 可能变化，单 IP 规则也不是长期稳定的网络方案。

此镜像默认 `APP_ENV=container_smoke`。它没有启用工作台、Agent、Azure SQL、预览、模型密钥或版本文件持久化。根据 ADR-023，Azure SQL 的版本文本读写接线和端到端验收完成前，不得切换到 `azure_demo` 或把这个 URL 称为可用产品 Demo。当前 GHCR 包为公开可拉取；镜像中不得包含 `.env` 或密钥。

## 2026-11-01 完整工作台部署记录

| 检查项 | 实测结果 |
| --- | --- |
| 源码与镜像 | `deploy/azure-preparation` 的 `c0390450fc8bd52fa51bf10342a3c574d2b03b78` 已推送；[镜像 CI](https://github.com/KevinChen073/my-atom-demo/actions/runs/41322698049) 成功；Azure 拉取 `ghcr.io/kevinchen073/my-atom-demo:smoke-c0390450fc8bd52fa51bf10342a3c574d2b03b78` 成功。 |
| 入口 | Azure Container App `myatom-azure-check` 采用单副本上限、按需启动、1 core / 2 GiB；入口只允许当前演示客户端的单个 `/32` 地址（具体 IP 仅在 Azure 配置中查看）。客户端出口变化后须更新规则。未从第二个公网 IP 实测拒绝响应。 |
| 数据库 | 托管身份 + `Authentication=ActiveDirectoryMSI`；SQL 服务器规则 `myatom-container-egress-20261101` 仅放行容器当前单个出口 IP。新修订首次因旧规则不匹配而退出；按用户即时确认改规则并重启后启动成功。出口 IP 变化仍可能导致后续连接失败。 |
| 在线健康与页面 | [工作台](https://myatom-azure-check.kindrock-ede6f587.eastasia.azurecontainerapps.io/) 返回 HTTP 200 并在浏览器呈现首页；`/api/health` 返回 HTTP 200、`app_env=azure_demo`、`model_configured=false`。 |
| 在线持久化冒烟 | 用临时访客会话调用 `POST /api/projects` 创建项目 `a20b8790-8b13-4465-a236-c37d13b997b4`，随后 `GET /api/projects/{id}` 与 `GET /api/projects` 均读回该项目。未执行容器替换后的读回或交付物版本文件在线读回。 |
| 模型 Key | `/api/model/defaults` 返回空 `api_key`；Azure 浏览器模型设置显示“仅当前页面会话”，以假的测试字符串保存并刷新后，输入框为空。未使用真实 Key，也未执行真实模型调用。 |
| 产物生成与预览 | 本地定向测试通过；Azure 在线未执行真实生成、构建、预览、回滚。不能以首页与项目读写冒烟声称端到端功能通过。 |

上线截图存于过程资料 `D:/AI/ATOM笔试/evidence/myatom-azure-workbench-2026-11-01.png`，不包含在公开仓库中。此部署仍是受信演示：同源预览的项目 ID 前缀只做命名空间，不提供脚本安全隔离；主容器构建生成代码仅适用于受信输入。GitHub Actions 负责镜像发布，Azure 修订仍由门户手动切换。

## 2026-11-02 Azure SQL 网络调整与冒烟

用户按 [ADR-027](decisions/ADR-027-azure-sql-trusted-demo-network.md) 确认开启 SQL Server `my-atom` 的“允许 Azure 服务和资源访问此服务器”，随后移除 `myatom-container-egress-20261101` 单 IP 规则。门户第一次保存“服务器异常”时返回 `ajaxExtended call failed`，刷新确认未生效；第二次保存显示成功，刷新后开关仍开启。旧单 IP 规则删除也显示成功，刷新后仅保留原有本机管理客户端规则。设置截图留在过程资料 `D:/AI/ATOM笔试/evidence/azure-sql-access-applied-2026-11-02.png`，不进入公开仓库。

在旧规则已移除、未改变 ACA 镜像与入口 IP 允许列表的条件下，在线冒烟结果如下：

| 检查项 | 实测结果 |
| --- | --- |
| API 健康 | `/api/health` 返回 `ok=true`、`app_env=azure_demo` |
| Azure SQL 基础写入 | 新访客会话 `POST /api/projects` 创建项目 `9da96c52-be22-4f39-bd9f-f73d9356c9e7` |
| 同会话读回 | `GET /api/projects/{id}` 的 ID 一致；`GET /api/projects` 列表含该项目 |
| 证明范围 | 当前容器在无旧单 IP 规则时仍能通过托管身份完成项目写读；不证明其他 Azure 身份不可访问数据库，也不证明容器重建后的版本和 checkpoint 恢复 |

等待 Azure SQL 防火墙传播窗口后，再以新的访客会话重复健康检查、项目创建、详情读回和列表读回，均通过；复测项目为 `d7928e21-e3a8-4fba-bd05-53ac8d682719`。这样减少旧规则短时缓存造成误判的可能。未更换容器修订，不能以此代替重建后恢复测试。

完整生成、构建、预览、回滚、异常后台与未授权入口拒绝仍按 [AZ-03～AZ-08](../tests/cases/DEPLOYMENT-AZURE.md)执行。项目冒烟没有调用模型，也没有读取或记录用户的模型 Key。

## 2026-11-02 浏览器模型 Key 持久化部署与冒烟

用户确认 [ADR-028](decisions/ADR-028-browser-model-key-both-environments.md) 后，`deploy/azure-preparation` 分支提交 `553298865602c430072958f9f96ef7d95db8ca38` 已推送。[Azure 镜像工作流](https://github.com/KevinChen073/my-atom-demo/actions/runs/41325134478)和 [PostgreSQL 持久化工作流](https://github.com/KevinChen073/my-atom-demo/actions/runs/41325134388)均通过。门户将固定标签 `ghcr.io/kevinchen073/my-atom-demo:smoke-553298865602c430072958f9f96ef7d95db8ca38` 部署为 `myatom-azure-check--0000010`；修订显示“正在运行(最大值)”、1 个副本、100% 流量。容器日志显示应用启动完成，系统事件显示流量已切换。

| 检查项 | 实测结果 |
| --- | --- |
| 在线服务 | [工作台](https://myatom-azure-check.kindrock-ede6f587.eastasia.azurecontainerapps.io/) 可打开；`/api/health` 为 HTTP 200，`ok=true`、`app_env=azure_demo`。 |
| 默认模型配置 | `/api/model/defaults` 的 `api_key` 字段为空；未向测试浏览器预填服务端 Key。 |
| 保存与刷新 | 在独立测试浏览器输入虚构 Key `fake-azure-smoke-key-20261102`，点击保存，刷新后模型设置可显示同一测试字符串。 |
| 清除 | 点击“清除 Key”后刷新，API Key 输入框为空；测试字符串已从该测试浏览器清除。 |

此次只证明线上浏览器保存、刷新读回与清除路径。未使用真实模型 Key，未执行模型连接、生成、预算停机或密钥在数据库及运行日志中的在线专项审计。共享 origin 预览脚本可能读取工作台 `localStorage`，因此仍限受信演示环境；完整交付验收继续按 [AZ-03～AZ-08](../tests/cases/DEPLOYMENT-AZURE.md)执行。

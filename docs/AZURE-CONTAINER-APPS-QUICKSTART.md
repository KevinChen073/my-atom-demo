# MYATOM：从 GitHub 到 Azure Container Apps 快速操作指南

状态：操作文档，2026-11-01；**完整工作台已部署到受信 IP 范围，首页和 Azure SQL 项目读写冒烟通过；真实模型生成、预览与重启恢复尚未在线验证。** 实际证据与配置见 [Azure 部署记录](AZURE-SMOKE-DEPLOY-2026-11-01.md)。产品验收以 [PRD](PRD.md)、[架构](ARCHITECTURE.md) 和 [部署 TC](../tests/cases/DEPLOYMENT-AZURE.md) 为准；路线决定见 [ADR-014](decisions/ADR-014-atoms-deployment-and-model-credentials.md)。

## 先看官方入口

- [Azure Container Apps 门户快速入门](https://learn.microsoft.com/en-us/azure/container-apps/quickstart-portal)：不写命令，先看到一个 Azure 站点。
- [从 GitHub 仓库构建并部署](https://learn.microsoft.com/en-us/azure/container-apps/quickstart-repo-to-cloud)：使用 `az containerapp up --repo` 建立容器应用及 GitHub Actions 自动部署。
- [`az containerapp up` 完整说明](https://learn.microsoft.com/en-us/azure/container-apps/containerapp-up)：查看参数、自动创建的资源、重新部署和限制。
- [Windows 安装 Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows)：若选择命令行路径。

## 0. MYATOM 当前状态与“成功”含义

本仓库的部署分支是 `deploy/azure-preparation`；[当前镜像工作流](https://github.com/KevinChen073/my-atom-demo/actions/runs/41322698049)已构建并发布 GHCR 镜像，Azure Container App 运行 `azure_demo` 模式，详见[实测记录](AZURE-SMOKE-DEPLOY-2026-11-01.md)。资源组为 `rg-myatom-quickstart`，Azure SQL Server 为 `my-atom.database.windows.net`，数据库为 `my-atom-dev`（schema v2）。容器托管身份已通过应用接口完成项目创建与读回。数据库采用免费无服务器层，实际使用量和后续账单仍须在 Azure 核对。本机尚无 Docker/Azure CLI。当前目标以 [ADR-020](decisions/ADR-020-azure-files-trusted-demo.md)、[ADR-021](decisions/ADR-021-azure-sql-platform-state.md) 和 [ADR-023](decisions/ADR-023-azure-sql-text-artifacts.md) 为准：Azure SQL 持久保存平台状态与版本文本，容器 `data/` 只作临时构建，**仅限受信人员**。

| 里程碑 | 可说明什么 | 不能说明什么 |
| --- | --- | --- |
| A：官方样例 URL 可打开 | Azure 账户、Container Apps 环境、公开入口可用 | MYATOM 代码已部署或功能可用 |
| B：MYATOM `/api/health` 返回 200 | 主 API 容器启动并可接请求 | LangGraph 恢复、持久化、模型、共享路径预览或真实生成已通过 |
| C：获授权评审 URL 完成 PRD 主旅程 | 按具体测试记录判定受信演示可用 | 单次成功不自动证明重启恢复、浏览器凭证安全及更新稳定性 |

## 1. 最快试通 Azure：门户操作

1. 登录 [Azure 门户](https://portal.azure.com/)，选定有有效订阅且具备 **Contributor/Owner** 权限的账户。先在 Cost Management 给测试资源组设预算提醒；预算是提醒，不应当成硬性停机开关。[Azure 预算说明](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets)。
2. 先打开现有资源组 `rg-myatom-quickstart`，核对已有 Container App、环境与 SQL Database 的名称和配置。若只想复核官方样例，可打开现有 `myatom-azure-check`；不要重复创建同名资源。
3. 如现有样例应用无法使用且确需新建测试应用，再按[门户快速入门](https://learn.microsoft.com/en-us/azure/container-apps/quickstart-portal)选择 **Use quickstart image** 并确认费用后创建。
4. 打开现有或新建应用的 URL，记录订阅、资源组、区域、URL、时间和实际页面。若失败，在容器应用的 **Log stream** 查看系统与控制台日志；步骤见[日志说明](https://learn.microsoft.com/en-us/azure/container-apps/log-streaming)。
5. 样例仅用于验证 Azure 账户和公开入口。清理时先在门户核对该资源组只包含样例资源，再按官方快速入门的清理说明处理；不要删除包含其他项目的资源组。

## 2. 可选命令行：复现官方样例

如需另行复现官方样例，可先按 [Windows 官方说明](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows)安装 Azure CLI，**重新打开终端**后执行。以下命令会创建或修改资源；已有 `myatom-azure-check` 时先核对其环境与配置，避免重复运行。

```powershell
az login
az account list --output table
az account set --subscription "<你的订阅 ID>"
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights

$resourceGroup = "rg-myatom-quickstart"
$environmentName = "env-myatom-quickstart"
$appName = "myatom-azure-check"
$location = "<该订阅支持的 Azure 区域，例如 centralus>"

az containerapp up `
  --name $appName `
  --resource-group $resourceGroup `
  --location $location `
  --environment $environmentName `
  --image mcr.microsoft.com/k8se/quickstart:latest `
  --target-port 80 `
  --ingress external `
  --query properties.configuration.ingress.fqdn `
  --output tsv
```

把输出的域名加上 `https://` 在浏览器打开。命令来自 [Container Apps 官方入门](https://learn.microsoft.com/en-us/azure/container-apps/get-started)；若只想试通站点，做到这里即可。`az containerapp up` 可能自动创建 Container Apps 环境与 Log Analytics 工作区，须在订阅中核对实际资源。

## 3. 把 MYATOM 从 GitHub 部署：先准备，再执行

### 3.1 必须先完成的代码/资源准备

| 准备项 | 本仓现状 | 达到可部署候选的条件 |
| --- | --- | --- |
| GitHub 源码 | 部署分支已推送；根目录 Dockerfile 已在 GitHub Actions 构建、发布 GHCR，并在 Azure 容器中通过健康模式冒烟，本机无 Docker | 完整应用上线前核对镜像摘要、容器设置与 `.env`、`data/`、密钥未进镜像；容器启动不代表 Azure SQL 和预览域通过 |
| Python 服务入口 | `backend/serve.py` 明确只允许 `APP_ENV=local`，主 API 在 `backend/api.py` | 生产入口使用受支持的 ASGI 启动方式；区分测试/生产环境，容器启动、健康检查与关停行为通过测试 |
| 平台状态 | 本地默认 SQLite；旧 PostgreSQL schema v2 用例在 CI 通过 | Azure 使用专用空 Azure SQL 库；平台 schema v1 与版本文本 schema v2 显式迁移、重启读回，独立异常后台只读查询；不搬本地历史 |
| 文件与 Runner | 本地 `data/`；同宿主 Runner；镜像已加入 Node/npm 并通过健康模式容器冒烟，尚未在容器内运行生成构建 | Azure SQL `version_files` 保存受控源码与文本构建资源；容器 `/app/data` 只作临时工作区，不配置外部挂载。验证重启后从 SQL 预览/回滚/迭代；仅在受信演示环境同容器构建，单副本/单 worker，绝非安全沙箱 |
| 预览与入口 | 本地同源 `/preview/...` 路由、票据与项目 ID 注入定向测试通过 | Azure 默认 HTTPS FQDN 同 origin 的 `/preview/...` 路径与 `myatom.app.<项目 UUID>.*` 存储前缀；需在线验证票据/刷新读回及入口认证/IP 允许列表。前缀不构成安全隔离，详见 [ADR-026](decisions/ADR-026-shared-origin-project-storage.md) |
| 模型与密钥 | 工作台可输入 DeepSeek / OpenAI 兼容 API Key，本地 `.env` 可预填 | 本地与 Azure 均在点击保存后将用户 Key 写入当前浏览器 `localStorage`，刷新后恢复；见 [ADR-028](decisions/ADR-028-browser-model-key-both-environments.md)。主 API 不持久保存 Key；真实模型测试需用户提供测试 Key |

受信演示配置为 `APP_ENV=azure_demo`、`MYATOM_TRUSTED_DEMO=1`、`MYATOM_AZURE_SQL_CONNECTION_STRING`、`WORKBENCH_ORIGIN`（Container Apps 默认 HTTPS FQDN）、`MYATOM_DATA_DIR=/app/data`；不需要 `PREVIEW_BASE_DOMAIN`。同源路由本地定向测试通过，Azure 首页已打开，真实产物预览仍待验证。用户在工作台填写模型 Key，服务器 `MODEL_API_KEY` 不设置；Azure 页面刷新后恢复已保存 Key；同源预览脚本可读取这一保存键，风险见 [ADR-026](decisions/ADR-026-shared-origin-project-storage.md) 与 [ADR-028](decisions/ADR-028-browser-model-key-both-environments.md)。Azure SQL 连接加密并验证证书，不设置 `MYATOM_DATABASE_URL`。入口 IP 允许列表已配置，但从非允许 IP 的拒绝响应尚未实测。实际访问参数和凭证不写进仓库。

### 3.1.1 容器临时工作区与运行参数

镜像内 `/app/data` 已为 `myatom` 用户创建；Container Apps 不配置 `volumeMounts` 或 `template.volumes`。设置 `MYATOM_DATA_DIR=/app/data`、单副本和单一 Uvicorn worker。镜像默认是 `container_smoke`；专用 Azure SQL 库 schema v1/v2 迁移、共享路径预览代码迁移、浏览器模型 Key 风险处理和受信入口限制就绪后，才将运行配置改为 `azure_demo`。Azure 的入口认证或 IP 规则须覆盖工作台与同 origin 的全部预览路径。[Container Apps 存储说明](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)明确容器文件系统在关闭或重启时会丢失；所以它只能存未提交的临时文件。

### 3.1.2 本地容器启动冒烟

在具备 Docker 的机器上，从仓库根目录执行：

```powershell
docker build -t myatom-api-smoke .
docker run --rm -p 127.0.0.1:18000:8000 myatom-api-smoke
```

另开终端访问 `http://127.0.0.1:18000/api/health`，预期 HTTP 200；访问 `http://127.0.0.1:18000/`，预期 HTTP 503。然后停止容器，确认进程退出。503 是 `container_smoke` 有意封闭应用功能的结果；只有 Azure SQL、共享路径 HTTPS 预览、模型 Key 风险处理和受信入口限制实测后，才可开放受信演示。固定标签镜像已由 [GitHub 工作流](https://github.com/KevinChen073/my-atom-demo/actions/runs/41316205814)构建并在 Azure 健康冒烟通过；本机缺少 Docker，`azure_demo` 与容器重启对账尚未实测。

### 3.2 准备完成后的 GitHub 自动部署命令模板

官方 `up --repo` 会创建 Azure 容器资源、镜像仓库与 GitHub Actions 工作流，并要求授权访问 GitHub；**不要直接对当前 `main` 和未就绪代码执行**。以下模板只用于准备部署分支的容器入口；之后仍须配置数据库、访问限制和共享路径预览。把尖括号内容替换为真实值。

```powershell
$resourceGroup = "<MYATOM 专用资源组>"
$environmentName = "<Container Apps 环境名>"
$appName = "<MYATOM 主 API 名>"
$location = "<支持 Container Apps 的区域>"
$repoUrl = "https://github.com/KevinChen073/my-atom-demo"
$branchName = "<已准备好的部署分支>"

az containerapp up `
  --name $appName `
  --resource-group $resourceGroup `
  --location $location `
  --environment $environmentName `
  --repo $repoUrl `
  --branch $branchName `
  --ingress external `
  --target-port 8000
```

执行时按提示完成 GitHub 设备授权；随后检查仓库新增的 `.github/workflows/` 文件、触发分支和 Azure 资源。以后应按审核过的工作流推送更新，**不要重复运行 `up --repo` 生成多份工作流**；该注意事项见 [`up` 官方说明](https://learn.microsoft.com/en-us/azure/container-apps/containerapp-up)。若 CLI/套餐/区域提示变化，以当时 `az containerapp up --help` 和官方文档为准。

### 3.3 凭证、验证与交付

1. 在 Azure Container App 的配置中添加运行时密钥，并通过环境变量引用；不要在命令行参数、GitHub 文件或截图中粘贴实际 Key。方法见 [Container Apps 密钥](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets)与[环境变量](https://learn.microsoft.com/en-us/azure/container-apps/environment-variables)。
2. 获取部署 URL，访问 `https://<主域名>/api/health`，检查 `ok`、环境和模型配置状态。这个接口只能验证 API 启动。失败时看 [容器日志](https://learn.microsoft.com/en-us/azure/container-apps/log-streaming)；日志不得包含 Key。
3. 单独部署异常后台，使用 `OPS_AZURE_SQL_CONNECTION_STRING` 的专用只读账号，仅授权四个 `ops_*` 视图；主应用的已提交版本从 Azure SQL 读取，容器 `/app/data` 只作临时构建。核对访问限制、目录权限、域名和证书；主容器内构建仅限获授权评审使用。
4. 在获授权测试 URL 逐项执行 `TC-E2E-01`（生成应用操作与刷新读回）、[共享预览 TC](../tests/cases/SHARED-ORIGIN-PREVIEW.md)（正常键前缀读写与同源风险取证）、重启后 Azure SQL 项目/checkpoint/源码/预览文件恢复、SSE 回放、版本回滚与迭代、独立异常后台只读查询；验证未授权请求被拒绝。`TC-SEC-01` 的旧“预览脚本无法读取工作台 Key/其他项目键”在新架构下不能判通过。记录环境、Git 提交号、URL、时间、实际结果、截图与脱敏日志。

## 本文未验证的边界

这份指南核对了 Azure 官方操作步骤与当前仓库结构；GitHub 部署分支已推送，复用现有 Azure 容器应用，没有创建额外云资源。本机未检测到 Azure CLI。容器托管身份 Azure SQL 连接已通过在线项目创建与读回冒烟。2026-11-02 按 [ADR-027](decisions/ADR-027-azure-sql-trusted-demo-network.md) 开启 SQL Server 的“允许 Azure 服务和资源访问此服务器”，移除旧容器出口单 IP 规则后再次通过基础读写冒烟。该开关允许所有 Azure 订阅中的资源尝试连接 SQL，须维持数据库身份权限与工作台入口限制；不作为生产网络方案。未验证的仍有容器替换后读回、交付物版本文件、真实模型生成与预览、从未授权 IP 拒绝请求、独立异常后台；GitHub 到 Azure 的自动更新尚未配置。

# MYATOM：从 GitHub 到 Azure Container Apps 快速操作指南

状态：操作文档，2026-11-01；**GitHub → Azure 路线已选定，尚未在 Azure 订阅或公开 URL 执行**。本指南先帮助你创建一个可访问的 Azure 测试应用，再说明把 MYATOM 真正部署到 Azure 的条件。产品验收以 [PRD](PRD.md)、[架构](ARCHITECTURE.md) 和 [部署 TC](../tests/cases/DEPLOYMENT-AZURE.md) 为准；路线决定见 [ADR-014](decisions/ADR-014-atoms-deployment-and-model-credentials.md)。云资源创建、GitHub 推送和正式发布按根目录工作约束执行；阅读本文不表示已执行。

## 先看官方入口

- [Azure Container Apps 门户快速入门](https://learn.microsoft.com/en-us/azure/container-apps/quickstart-portal)：不写命令，先看到一个 Azure 站点。
- [从 GitHub 仓库构建并部署](https://learn.microsoft.com/en-us/azure/container-apps/quickstart-repo-to-cloud)：使用 `az containerapp up --repo` 建立容器应用及 GitHub Actions 自动部署。
- [`az containerapp up` 完整说明](https://learn.microsoft.com/en-us/azure/container-apps/containerapp-up)：查看参数、自动创建的资源、重新部署和限制。
- [Windows 安装 Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows)：若选择命令行路径。

## 0. MYATOM 当前状态与“成功”含义

本仓库的部署准备分支是 `deploy/azure-preparation`；[PostgreSQL 工作流](https://github.com/KevinChen073/my-atom-demo/actions/runs/41297467225)已用一次性数据库通过 schema v2 与恢复冒烟，但不部署 Azure。本机尚无 Docker/Azure CLI，镜像和真实 Azure 资源未验证。当前路线以 [ADR-020](decisions/ADR-020-azure-files-trusted-demo.md) 为准：Azure Files 挂载 `data/`、主容器内构建，**仅限受信人员**。`az containerapp up --repo` 只读取 GitHub 已提交分支，且可能创建云资源；不能用它代替持久挂载、访问限制及预览域验收。

| 里程碑 | 可说明什么 | 不能说明什么 |
| --- | --- | --- |
| A：官方样例 URL 可打开 | Azure 账户、Container Apps 环境、公开入口可用 | MYATOM 代码已部署或功能可用 |
| B：MYATOM `/api/health` 返回 200 | 主 API 容器启动并可接请求 | LangGraph 恢复、持久化、模型、隔离预览或真实生成已通过 |
| C：获授权评审 URL 完成 PRD 主旅程 | 按具体测试记录判定受信演示可用 | 单次成功不自动证明重启恢复、跨项目隔离及更新稳定性 |

## 1. 最快试通 Azure：门户操作

1. 登录 [Azure 门户](https://portal.azure.com/)，选定有有效订阅且具备 **Contributor/Owner** 权限的账户。先在 Cost Management 给测试资源组设预算提醒；预算是提醒，不应当成硬性停机开关。[Azure 预算说明](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets)。
2. 搜索 **Container Apps** → **Create** → **Container App**。新建一个只用于测试的资源组，名称可用 `rg-myatom-quickstart`；应用名称可用 `myatom-azure-check`。选账号可用且距离评审较近的区域。
3. 容器页选 **Use quickstart image**，按门户提示 **Review + create** → **Create**。这一步会创建真实云资源，可能产生费用。官方界面步骤见[门户快速入门](https://learn.microsoft.com/en-us/azure/container-apps/quickstart-portal)。
4. 打开部署结果中的应用 URL，记录订阅、资源组、区域、URL、时间和实际页面。若失败，在容器应用的 **Log stream** 查看系统与控制台日志；步骤见[日志说明](https://learn.microsoft.com/en-us/azure/container-apps/log-streaming)。
5. 样例仅用于验证 Azure 账户和公开入口。清理时先在门户核对该资源组只包含样例资源，再按官方快速入门的清理说明处理；不要删除包含其他项目的资源组。

## 2. 可选命令行：复现官方样例

如喜欢 PowerShell，可先按 [Windows 官方说明](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows)安装 Azure CLI，**重新打开终端**后执行。以下命令会创建资源；只在确认订阅、区域和费用后运行。

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
| GitHub 源码 | 本地有未提交工作；未建立部署分支。根目录 Dockerfile 与 `.dockerignore` 已准备，但本机无 Docker，尚未构建镜像 | 核对本地改动，建立受控部署分支，提交/推送经确认的代码；实测根目录 Dockerfile 构建 `web/dist` 和 Python 依赖、启动主 API 监听 `0.0.0.0:8000` 并暴露 8000；不把 `.env`、`data/`、密钥推送到 GitHub |
| Python 服务入口 | `backend/serve.py` 明确只允许 `APP_ENV=local`，主 API 在 `backend/api.py` | 生产入口使用受支持的 ASGI 启动方式；区分测试/生产环境，容器启动、健康检查与关停行为通过测试 |
| 平台状态 | 本地默认 SQLite；PostgreSQL schema v2 与恢复用例已在 CI 通过 | Azure 从空 PostgreSQL 库开始；显式迁移、重启读回，独立异常后台只读查询；不搬本地历史 |
| 文件与 Runner | 本地 `data/`；同宿主 Runner；镜像已加入 Node/npm，尚未容器实测 | Azure Files 挂载 `/app/data` 并验证写入权限、文件 hash、容器替换后读回；只在受信演示环境同容器构建，单副本/单 worker，绝非安全沙箱 |
| 预览与入口 | 本地 `.localhost` 项目域 | 工作台 HTTPS 域与 `p-<uuid>.<预览域>` wildcard DNS/TLS 指向同一容器 8000；每项目 origin 隔离、票据、CSP、localStorage 刷新读回及入口认证/IP 允许列表实测 |
| 模型与密钥 | 当前本地 `.env`；拟支持 DeepSeek 与 OpenAI 兼容 API | 服务端密钥和预算配置；用户输入 Key 不进入前端持久存储、仓库、日志或预览代码；真实模型测试需用户提供测试 Key |

上述条件不满足时，最多部署一个**受限测试容器**验证启动。受信演示需在容器配置 `APP_ENV=azure_demo`、`MYATOM_TRUSTED_DEMO=1`、`MYATOM_DATABASE_URL`、`MODEL_API_KEY`、`WORKBENCH_ORIGIN`、`PREVIEW_BASE_DOMAIN`、`MYATOM_DATA_DIR=/app/data`；缺持久挂载或域名配置时启动会失败。访问限制必须先在 Container Apps ingress 层配置并实测。实际访问参数和凭证只放 Azure 服务端配置，不写进仓库。

### 3.1.1 Azure Files 挂载与运行参数

先在 Container Apps 环境登记**经典 Azure Files 共享**，再导出应用 YAML，在容器 `volumeMounts` 中加入 `/app/data`，并在 `template.volumes` 中引用环境级 `storageName`。下面是应合并到应用 YAML 的片段，不能当完整资源定义直接提交；具体字段和操作以 [微软挂载教程](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts-azure-files) 为准：

```yaml
template:
  containers:
    - name: myatom-api
      volumeMounts:
        - volumeName: myatom-data
          mountPath: /app/data
  volumes:
    - name: myatom-data
      storageType: AzureFile
      storageName: myatom-files
  scale:
    minReplicas: 1
    maxReplicas: 1
```

镜像默认是 `container_smoke`。挂载、空 PostgreSQL 库 schema v2 迁移、HTTPS 工作台和 wildcard 预览域、受信入口限制就绪后，才将运行配置改为 `azure_demo`。挂载路径必须能被容器内 `myatom` 用户写入；若启动时报挂载或权限错误，先检查 Azure Files 挂载配置，不要改为临时盘继续。使用单一 Uvicorn worker。Azure 的入口认证或 IP 规则须覆盖工作台及所有预览子域。

### 3.1.2 本地容器启动冒烟

在具备 Docker 的机器上，从仓库根目录执行：

```powershell
docker build -t myatom-api-smoke .
docker run --rm -p 127.0.0.1:18000:8000 myatom-api-smoke
```

另开终端访问 `http://127.0.0.1:18000/api/health`，预期 HTTP 200；访问 `http://127.0.0.1:18000/`，预期 HTTP 503。然后停止容器，确认进程退出。503 是 `container_smoke` 有意封闭应用功能的结果；只有生产存储、Runner 和预览隔离完成后才能开放主流程。本机缺少 Docker，以上命令尚未执行，不能据此声称镜像已通过构建。

### 3.2 准备完成后的 GitHub 自动部署命令模板

官方 `up --repo` 会创建 Azure 容器资源、镜像仓库与 GitHub Actions 工作流，并要求授权访问 GitHub；**不要直接对当前 `main` 和未就绪代码执行**。以下模板只用于准备部署分支的容器入口；之后仍须配置持久卷、数据库、访问限制和预览域。把尖括号内容替换为真实值。

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
3. 单独部署异常后台并授予 PostgreSQL 安全视图只读权限；主应用挂载 Azure Files，Host 路由工作台与每项目预览域。核对访问限制、挂载权限、域名和证书；主容器内构建仅限获授权评审使用。
4. 在获授权测试 URL 逐项执行 `TC-E2E-01`（生成应用操作与刷新读回）、`TC-SEC-01`（密钥与跨项目隔离）、重启后 LangGraph/checkpoint 恢复、SSE 回放、版本回滚及独立异常后台只读查询；验证未授权请求被拒绝。记录环境、Git 提交号、URL、时间、实际结果、截图与脱敏日志。

## 本文未验证的边界

这份指南核对了 Azure 官方操作步骤与当前仓库结构；GitHub 准备分支已推送，但**没有登录 Azure、创建云资源、配置密钥或访问 Azure URL**。本机未检测到 Azure CLI。首个样例 URL 需要实际运行后才能确认；受信演示交付还依赖 §3.1 的挂载、访问限制、域名和真实环境验收。

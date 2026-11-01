# Azure 容器镜像发布与启动冒烟记录（2026-11-01）

状态：**镜像构建、GHCR 发布和 Azure Container Apps 启动冒烟已通过；完整 MYATOM 应用未开放。** 本记录对应 [部署指南](AZURE-CONTAINER-APPS-QUICKSTART.md)、[Azure 持久化方案](AZURE-PERSISTENCE.md)和 [ADR-023](decisions/ADR-023-azure-sql-text-artifacts.md)。

| 检查项 | 实际结果 |
| --- | --- |
| 源码 | `deploy/azure-preparation` 分支提交 `0c2f7237caacccfc5673505113b574c372569250`；只为镜像工作流增加 GHCR 发布权限和推送步骤，主工作区未提交的 Azure SQL 改动未包含在该镜像内 |
| GitHub Actions | [Azure demo image smoke](https://github.com/KevinChen073/my-atom-demo/actions/runs/41307852684) 成功；先运行 Python 测试、Docker 构建和容器健康冒烟，再推送镜像 |
| 镜像仓库 | [公开 GHCR 包](https://github.com/KevinChen073/my-atom-demo/pkgs/container/my-atom-demo)，固定标签 `ghcr.io/kevinchen073/my-atom-demo:smoke-0c2f7237caacccfc5673505113b574c372569250`；另有会移动的 `:smoke` 标签 |
| Azure 容器应用 | 复用 `rg-myatom-quickstart` 中的 `myatom-azure-check`；修订 `myatom-azure-check--0000003` 运行中、健康，镜像指向上述固定标签 |
| 入口与探针 | HTTPS 对外入口目标端口 `8000`；启动、存活、就绪探针均为 `HTTP GET /api/health :8000`。默认探针检查 `/`，而本镜像故意对 `/` 返回 503，故必须覆盖默认路径 |
| 对外验证 | [健康地址](https://myatom-azure-check.kindrock-ede6f587.eastasia.azurecontainerapps.io/api/health) 返回 `ok: true`、`app_env: container_smoke`、`model_configured: false`；根路径返回“容器启动检查模式，应用功能尚未开放” |

本次只验证了 GitHub 构建并发布镜像、Azure 拉取镜像、容器启动与 HTTPS 健康访问。GitHub 工作流目前**不会自动更新 Azure 修订**；本次 Azure 镜像、端口和探针由门户配置。后续要做自动部署，须单独建立 GitHub 到 Azure 的受限部署身份与部署步骤并验证。

此镜像默认 `APP_ENV=container_smoke`。它没有启用工作台、Agent、Azure SQL、预览、模型密钥或版本文件持久化。根据 ADR-023，Azure SQL 的版本文本读写接线和端到端验收完成前，不得切换到 `azure_demo` 或把这个 URL 称为可用产品 Demo。当前 GHCR 包为公开可拉取；镜像中不得包含 `.env` 或密钥。

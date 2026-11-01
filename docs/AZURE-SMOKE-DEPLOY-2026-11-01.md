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

## 2026-11-01 后续部署记录

| 检查项 | 实测结果 |
| --- | --- |
| 新源码 | `deploy/azure-preparation` 已推送 `4055e56`（Azure SQL、版本文本、模型设置）及 `ad56bfa`（修复预置 SQL 连接串导致健康模式退出） |
| 镜像 CI | [修复镜像工作流](https://github.com/KevinChen073/my-atom-demo/actions/runs/41316205814) 成功；包含测试、Docker 构建、容器健康检查和 GHCR 发布 |
| Azure 镜像 | `ghcr.io/kevinchen073/my-atom-demo:smoke-ad56bfa3be7b205e3f2010412cb6d0925a2cf4d8` 已部署到 `myatom-azure-check--0000007`；修订显示 Running / Healthy |
| 对外冒烟 | `/api/health` 返回 HTTP 200、`app_env=container_smoke`；根路径返回 HTTP 503，工作台有意不开放 |
| Schema | 用户确认 `my-atom-dev` 已迁移到 v2；Azure 门户只读查询 `SELECT 1 FROM dbo.myatom_schema_version WHERE version=2` 返回 1 行 |
| 容器到 SQL | 容器内 `python -m backend.azure_sql_probe` 第一次返回数据库暂不可用；重试明确返回 SQL 防火墙拒绝出口 IP `20.239.117.15`。只读连接和应用数据读写尚未通过 |

首次新镜像 `4055e56` 在已预置 Azure SQL 连接串的健康模式下启动退出（`RuntimeError: 当前运行环境不允许连接 Azure SQL`）。已恢复旧镜像、修复并通过新增的健康模式测试后重新发布。当前镜像保持健康检查模式；用户确认暂无独立 HTTPS 预览域。SQL 单 IP 防火墙规则尚未保存，等待网络访问变更确认。容器出口 IP 可能变化，单 IP 规则只用于当前冒烟，不是长期稳定的网络方案。

此镜像默认 `APP_ENV=container_smoke`。它没有启用工作台、Agent、Azure SQL、预览、模型密钥或版本文件持久化。根据 ADR-023，Azure SQL 的版本文本读写接线和端到端验收完成前，不得切换到 `azure_demo` 或把这个 URL 称为可用产品 Demo。当前 GHCR 包为公开可拉取；镜像中不得包含 `.env` 或密钥。

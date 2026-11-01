# ADR-026：共享预览 origin 与项目 ID 存储前缀

- 状态：Accepted（2026-11-01，用户明确要求修改架构）；共享路径与模板适配器已在本地实现并通过定向测试，Azure 浏览器验收仍待执行。
- 修订：[ADR-004](ADR-004-generated-deliverable-boundaries.md) 第 3 条的每项目独立 origin、[ADR-020](ADR-020-azure-files-trusted-demo.md) 第 3/5 条的 wildcard 预览域，以及相应 PRD、架构和 Azure 部署目标。历史决定保留供追溯。
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[Azure 部署](../AZURE-CONTAINER-APPS-QUICKSTART.md)、[现行模型 Key 决定](ADR-028-browser-model-key-both-environments.md)、[验收](../../tests/cases/DEPLOYMENT-AZURE.md)。

## 背景与决定

每项目 `p-<uuid>.<预览域>` 要求 wildcard DNS/TLS；现有 Azure Container App 已有可直接使用的 HTTPS 默认域名。为缩短受信演示的部署路径，**工作台和所有项目预览共用该应用的同一个 origin**，用不同 URL 路径路由预览，不再要求 `PREVIEW_BASE_DOMAIN` 或每项目子域名。本地目标也采用工作台同 origin 的预览路径；现有 `.localhost:8001` 实现属于待迁移旧行为。

生成应用业务数据仍只用浏览器 `localStorage`，固定键名前缀为 `myatom.app.<规范化项目 UUID>.`；规范化形式是 UUID 去连字符后的 **32 位小写十六进制**，后面接受控的应用键名和可选 schema 版本，**不加入交付物版本 ID**，保证同项目 v1/v2/回滚读取同一份业务数据。模板的 `GeneratedAppStorage` 在 `src/hooks/` 内统一读写、校验和报错；生成代码不得直接使用无前缀键、`localStorage.clear()` 或扫删其他键。项目 UUID 必须由可信的预览上下文注入，不接受生成代码自报或 URL 任意参数替换。旧独立 origin 中的浏览器数据不会自动搬到共享 origin；如要迁移须另做用户可见的数据导出/导入。

预览入口目标为工作台 origin 下的 `/preview/open/{version_id}?ticket=...`，兑换后使用带短期会话的 `/preview/s/{session}/v/{version_id}/...` 路径。服务端仍校验票据、会话、版本与项目归属，并限制资源路径；这些检查只控制服务端文件访问，**不能隔离同源浏览器脚本**。相对资源路径、刷新、重新载入与票据过期须实测。平台项目、checkpoint、版本源码仍在 SQLite/Azure SQL；浏览器业务数据不随代码回滚。

## 安全边界与冲突

浏览器按 origin 共享 `localStorage`。项目 ID 前缀只降低误写和键名冲突，**不构成跨项目数据保密或权限隔离**：同源生成代码可枚举、读取、改写其他项目键。本地与 Azure 工作台依 [ADR-028](ADR-028-browser-model-key-both-environments.md) 在用户点击保存后，将模型 API Key 写入同 origin 的 `localStorage`；预览脚本可能读取，刷新后也不会自动清除。路径、CSP、短期预览票据和 iframe `sandbox` 不能补出原先的 origin 安全边界。不得再声称 `TC-SEC-01` 的跨项目/凭证隔离通过。

此方案仅作为**受信、受限演示的产品简化**，不是匿名公网或不可信生成代码的安全架构。入口仍须限制为获授权人员；不得在共享 origin 预览中输入真实敏感业务数据。用户已选择两端都在浏览器保存 Key，持久暴露面扩大。若要求跨项目保密、可靠保护浏览器模型 Key 或公开任意代码，必须重新引入真正的 origin/执行隔离并重做安全验收。

## 实施与验收边界

1. 已修改本地与 Azure 的预览路由、URL 生成和环境校验，移除每项目 Host 匹配与 wildcard 域依赖；保留服务端项目归属校验。Azure 现有旧镜像仍是健康模式，不能将本地实现写成已上线功能。
2. 已在预览 HTML 注入受控项目 UUID，模板 `src/hooks/generatedAppStorage.ts` 提供前缀读写；CodeLoop 提示和源码校验禁止生成源码直接访问浏览器存储。历史无前缀版本不在同源预览中执行；用户可基于旧版的合并规格重新生成，新版通过后才可预览。旧 origin 数据不自动迁移。
3. 浏览器实测同项目跨版本、刷新/重进和回滚后的键读回；A/B 项目正常路径不串写、禁用 `clear()`；另用受控脚本证明同源跨项目读取与 Key 读取风险，记录为**已知安全边界**，不得标为“隔离通过”。
4. Azure Container Apps 默认 HTTPS FQDN 可以作为工作台与共享预览的访问域；仍需 Azure SQL 连通、入口访问限制、真实模型/构建/预览及重启恢复验收。SQL 防火墙与域名决策相互独立。

## 依据

- [MDN Web Storage](https://developer.mozilla.org/en-US/docs/Web/API/Web_Storage_API/Using_the_Web_Storage_API)：同一 origin 的页面共享 `localStorage`。
- [MDN iframe](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)：同源 iframe 同时使用 `allow-scripts` 和 `allow-same-origin` 不构成可靠 sandbox。
- [Azure Container Apps ingress](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview)：容器应用自带 HTTPS FQDN。

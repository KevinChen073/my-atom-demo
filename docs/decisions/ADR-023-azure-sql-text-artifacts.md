# ADR-023：Azure SQL 保存交付版本的文本文件

- 状态：Accepted（2026-11-01；schema v2 定义初始版本文件表；路径排序规则已由 [ADR-030](ADR-030-azure-sql-case-sensitive-version-paths.md) 与 schema v3 补充）
- 取代：[ADR-022](ADR-022-ephemeral-azure-demo-artifacts.md) 中“交付文件丢失可接受”的决定；继续取代 [ADR-020](ADR-020-azure-files-trusted-demo.md) 的 Azure Files 条款。[ADR-021](ADR-021-azure-sql-platform-state.md) 的 Azure SQL 平台状态决定继续有效。
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[部署说明](../AZURE-PERSISTENCE.md)、[验收](../../tests/cases/DEPLOYMENT-AZURE.md)、[交付物版本边界](ADR-004-generated-deliverable-boundaries.md)

## 背景与目标

用户要求单容器、不挂载外部文件，同时恢复交付版本在容器重启后的可预览和可回滚能力。固定 React + TypeScript + Vite 模板的受控源码、构建后的 HTML/JS/CSS/SVG、依赖锁和说明文件可作为 UTF-8 文本保存。平台项目、run、checkpoint、版本指针及异常已决定使用 Azure SQL。将版本文本也存入同一数据库，省去 Azure Files 或 Blob 的额外资源与配置。

## 决定

1. **数据归属**：Azure SQL 是交付版本文件的权威存储。新增 `version_files` 表，主键为 `(version_id, path)`，每行保存相对路径、UTF-8 文本内容（`NVARCHAR(MAX)`）、UTF-8 字节数、SHA-256、用途（source/dist）及 MIME 类型。版本 manifest 和 `active_version_id` 仍在现有表。字段、索引、迁移版本与权限由显式 Azure SQL schema v2 迁移定义；v1 部署不得声称文件已持久化。
2. **文件边界**：只保存模板受控源码、`package.json`、`package-lock.json`、`README.md`、`index.html`、构建后的文本静态资源及必要的文本测试摘要。允许的文本扩展名为 `.tsx`、`.ts`、`.js`、`.css`、`.html`、`.json`、`.md`、`.svg`、`.txt`；最多 **64 个文件、单文件 512 KiB、每版本 UTF-8 总量 2 MiB**。按 UTF-8 字节数计限，严格解码，拒绝二进制、路径穿越和越界文件；不保存 `node_modules`、npm 缓存、临时工作区或完整构建日志。现有生成文件数与大小限制继续适用。超过上限时构建结果给出明确原因而不入库。以后若交付物需要二进制资产，须单独变更决策。
3. **构建与提交**：`/app/data` 只作可删除的工作区和候选缓存。源码检查、Vite 构建与静态探针在此完成。通过后，服务端以严格 UTF-8 读取候选文件、校验路径和 hash，在**同一个 Azure SQL 事务**写入 `versions`、全部 `version_files`、当前版本指针、必要事件和最多 5 版的淘汰操作。任一文件或数据库写入失败则整体回滚，旧版保持可用；提交完成后容器文件可清理。
4. **读取与回滚**：工作台代码视图按版本和路径从数据库读源码；预览网关根据版本和请求路径直接读取 `dist/` 文本并返回正确 MIME/CSP，不依赖本地文件。迭代的 Prepare 从数据库读取基线源码，校验 hash 后重建临时工作区。回滚仅在事务中切换 `active_version_id`，无需复制文件。第 6 个成功版本淘汰最旧的非当前版本及其文件行；失败候选不占名额。
5. **恢复**：容器重启后，已提交版本、源码、预览资源与指针从 Azure SQL 恢复。尚未提交的临时工作区/候选可能丢失；恢复器必须辨认缺失缓存，基于 checkpoint 可重建时重建，否则明确失败并让用户重新运行，不能把未完成候选当作可用版本。数据库断连时不静默回退到容器文件。
6. **部署边界**：维持单 API 容器、单副本/worker 和受信访问。生成代码仍在持有数据库连接与模型密钥的主容器执行，**不构成安全沙箱**。独立异常后台仍为单独部署，只读脱敏视图，不读取 `version_files`。Azure SQL 的存储、备份与请求费用需按实际文件量核算。

## 实施顺序与验收

1. 实施 schema v2、事务级版本写入和 5 版清理；用失败注入验证不能出现只有指针或只有部分文件的版本。
2. 将预览、代码读取和新 run 基线读取切到数据库；验证容器文件目录清空后仍能预览、回滚、迭代。
3. 验证空库迁移、v1→v2 迁移、SQL 断连、并发提交、大小上限、hash 不匹配、路径穿越、跨项目授权、容器重启后的读回及 Azure SQL 成本。未完成前 `azure_demo` 只可视为**架构候选**，不能宣称持久化版本已交付。

若旧 schema v1 已有只在容器磁盘保存的 `versions` 行，迁移不能凭元数据补出源码。迁移必须先检测并报告这些行，要求从仍存在的文件完成一次性受控导入并核对 hash；文件已丢失时，将旧行标记为不可用且不得作为当前指针，不能假造成功版本。

参考：[Azure SQL `nvarchar(max)`](https://learn.microsoft.com/en-us/sql/t-sql/data-types/nchar-and-nvarchar-transact-sql)、[Azure SQL 事务](https://learn.microsoft.com/en-us/sql/t-sql/language-elements/begin-transaction-transact-sql)、[Container Apps 存储生命周期](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)。

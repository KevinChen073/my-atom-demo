# ADR-022：Azure 受信演示改用容器临时文件

- 状态：Superseded by [ADR-023](ADR-023-azure-sql-text-artifacts.md)（2026-11-01；用户随后决定将交付版本文本保存到 Azure SQL）。以下仅保留短暂过渡方案的历史记录，不再作为当前目标。
- 修订：[ADR-020](ADR-020-azure-files-trusted-demo.md) 的 Azure Files、挂载门禁及文件恢复承诺；[ADR-021](ADR-021-azure-sql-platform-state.md) 的第 5 条。两者关于 Azure SQL、同容器构建与受信访问的其他边界继续适用。
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[部署说明](../AZURE-PERSISTENCE.md)、[验收](../../tests/cases/DEPLOYMENT-AZURE.md)

## 决定

1. Azure 受信演示维持单个主 API 容器、单副本和单 worker；不配置 Azure Files、Blob 或其他外部文件挂载。`MYATOM_DATA_DIR=/app/data` 使用容器自身可写文件系统，存放工作区、候选、源码、构建文件和 npm 缓存。启动只验证目录可写，不要求挂载。
2. 项目、run、事件、异常、预览票据和 LangGraph checkpoint 仍存 Azure SQL。数据库的持久性**不代表交付文件持久**：容器关闭、重启、替换或重新部署后，`/app/data` 的文件可能全部消失；单副本也不改变此性质。[Container Apps 存储说明](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)把容器文件系统列为临时存储。
3. 可用版本最多 5 个的规则仅对**当前仍存在的文件**成立。Azure 启动时核对版本 `dist/index.html`，移除文件缺失的可用版本入口和当前指针，保留 run、事件和异常记录，并写入 `version_unavailable` 事件。旧源码不能预览、回滚或作为下一轮迭代基线；用户须重新生成。不能把这一模式称作“交付物跨重启持久化”。浏览器 `localStorage` 可能仍保留业务数据，但没有旧代码时无法保证继续使用。
4. 候选先在同一临时文件系统完成源码检查、构建和静态探针，再写入不可变目录，最后提交 Azure SQL 版本指针。若容器中途退出，候选与工作区可能丢失；恢复流程只能依据 Azure SQL 的记录判定并提示重新生成，不能假称无损续跑。缺文件的版本不得进入回滚列表。
5. 受信访问和代码执行风险不变：生成代码与主 API 同容器，没有安全沙箱；只允许获授权评审使用。该取舍用于低成本短期演示，不满足笔试题对交付物跨部署持续可用的完整目标。若恢复该目标，须重新选择持久文件方案并取得用户确认。

## 验收与风险

- 验证当前容器内生成、预览、刷新、切换和最多 5 版回滚；验证容器重启后 Azure SQL 项目与 checkpoint 仍在，文件缺失版本从可用列表移除，不能返回失效预览 URL，且可以从空基线创建新 run。
- 真实 Azure SQL、域名、访问限制、模型调用和容器重启行为仍需现场测试。当前本地测试只能验证目录门禁和版本对账逻辑；不代表 Azure 已部署。

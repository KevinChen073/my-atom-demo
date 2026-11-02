# ADR-028：本地与 Azure 都在浏览器保存模型 Key

- 状态：Accepted（2026-11-02，用户在 Azure SQL 冒烟后明确要求线上线下都支持）；取代 [ADR-025](ADR-025-browser-model-settings.md) 中 Azure 仅页面内存保存和加载时删除保存键的决定，并更新 [ADR-026](ADR-026-shared-origin-project-storage.md) 的风险边界。本地 `.env` Key 预填规则后由 [ADR-033](ADR-033-model-key-no-default.md) 取代。
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[模型与存储 TC](../../tests/cases/MODEL-AND-STORAGE.md)、[共享预览 TC](../../tests/cases/SHARED-ORIGIN-PREVIEW.md)。

## 决定

本地 loopback 与 Azure 工作台使用相同的模型设置行为：用户点击“保存”后，服务类型、API Key、Base URL 和模型名写入**当前浏览器、当前工作台 origin** 的 `localStorage` 键 `myatom.model-config.v1`；刷新后恢复。点击“清除 Key”删除整个保存键，并清除本页活动配置。测试连接只发一次探针请求，不自动保存。浏览器拒绝写入或删除时明确提示失败，不宣称已经保存或清除。

按 ADR-033，所有环境的模型默认值接口均不返回 `MODEL_API_KEY`；普通模式初始 Key 为空。用户明确保存过的 Key 可从 `localStorage` 恢复，线上/本地行为一致。主 API 仅在运行所需的进程内存中使用用户 Key，不将其写入平台数据库、checkpoint、日志、异常中心或生成文件。`localStorage` 不跨浏览器、设备或 origin 同步；浏览器清理站点数据后须重新填写。

## 已知风险与范围

工作台与生成应用预览共用 origin。任何在该 origin 执行的预览脚本都可能读取 `myatom.model-config.v1`，包括刷新后；项目 ID 键前缀无法阻止这一点。界面明确提示此风险与清除入口。本决定只适用于入口受限的受信演示，**不把保存到浏览器称作安全凭证隔离**；不使用真实敏感业务数据进行预览测试。未来若开放不受信用户或代码，须建立独立预览 origin/执行隔离，并重新设计凭证边界。

## 验收

在本地与 Azure 分别使用虚构测试 Key：保存、刷新、确认设置恢复；清除、刷新、确认键不存在；禁止浏览器存储时确认保存失败可见。确认两端默认值接口均不下发服务器 Key。用受控预览脚本证明同源读取风险并在结束后清除测试 Key；不得将该结果标为隔离通过。真实模型调用另行用用户提供的测试 Key 验证。

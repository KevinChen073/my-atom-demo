# ADR-033：普通模式不提供默认 API Key

- 状态：Accepted（2026-11-02，用户明确要求）
- 修订：[ADR-025](ADR-025-browser-model-settings.md)、[ADR-028](ADR-028-browser-model-key-both-environments.md) 中本地 `.env` Key 预填规则。
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[模型与存储 TC](../../tests/cases/MODEL-AND-STORAGE.md)。

## 决定

普通模式的 API Key 输入框默认空白。本地和线上 `/api/model/defaults` 只返回非密钥的服务类型、Base URL、模型名，不返回 `MODEL_API_KEY`；前端也不把默认值接口中的 Key 自动设置为活动凭证。用户明确输入并保存的 Key 继续按 ADR-028 从当前浏览器 `localStorage` 恢复，这属于用户配置，不是默认 Key。

服务端 `MODEL_API_KEY` 只供**已经验证邀请码、且本轮选择平台测试额度**的 run 使用。普通模式即使本地 `.env` 存在该变量，也必须提供用户自己的 Key；模型网关不能静默回退到环境 Key。未提供凭证时，在创建 run 前给出明确错误。邀请码模式不向浏览器返回服务端 Key，额度与权限检查维持不变。

## 验收

本机 loopback、非本机和 Azure 默认值接口均返回空 Key；本地设置了 `MODEL_API_KEY` 但不带用户 Key 时，run 创建被拒且不产生运行记录；历史用户自存 Key 仍可恢复并使用；持码任务可使用平台额度，未授权任务不能调用服务器 Key。

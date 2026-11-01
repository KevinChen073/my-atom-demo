# ADR-025：访客自行配置模型，本地可保存 Key

- 状态：Accepted（2026-11-01，用户先选择本地浏览器保存方案，后明确选择 Azure 仅页面会话保存）；更新 [ADR-014](ADR-014-atoms-deployment-and-model-credentials.md) 的第 3、4 条模型凭证边界。
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[根目录约束](../../AGENTS.md)。

> 2026-11-01 修订：[ADR-026](ADR-026-shared-origin-project-storage.md) 取消每项目独立预览 origin 后，用户确认 Azure 不再将 Key 存入浏览器 `localStorage`；本地 loopback 仍可保存。Azure 旧版本留下的该键在工作台加载时删除。此举减少持久泄露面，但同源预览脚本仍可接触父页面和同源接口；仅可用于限制入口的受信演示。

## 决定

工作台提供 DeepSeek / OpenAI 兼容服务、API Key、Base URL 和模型名设置。访客自行输入。本地 loopback 工作台可将设置存到当前浏览器 `localStorage`，清除 Key 时删除保存值；Azure 工作台只在当前页面会话的 JavaScript 内存中保留设置，整页刷新或关闭后须重新填写。Azure 页面加载时清理历史的 `myatom.model-config.v1` 保存键。本地 `APP_ENV=local` 且请求源与工作台 Host 均为本机 loopback 时，可从 `.env` 的 `MODEL_API_KEY` 回填设置输入框；线上接口永不返回服务器 Key。`.env` Key 是本地便捷默认值，不再是所有用户生成任务的唯一凭证。

正常工作台代码只把 Key 发送到主 API；主 API 将当前 run 的 Key 保存在进程内存，不写入项目、数据库、checkpoint、日志或异常中心。数据库只记 provider、Base URL、模型名和“需要用户 Key”标记。进程重启时活动 run 等待浏览器重新提交 Key 后继续；Azure 整页刷新后用户须重填。工作台文案必须说明会话边界。共享 origin 的生成脚本仍可能在当前页面运行时接触父页面或接口；不得宣称 Key 已与生成代码安全隔离。

模型测试由用户主动触发，向所选模型发送极短探针请求。通用 OpenAI 兼容服务不传 DeepSeek 专有的 `thinking` 参数。上线前仍需完成不同服务的实测兼容性、工作台脚本安全和重启恢复验收。

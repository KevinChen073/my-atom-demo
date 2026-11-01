# ADR-025：访客自行配置模型，允许浏览器保存 Key

- 状态：Accepted（2026-11-01，用户明确选择截图方案）；更新 [ADR-014](ADR-014-atoms-deployment-and-model-credentials.md) 的第 3、4 条模型凭证边界。
- 关联：[PRD](../PRD.md)、[架构](../ARCHITECTURE.md)、[根目录约束](../../AGENTS.md)。

## 决定

工作台提供 DeepSeek / OpenAI 兼容服务、API Key、Base URL 和模型名设置。访客自行输入并可选择在当前浏览器 `localStorage` 保存；清除 Key 会删除浏览器保存值。本地 `APP_ENV=local` 且请求源与工作台 Host 均为本机 loopback 时，可从 `.env` 的 `MODEL_API_KEY` 回填设置输入框；线上接口永不返回服务器 Key。`.env` Key 是本地便捷默认值，不再是所有用户生成任务的唯一凭证。

浏览器只把 Key 发送到主 API；主 API 将当前 run 的 Key 保存在进程内存，不写入项目、数据库、checkpoint、日志或异常中心。数据库只记 provider、Base URL、模型名和“需要用户 Key”标记。进程重启时活动 run 等待浏览器重新提交 Key 后继续；如果浏览器本地存储已被清除，用户须重新输入。浏览器存储并非安全保险箱，共用设备或脚本被注入时存在泄露风险；工作台文案必须明确告知。

模型测试由用户主动触发，向所选模型发送极短探针请求。通用 OpenAI 兼容服务不传 DeepSeek 专有的 `thinking` 参数。上线前仍需完成不同服务的实测兼容性、工作台脚本安全和重启恢复验收。

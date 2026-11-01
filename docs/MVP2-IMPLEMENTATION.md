# MVP2 本地落地映射

状态：2026-10-31 本地开发实现；范围依 [PRD](PRD.md) 与 [架构](ARCHITECTURE.md)，变更规则见 [ADR-002](decisions/ADR-002-change-control.md)。用例见 [MVP2 TC](../tests/cases/MVP2.md)，实测过程留在本机 `D:\AI\ATOM笔试\docs\MVP2-VERIFICATION.md`。

**历史实施记录**：本页描述当时实际实现的服务端 `AppDataService`/SQLite，不代表用户随后确认的目标边界。2026-11-01 已迁移为每项目独立预览 origin 的 `localStorage`、候选检查及最多 5 个可用快照；实际浏览器业务交互与公网域名仍需复测。最新边界见 [ADR-004](decisions/ADR-004-generated-deliverable-boundaries.md)。

## 实时进度

`GET /api/runs/{run_id}/stream?after_seq=N` 从持久事件表按 `seq` 回放，随后增量发送 SSE。事件含 `schema_version=1`，15 秒空闲心跳。客户端按序号去重，断线重连只请求缺失事件；SSE 失败退回已有 `GET /events` 轮询。重连不启动新 run。

## 本地交互预览

已保存版本的 `dist/` 是实际 Vite 构建产物。主 API 验证访客项目权限后签发单次、两分钟票据；预览服务在 `127.0.0.1:8001` 消费票据并设置 HttpOnly、版本限定、一小时会话 cookie。主工作台位于 `127.0.0.1:8000`，iframe 使用独立 origin 和 CSP；预览仅能读取已保存版本的静态文件与该项目的受控数据实体。旧版本可预览其已保存构建产物；回看旧代码不回退业务数据。

本机没有 Docker。双端口、CSP、生成文件白名单、禁用直接网络 API 与短期会话只能限制浏览器侧能力，**不能隔离 npm 构建时的宿主进程**。因此 `APP_ENV=local` 才可启用这一路径，公开 URL、Atoms Cloud 预览或可对外执行任意生成代码的服务均未通过本轮验收。

## 生成应用数据

Build Plan 增加 `entities` 结构：实体名和 `text/number/boolean` 字段、必填标记；`id/created_at/updated_at` 由服务端提供。批准计划后，模型只写 `src/App.tsx` 与 `src/App.css`，通过固定模板 `src/appData.ts` 的 `listRecords/createRecord/updateRecord/deleteRecord` 读写。预览服务依版本 manifest 检查实体和字段，记录以项目 ID 分区保存在 `data/app_data.sqlite3`。新增请求支持 `Idempotency-Key`，同一键和同一数据的重放返回原记录，键相同而数据不同则拒绝。每实体上限 1000 条，每条请求数据最多 16 KB。不同版本共享同一项目业务数据；旧版本按其 schema 投影字段，不自动迁移或回滚数据。

## 三例冒烟校准

[示例目录](../examples/catalog.json) 由工作台首页直接读取；点击卡片只填入可编辑的需求草稿。三个需求覆盖番茄钟待办、带三套皮肤的点击游戏、移动点单 Web/H5。可主动运行单例真实模型检查 `python -m tests.live_examples_smoke --id <example_id>`；脚本在批准计划前检查各例关键功能和持久化实体，构建后检查受控预览入口与数据接口。浏览器业务验收另按 [示例 TC](../tests/cases/EXAMPLES.md) 执行，过程证据见本机 `D:\AI\ATOM笔试\docs\EXAMPLE-CALIBRATION-VERIFICATION.md`。

游戏冒烟暴露快速连点时“本轮 12 分、持久最高分 11 分”的漏写。生成提示因此要求按最终回合分数一次结算；Runner 对常见 `setState` 更新函数中的保存调用或嵌套状态更新加源码门禁，违规代码交由有限的模型纠正循环。该检查只覆盖可识别的源码模式，不能替代浏览器里的快速连点测试。移动点单的后端能力限受控 `orders` CRUD 和字段类型校验；商品价格由生成前端计算，不具备可信服务端价格校验或支付能力。

## 未验证边界

- 本机进程与宿主共享权限；公开部署必须替换 Runner/PreviewGateway 并重新做隔离测试。
- Atoms 的 Python 常驻服务、生产 SSE、生产数据迁移、代码导入和安全预览仍以本机 `D:\\AI\\ATOM笔试\\docs\\ATOMS-SPIKES.md` 的实测状态为准；未把阻断项改写为通过。
- 真实模型对任意需求的 schema 与生成代码质量需逐例验证；自动构建成功不等于浏览器业务流程通过。

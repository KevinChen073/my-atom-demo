# 结构化决策卡与单一发送验收

依据：[ADR-010](../../docs/decisions/ADR-010-structured-card-single-send.md)、[ADR-011](../../docs/decisions/ADR-011-decision-turn-composer.md)、[讨论记录](../../docs/DESIGN-DISCUSSION-STRUCTURED-DECISION-SINGLE-SEND.md)。执行时记录环境、代码版本、输入、实际结果、消息/事件证据和截图；本表的“未执行”不代表失败。

| ID | 操作与输入 | 预期 | 当前证据 |
| --- | --- | --- | --- |
| SD-01 | 澄清卡显式选齐必答，卡下文字留空发送 | 卡内无确认按钮；答案入库，ClarityGate 决定下一步 | `tests/test_single_send.py` 自动化 |
| SD-02 | 漏必答；可选题留空；同时发修改需求及旧卡答案 | 漏必答不确认；可选不阻断；修改优先，旧卡不隐式确认 | `tests/test_single_send.py` 阶段门禁；组合消息待补 |
| SD-03 | 计划发“把首页改成绿色，然后按这版计划开始生成” | 只出新版计划，无批准或文件写入 | `tests/test_single_send.py` 自动化 |
| SD-04 | 当前计划发“可以”“确认”“继续”或空消息 | 均不启动构建 | `tests/test_single_send.py` 测三条含糊语句；空消息 API 422 待单测 |
| SD-05 | 当前计划发“按这版计划开始生成” | 只批准当前版本一次，之后才 Prepare | `tests/test_single_send.py` 自动化 |
| SD-06 | 用旧卡引用批准新版本 | 409，旧草稿保留，新卡可核对 | `tests/test_single_send.py` 自动化；UI 待人工复核 |
| SD-07 | 带跨设备同步条件的问题与批准混发 | 回答 localStorage 边界，继续等确认，不构建 | `tests/test_single_send.py` 自动化 |
| SD-08 | 构建失败依次明确要求再修、指定方向、原样重建；试“继续”及互斥混写 | 只允许当前卡白名单内的一次动作；含糊及互斥不执行，环境故障不改码 | `tests/test_single_send.py` 测环境白名单/互斥；完整失败链路待执行 |
| SD-09 | 同键相同/不同载荷；两标签不同键抢同卡 | 相同重放同一结果；冲突 409；最多一个有效决定 | `tests/test_single_send.py` 测同键、存储级并发；双浏览器待执行 |
| SD-10 | 发送后刷新/断线/服务重启 | 原文、解释结果和卡状态可读；不重复执行 | `tests/test_single_send.py` 测持久读取与服务重启；断网未执行 |
| SD-11 | 构建中写草稿、切换右栏及项目再返回 | 已批准 spec 不变；草稿不混项目；不隐式新建 run | 待浏览器执行 |
| SD-12 | 键盘完成澄清、计划修改与批准；检查 1280×720、1366×768、1440×900 | 当前卡与唯一输入区位于同一 Agent 对话；三视口可达，焦点、文字状态、错误清晰 | `test_feedback_regression.py` 测三视口与计划阶段 Tab 顺序；完整键盘流程待执行 |
| SD-13 | 在计划卡输入文字，按 Shift+Enter，再按 Enter | 只显示 `n/2000` 形式的字数，无“关联当前计划卡”；Shift+Enter 换行不提交，Enter 恰好提交一次 | `test_feedback_regression.py` 浏览器自动化 |

2026-11-01 本地执行：将测试临时目录设在 `D:\projects\my-atom-demo\data\test-temp` 后，`pytest tests -q` **64 通过**；`web/npm run build` 通过；`git diff --check` 通过。浏览器用隔离的本地服务与 FakeModel 验证了 1280×720、1366×768、1440×900 三个桌面视口；ADR-011 交互修订后执行 `test_feedback_regression.py` **6 通过**，并在本机计划等待页观察了卡片与输入区同处一条 Agent 对话、计划详情默认收起及 `0/2000` 计数。随后对输入标签与计划选择后的焦点做了微调，构建通过；这两项微调后的浏览器回归按用户要求暂停。此前一次全量运行因 C 盘临时目录耗尽而失败，该结果不能算产品缺陷或功能通过；重跑后通过。SD-08 完整失败链路、SD-10 真实断网、SD-11 跨项目草稿和公开环境仍待执行，不以本地通过代替在线验收。

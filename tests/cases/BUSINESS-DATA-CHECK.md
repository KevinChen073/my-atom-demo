# TC：生成应用业务数据保存检查

适用：新生成版本或迭代版本。计划与源码使用固定 React + TypeScript + Vite 模板，业务数据仅通过 `generatedAppStorage` 写入当前浏览器的 `localStorage`。参见 [ADR-034](../../docs/decisions/ADR-034-business-data-source-gate.md)。

| Case | 操作 | 预期 |
| --- | --- | --- |
| BDC-01 需求文档 | 提交可新增、编辑和删除记录的需求，完成澄清并查看计划/项目文档 | `business_data.required=true`；列明要保存的字段、存储位置、刷新读回与写入失败验收、浏览器及回滚边界 |
| BDC-02 缺少接线 | 候选仅使用 React 页面状态，或只有 `getItem`/只有 `setItem` | `BusinessDataCheck` 报具体缺项和文件，不能进入构建或提交版本；可修复时只重生目标文件 |
| BDC-03 接线完整 | 候选有适配器 `getItem` 与 `setItem` | 源码级检查通过，事件、manifest 与测试卡记录 `source_contract_only`；浏览器检查仍标未执行 |
| BDC-04 静态页面 | 计划明确无需跨刷新保存的业务数据 | 检查为不适用，不强制写入浏览器存储 |
| BDC-05 真正保存 | 在独立测试浏览器中新增业务记录、刷新、重进同项目预览；再模拟拒绝浏览器存储 | 数据读回与计划一致；失败提示明确且不宣称已保存。记录浏览器、版本 ID、操作结果和失败证据。源码级通过不能代替此项 |
| BDC-06 旧版 | 打开本功能实施前保存的版本 | 不追溯改写 manifest；需求文档和测试页提示缺少检查记录，不能宣称历史数据已保存 |
| BDC-07 键名兼容 | 生成订单应用，使用 `order-demo:orders` 读写；再把同文件常量改为 `order-demo/orders` | 前者在项目命名空间内可写可读；后者在源码检查时定位文件并要求修复，不把非法键名误报成浏览器禁用存储 |

自动化：`tests/test_business_data_check.py` 覆盖文档结构、源码接线与工作流回退；BDC-05 仍须按具体生成应用进行浏览器冒烟。

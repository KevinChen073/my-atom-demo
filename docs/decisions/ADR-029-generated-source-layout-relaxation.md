# ADR-029：放宽生成源码的状态布局限制

- 状态：Accepted（用户于 2026-11-02 明确要求）
- 关联：[PRD](../PRD.md)、[系统架构](../ARCHITECTURE.md)、[ADR-002](ADR-002-change-control.md)、[ADR-013](ADR-013-source-validation-targeted-repair.md)、[源码修复用例](../../tests/cases/MVP1.md)。

## 背景

一次人工源码修复连续收到 `src/App.tsx：状态与业务逻辑须放在 src/hooks/ 中`。该规则只按 `useState/useEffect/useReducer/useRef` 调用位置判断，即使生成的 React + TypeScript 源码可以通过构建，也会在构建前被挡住并反复重生同一文件。固定 `useAppState.ts` 及强制导入还会给简单页面增加无用跨文件接口。

## 决定

生成应用仍固定 React + TypeScript + Vite。必需生成文件改为 `src/App.tsx`、`src/app.css`、根目录 `readme.md`；`src/hooks/` 与 `src/components/` 按复杂度选用。`App.tsx` 与组件可直接使用 React 状态 Hook、事件处理和业务逻辑；不再要求强制生成、导入 `useAppState.ts`。模型提示按简单页面先完成可编译的单文件状态逻辑，复杂时再拆文件。

`ValidateSource` 只阻断文件路径/大小/数量、模板入口、导入范围、直接浏览器存储访问和禁止能力等确定性边界，以及既有状态更新函数副作用规则。项目业务数据无论代码位于 App、组件还是 hook，都必须经模板的 `generatedAppStorage` 适配器读写；该适配器文件仍不可由模型覆盖。真实 `npm run build` 中的 `tsc -b` 继续负责 TypeScript 类型与语法校验；不能为了减少修复轮次而跳过构建。

模板的 TypeScript 配置保留 `strict`，但不再把未使用局部变量或参数当作构建失败。简单需求中的无害草稿变量不应消耗模型修复轮次；类型不兼容和语法错误仍会由 `tsc -b` 报出。

源码或构建反馈仍可按文件定向修复，最多 60 轮及无进展/复现停机规则不变。历史停在人工处理的 run 不自动重启；用户可在现有修复卡明确要求继续，新的候选按本规则重新校验，旧可用版本不变。

## 验收

- 只包含三个必需文件、在 `App.tsx` 使用 `useState` 且有未使用草稿变量的应用通过源码校验、TypeScript 构建并保存版本，自动修复轮次为 0。
- `App.tsx` 经 `generatedAppStorage` 保存数据可通过源码校验；直接使用 `localStorage` 仍被阻断。
- 目录越界、外部接口、缺少 `app.css` 导入等边界仍被阻断，源码反馈与构建反馈保持区分。

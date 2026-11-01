export type BudgetKind = 'model_calls' | 'total_tokens' | 'run_seconds' | 'fix_rounds'
export type BudgetChoice = Record<BudgetKind, boolean>
export type BudgetData = {
  reason: string
  budget_kind: string
  limits: Record<BudgetKind, number>
  usage: Record<BudgetKind, number | null>
  increments: Record<BudgetKind, number>
}

const KINDS: BudgetKind[] = ['total_tokens', 'model_calls', 'run_seconds', 'fix_rounds']
const LABELS: Record<BudgetKind, string> = {
  total_tokens: '模型 Token', model_calls: '模型调用次数',
  run_seconds: 'Agent 执行时间', fix_rounds: '自动源码修复轮次',
}

function display(kind: BudgetKind, value: number): string {
  return kind === 'run_seconds' ? (value % 60 === 0 ? `${value / 60} 分钟` : `${Math.floor(value / 60)} 分 ${value % 60} 秒`) :
    kind === 'total_tokens' ? value.toLocaleString('zh-CN') : `${value} ${kind === 'model_calls' ? '次' : '轮'}`
}

export function BudgetExtensionCard({ data, choice, onChange }: {
  data: BudgetData
  choice: BudgetChoice
  onChange: (kind: BudgetKind, selected: boolean) => void
}) {
  return <div className="decision-card budget-extension-card">
    <div className="card-heading"><span className="card-overline">额度确认</span><span className="pending-badge">等待回复</span></div>
    <h3>当前任务已暂停</h3>
    <p className="budget-reason">{data.reason}</p>
    <fieldset className="budget-options"><legend>选择本次增加的额度</legend>
      {KINDS.map(kind => <label className="budget-option" key={kind}>
        <input type="checkbox" checked={choice[kind]} onChange={event => onChange(kind, event.target.checked)} />
        <span><strong>{LABELS[kind]}　+{display(kind, data.increments[kind])}</strong>
          <small>已用 {data.usage[kind] === null ? '未记录' : display(kind, data.usage[kind])} / 当前上限 {display(kind, data.limits[kind])}
            {choice[kind] ? ` → 确认后 ${display(kind, data.limits[kind] + data.increments[kind])}` : ''}</small></span>
      </label>)}
    </fieldset>
    <p className="budget-note">当前已耗尽的额度必须选中。确认后只增加选中的额度，并从当前检查点继续；已用量不会清零，等待确认不计入执行时间。</p>
  </div>
}

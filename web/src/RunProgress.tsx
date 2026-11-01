import { useEffect, useRef, useState } from 'react'

type ProgressRun = {
  id: string
  status: string
  phase: string
  fix_rounds: number
  plan?: { tasks: string[]; features?: string[] } | null
  active_elapsed_seconds?: number | null
  execution_running?: boolean | null
  elapsed_received_at?: number
}
type ProgressEvent = { seq: number; type: string; payload: Record<string, unknown> }
type StepState = 'pending' | 'active' | 'passed' | 'failed'

function latest(events: ProgressEvent[], type: string): ProgressEvent | undefined {
  return [...events].reverse().find(event => event.type === type)
}

function duration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  return [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60]
    .map(value => String(value).padStart(2, '0')).join(':')
}

function stageText(run: ProgressRun, events: ProgressEvent[]): { title: string; collected: string; next: string } {
  const clarity = latest(events, 'clarity_result')?.payload
  const confirmed = Array.isArray(clarity?.confirmed) ? clarity.confirmed as { answer?: unknown }[] : []
  const answers = confirmed.map(item => String(item.answer || '').trim()).filter(Boolean)
  const collected = answers.length ? `上一轮已确认 ${answers.length} 项：${answers.map(answer => answer.slice(0, 60)).join('；')}` : '已收到你的需求，正在确认实现所需的关键信息。'
  if (run.status === 'awaiting_clarification') return { title: '需求澄清', collected, next: '接下来：请回答当前卡片中的问题。' }
  if (run.status === 'clarifying') {
    if (run.phase === 'ClarityGate') return { title: '正在核对回答', collected: '已收到本轮回答，正在判断是否还有关键缺口。', next: '接下来：信息足够就制定计划，否则再补问关键问题。' }
    return { title: '正在梳理需求', collected, next: '接下来：提出需要你确认的关键问题。' }
  }
  if (run.status === 'planning') return { title: '正在制定计划', collected: answers.length ? collected : '需求已确认。', next: '接下来：列出实现任务与验收点，请你确认。' }
  if (run.status === 'awaiting_plan') return { title: '构建计划已就绪', collected: `计划列出 ${run.plan?.tasks?.length || run.plan?.features?.length || 0} 项拟做内容，尚未开始生成。`, next: '接下来：请确认计划或提出修改。' }
  if (run.status === 'completed') return { title: '本轮已完成', collected: '可用版本已保存；具体检查结果以本轮记录为准。', next: '后续可查看实际预览并自行试用。' }
  if (run.status === 'awaiting_repair') return { title: '本轮已暂停', collected: '检查未通过，候选源码和诊断记录已保留。', next: '接下来：由你决定继续修复或指定方向；若已构建，也可原样重建。' }
  if (['failed', 'budget_exceeded', 'cancelled'].includes(run.status)) return { title: '本轮已停止', collected: '本轮没有产生新可用版本。', next: '请查看上方的结果与处理建议。' }
  if (run.phase === 'Prepare') return { title: '正在准备应用', collected: '计划已确认。', next: '接下来：准备固定模板并生成源码。' }
  if (run.phase === 'CodeLoop') return { title: run.fix_rounds ? '正在修复源码' : '正在生成源码', collected: run.fix_rounds ? `正在进行第 ${run.fix_rounds} 轮源码修复，处理上次检查反馈。` : '正在按已确认的计划编写应用。', next: '接下来：校验生成文件，再执行构建。' }
  if (run.phase === 'ValidateSource') return { title: '正在检查源码', collected: '已收到本轮候选文件。', next: '接下来：若能定位问题文件，仅重新生成该文件；通过后开始构建。' }
  if (run.phase === 'BuildTest') return { title: '正在构建检查', collected: '源码已写入候选工作区。', next: '接下来：确认依赖安装与构建命令是否通过。' }
  if (run.phase === 'Diagnose') return { title: '正在定位构建错误', collected: '本轮构建未通过，已保留诊断记录。', next: '接下来：仅对可修复的源码问题再次生成。' }
  if (run.phase === 'PackageCandidate') return { title: '正在整理候选产物', collected: '构建检查已通过。', next: '接下来：检查预览所需的静态资源。' }
  if (run.phase === 'PreviewCheck') return { title: '正在检查预览资源', collected: '候选产物已打包。', next: '接下来：检查入口和静态文件可读性。' }
  if (run.phase === 'CommitVersion') return { title: '正在保存版本', collected: '静态预览资源检查已通过。', next: '接下来：保存可用版本并提供预览。' }
  return { title: '正在处理', collected: '已收到当前任务。', next: '接下来：同步最新处理结果。' }
}

function buildSteps(run: ProgressRun, events: ProgressEvent[]): { label: string; state: StepState; note?: string }[] {
  const files = latest(events, 'files_written')
  const build = latest(events, 'build_result')
  const preview = latest(events, 'preview_check')
  const saved = latest(events, 'completed') || latest(events, 'version_saved')
  const buildOk = build?.payload.ok === true
  const previewOk = preview?.payload.ok === true
  const fileCount = Array.isArray(files?.payload.files) ? files.payload.files.length : 0
  const commands = Array.isArray(build?.payload.steps) ? build.payload.steps as { command?: string; exit_code?: number | null }[] : []
  const commandResult = commands.map(step => `${step.command || '构建命令'} ${step.exit_code === 0 ? '通过' : step.exit_code === null ? '环境故障' : '失败'}`).join('；')
  const checkedAssets = Number(preview?.payload.checked_assets || 0)
  return [
    { label: '生成源码', state: run.phase === 'CodeLoop' || run.phase === 'ValidateSource' ? 'active' : files ? 'passed' : latest(events, 'source_validation_failed') ? 'failed' : run.phase === 'Prepare' ? 'active' : 'pending', note: files && run.phase !== 'CodeLoop' ? `${fileCount} 个文件已写入` : undefined },
    { label: '构建检查', state: run.phase === 'BuildTest' ? 'active' : buildOk ? 'passed' : build ? 'failed' : 'pending', note: commandResult || undefined },
    { label: '静态预览资源检查', state: run.phase === 'PreviewCheck' ? 'active' : previewOk ? 'passed' : preview ? 'failed' : 'pending', note: previewOk ? `入口与 ${checkedAssets} 项静态资源可读；浏览器交互未检查` : preview ? String(preview.payload.reason || '静态资源检查未通过') : undefined },
    { label: '保存可用版本', state: saved ? 'passed' : run.phase === 'CommitVersion' ? 'active' : 'pending' },
  ]
}

export function RunProgress({ run, events, connected }: { run: ProgressRun; events: ProgressEvent[]; connected: boolean }) {
  const [now, setNow] = useState(Date.now())
  const lastDisplayed = useRef({ runId: run.id, elapsed: run.active_elapsed_seconds || 0 })
  const isWorking = ['clarifying', 'planning', 'building'].includes(run.status)
  const isWaiting = ['awaiting_clarification', 'awaiting_plan'].includes(run.status)
  const isFinished = !isWorking && !isWaiting
  useEffect(() => {
    if (!run.execution_running || !connected || isFinished) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [run.execution_running, connected, isFinished])
  const serverBasedElapsed = (run.active_elapsed_seconds || 0) + (run.execution_running && connected && run.elapsed_received_at ? Math.max(0, now - run.elapsed_received_at) / 1000 : 0)
  if (lastDisplayed.current.runId !== run.id) lastDisplayed.current = { runId: run.id, elapsed: run.active_elapsed_seconds || 0 }
  if (connected) lastDisplayed.current.elapsed = serverBasedElapsed
  const elapsed = connected ? serverBasedElapsed : lastDisplayed.current.elapsed
  const hasElapsed = typeof run.active_elapsed_seconds === 'number' && Number.isFinite(run.active_elapsed_seconds)
  const timeLabel = !hasElapsed ? isWorking ? '执行时间同步中' : '执行时间未记录'
    : isFinished && elapsed < 0.001 ? '执行时间未记录' : `执行 ${duration(elapsed)}`
  const stage = stageText(run, events)
  const planned = run.plan?.tasks?.length ? run.plan.tasks : run.plan?.features || []
  const body = <>
    <div className="run-progress-head"><strong aria-live={isWorking ? 'polite' : undefined}>{stage.title}</strong><span title="仅累计 Agent 实际执行，等待你回复的时间不计入">{timeLabel}</span></div>
    <p>{stage.collected}</p><p className="run-progress-next">{stage.next}</p>
    {planned.length && (run.status === 'building' || isFinished) ? <details className="run-plan-outline"><summary>计划要做什么 · {planned.length} 项</summary><ul>{planned.map((task, index) => <li key={index}>{task}</li>)}</ul></details> : null}
    {(run.status === 'building' || (isFinished && run.plan)) && <div className="run-checks"><span className="run-checks-title">实际执行与检查</span><ul>{buildSteps(run, events).map(step => <li key={step.label} className={`run-step ${step.state}`}><span aria-hidden="true">{step.state === 'passed' ? '✓' : step.state === 'failed' ? '!' : step.state === 'active' ? '●' : '○'}</span><div><strong>{step.label}</strong>{step.note && <small>{step.note}</small>}</div></li>)}</ul></div>}
  </>
  if (isFinished) return <details className="run-progress-fold"><summary>查看本轮处理过程 · {timeLabel}</summary>{body}</details>
  return <div className={`agent-message current run-progress ${isWaiting ? 'waiting' : ''}`}>{body}</div>
}

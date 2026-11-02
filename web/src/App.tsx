import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useColumnLayout } from './useColumnLayout'
import { RunProgress } from './RunProgress'
import { BudgetExtensionCard } from './BudgetExtensionCard'
import type { BudgetChoice, BudgetData, BudgetKind } from './BudgetExtensionCard'
import { withRunElapsed } from './runElapsed'
import { ModelSettings } from './ModelSettings'
import type { InviteSession } from './ModelSettings'
import { currentModelConfig, modelRequestHeader, setPlatformModel } from './modelConfigStore'
import type { ModelConfig } from './modelConfigStore'
import { canSubmitNewRunRequest } from './requestValidation'
import catalog from '../../examples/catalog.json'
import brandLockup from '../../design/v3/icons/brand-lockup.svg'
import brandMark from '../../design/v3/icons/brand-mark.svg'
import workbenchIcon from '../../design/v3/icons/workbench.svg'
import overviewIcon from '../../design/v3/icons/overview.svg'
import docsIcon from '../../design/v3/icons/docs.svg'
import testsIcon from '../../design/v3/icons/tests.svg'
import versionsIcon from '../../design/v3/icons/versions.svg'

type Example = (typeof catalog.examples)[number]

type Question = { id: string; text: string; default: string; required: boolean }
type Clarification = { summary: string; assumptions: string[]; questions: Question[] }
type PlanEntity = { name: string; fields: { name: string; type: 'text' | 'number' | 'boolean'; required: boolean }[] }
type Plan = { title: string; pages: { name: string; purpose: string }[]; features: string[]; data_model: string[]; entities?: PlanEntity[]; acceptance: string[]; tasks: string[]; limitations: string[]; template: string; change_set?: { retained: string[]; modified: { before: string; after: string }[]; removed: string[]; added: string[] } }
type FileInfo = { path: string; sha256: string; bytes: number }
type BuildStep = { command: string; exit_code: number; seconds: number }
type FailureSummary = { stage?: 'source_validation' | 'build'; cause: string; latest_error: string; command: string; automatic_repairs: number; total_attempts?: number; attempts: { number: number; command: string; error: string }[]; evidence_ref: string }
type Card = { type: string; schema_version: number; card_id: string; run_id: string; status: string; payload: Clarification & Plan & Partial<BudgetData> & { version_id?: string; build?: { ok: boolean; steps: BuildStep[] }; files?: FileInfo[]; browser_check?: string; diagnostics?: string; diagnostics_ref?: string; diagnosis?: { category: string; command: string; evidence_ref: string; repairable: boolean; reason: string }; failure_summary?: FailureSummary; failure_stage?: 'plan' | 'source_validation' | 'build' | 'commit_version'; failure_reason_code?: string; recovery_blocker?: string; manual_rounds?: number }; actions: string[] }
type Run = { id: string; project_id: string; request_text: string; status: string; phase: string; card: Card | null; card_id: string | null; spec_version: number; approved_spec_version: number | null; plan?: Plan | null; model_calls: number; tokens_used: number; fix_rounds: number; error: string | null; version_id: string | null; trace_id: string; created_at: string; updated_at: string; active_elapsed_seconds?: number | null; execution_running?: boolean | null; needs_model_key?: boolean; active_seconds?: number | null; execution_started_at?: string | null; elapsed_received_at?: number }
type Version = { id: string; project_id: string; run_id: string; manifest: { files: FileInfo[]; build: { ok: boolean; steps: BuildStep[] }; template: string; preview: { status: string } | null; entities?: PlanEntity[] }; created_at: string }
type Decision = { id: string; run_id: string; card_id: string; spec_version: number; action: string; payload: { answers?: Record<string, string>; request_text?: string; feedback?: string } & Partial<Record<BudgetKind, number>>; created_at: string }
type Submission = { id: string; run_id: string; card_id: string; spec_version: number; text: string; answers: Record<string, string>; status: 'interpreting' | 'needs_clarification' | 'committed' | 'rejected'; reply: string; committed_action: string | null; decision_id: string | null; created_at: string }
type Project = { id: string; title: string; created_at: string; updated_at: string; active_version_id: string | null; runs: Run[]; versions: Version[]; decisions: Decision[] }
type ProjectSummary = Pick<Project, 'id' | 'title' | 'updated_at'> & {
  latest_status: string | null
  latest_phase: string | null
  latest_version_id: string | null
}
type Event = { run_id: string; seq: number; event_id: string; type: string; payload: Record<string, unknown>; at: string }
type RightView = 'workbench' | 'overview' | 'documents' | 'tests' | 'versions'
type PreviewResponse = { url: string; expires_at: string }

const REQUEST_DRAFTS_KEY = 'myatom.request-drafts.v1'
const DECISION_DRAFTS_KEY = 'myatom.decision-drafts.v1'
const MESSAGE_KEYS_KEY = 'myatom.message-keys.v1'
type DecisionDraft = { answers: Record<string, string>; editedRequest: string; feedback: string }
type MessageKey = { id: string; payload: string }
const isTextDraft = (value: unknown): value is string => typeof value === 'string' && value.length <= 5000
function isMessageKey(value: unknown): value is MessageKey {
  if (!value || typeof value !== 'object') return false
  const key = value as Record<string, unknown>
  return typeof key.id === 'string' && /^[0-9a-f-]{36}$/i.test(key.id)
    && typeof key.payload === 'string' && key.payload.length <= 12000
}
function isDecisionDraft(value: unknown): value is DecisionDraft {
  if (!value || typeof value !== 'object') return false
  const draft = value as Record<string, unknown>
  return typeof draft.editedRequest === 'string' && draft.editedRequest.length <= 5000
    && typeof draft.feedback === 'string' && draft.feedback.length <= 5000
    && !!draft.answers && typeof draft.answers === 'object' && !Array.isArray(draft.answers)
    && Object.values(draft.answers).every(answer => typeof answer === 'string' && answer.length <= 500)
}
function readSessionDrafts<T>(key: string, isDraft: (value: unknown) => value is T): Record<string, T> {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    const drafts: Record<string, T> = {}
    for (const [draftKey, draft] of Object.entries(value)) {
      if (draftKey.length <= 200 && isDraft(draft)) drafts[draftKey] = draft
    }
    return drafts
  } catch { return {} }
}
function saveSessionDrafts<T>(key: string, drafts: Record<string, T>) {
  try { sessionStorage.setItem(key, JSON.stringify(drafts)) } catch { /* A full or disabled store must not block editing. */ }
}

const STATUS: Record<string, string> = {
  clarifying: '正在梳理需求', awaiting_clarification: '等待需求确认', planning: '正在拟定计划',
  awaiting_plan: '等待计划确认', awaiting_repair: '等待你决定如何处理', awaiting_budget: '等待额度确认', building: '正在生成代码', completed: '代码已保存', failed: '需要处理',
  cancelled: '已取消', budget_exceeded: '额度已达上限',
}
const PHASE: Record<string, string> = {
  Clarify: '需求澄清', WaitClarify: '需求确认', ClarityGate: '核对回答', Plan: '制定计划', WaitPlan: '计划确认',
  Prepare: '准备模板', CodeLoop: '编写代码', ValidateSource: '检查源码', BuildTest: '构建与测试', Diagnose: '诊断修复',
  PackageCandidate: '整理候选版本', PreviewCheck: '检查预览', CommitVersion: '保存版本', Done: '已完成', NeedsUser: '需要处理', WaitRepair: '等待修复决定', WaitBudget: '等待额度确认', Cancelled: '已取消',
}
const USER_ACTIVITY: Record<string, string> = {
  card: '收到需要确认的内容', decision_submitted: '你已提交决定', version_saved: '新版本已保存',
  completed: '应用已生成', failed: '本轮遇到问题', cancelled: '本轮已取消', budget_exceeded: '本轮达到用量上限', budget_extended: '你已确认增加额度',
}
const RIGHT_LABEL: Record<RightView, string> = {
  workbench: '产物预览', overview: '项目概览', documents: '项目文档', tests: '测试', versions: '版本',
}
const RIGHT_ICON: Record<RightView, string> = { workbench: workbenchIcon, overview: overviewIcon, documents: docsIcon, tests: testsIcon, versions: versionsIcon }
const ROUTE_SEGMENT: Record<RightView, string> = { workbench: '', overview: '/overview', documents: '/docs', tests: '/tests', versions: '/versions' }
function parseRoute(path: string): { id: string | null; view: RightView } {
  const match = path.match(/^\/projects\/([^/]+)(?:\/(overview|docs|tests|versions|publish))?\/?$/)
  const views: Record<string, RightView> = { overview: 'overview', docs: 'documents', tests: 'tests', versions: 'versions', publish: 'versions' }
  return { id: match?.[1] || null, view: views[match?.[2] || ''] || 'workbench' }
}
function projectGlyph(title: string): string { return [...title.trim()][0] || '项' }
function plannedTasks(plan: Plan): string[] { return plan.tasks?.length ? plan.tasks : plan.features || [] }

type ConversationTurn = { kind: 'card'; card: Card; at: string; seq: number } | { kind: 'decision'; decision: Decision; card: Card | null; at: string; seq: number } | { kind: 'message'; message: Submission; card: Card | null; at: string; seq: number }
function conversationTurns(events: Event[], decisions: Decision[], messages: Submission[], run: Run): ConversationTurn[] {
  const cards = new Map<string, Card>()
  const used = new Set<string>()
  const turns: ConversationTurn[] = []
  const submittedDecisionIds = new Set(messages.map(item => item.decision_id).filter(Boolean))
  const pendingCardId = ['awaiting_clarification', 'awaiting_plan', 'awaiting_repair', 'awaiting_budget'].includes(run.status) ? run.card_id : null
  for (const event of events) {
    if (event.type === 'card') {
      const card = event.payload.card as Card | undefined
      if (!card?.card_id) continue
      cards.set(card.card_id, card)
      if (card.card_id !== pendingCardId) turns.push({ kind: 'card', card, at: event.at, seq: event.seq })
    }
    if (event.type === 'decision_submitted') {
      const id = String(event.payload.decision_id || '')
      if (submittedDecisionIds.has(id)) continue
      const decision = decisions.find(item => item.id === id) || decisions.find(item => !used.has(item.id) && item.action === event.payload.action && item.spec_version === event.payload.spec_version)
      if (!decision || used.has(decision.id)) continue
      used.add(decision.id)
      turns.push({ kind: 'decision', decision, card: cards.get(decision.card_id) || null, at: event.at, seq: event.seq })
    }
    if (event.type === 'message_submitted') {
      const message = messages.find(item => item.id === event.payload.submission_id)
      if (message) turns.push({ kind: 'message', message, card: cards.get(message.card_id) || null, at: event.at, seq: event.seq })
    }
  }
  return turns
}

function decisionText(decision: Decision, card: Card | null): string {
  if (decision.action === 'revise_clarification') return `我修改了需求：${decision.payload.request_text || '请按修改后的需求重新梳理。'}`
  if (decision.action === 'revise_plan') return `请调整计划：${decision.payload.feedback || '请重新拟定计划。'}`
  if (decision.action === 'approve_plan') return '我确认这个计划，开始生成应用。'
  if (decision.action === 'continue_repair') return card?.payload.failure_stage === 'source_validation' ? '请根据源码检查反馈继续修复一次。' : '请针对这次构建错误继续修复一次。'
  if (decision.action === 'rebuild') return '请用当前代码重新构建一次。'
  if (decision.action === 'guided_repair') return `请按这个方向修复：${decision.payload.feedback || ''}`
  if (decision.action === 'extend_budget') return '我确认增加选中的额度，并继续当前任务。'
  if (decision.action === 'extend_auto_repair') return '请增加 30 轮自动源码修复额度，并继续当前任务。'
  const questions = card?.type === 'clarification' ? (card.payload as Clarification).questions || [] : []
  const answers = decision.payload.answers || {}
  const lines = questions.map(question => `${question.text}：${answers[question.id] || '不填写'}`)
  return lines.length ? `我确认这些需求。\n${lines.join('\n')}` : '我确认这些需求。'
}

function ConversationTurns({ turns }: { turns: ConversationTurn[] }) {
  return <>{turns.map(turn => turn.kind === 'message'
    ? <div className="conversation-turn" key={`message-${turn.message.id}`}><div className="request-author"><strong>你</strong><time dateTime={turn.at}>{formatTime(turn.at)}</time></div><div className="request-card"><p>{turn.message.text || '已提交澄清卡答案'}</p>{Object.entries(turn.message.answers).length > 0 && <ul className="submitted-answers">{Object.entries(turn.message.answers).map(([id, value]) => <li key={id}>{((turn.card?.payload as Clarification | undefined)?.questions || []).find(question => question.id === id)?.text || id}：{value || '不填写'}</li>)}</ul>}</div><div className="agent-speaker"><img src={brandMark} alt="" /><strong>MYATOM</strong></div><div className="agent-message past"><p>{turn.message.status === 'interpreting' ? '正在理解这条消息…' : turn.message.reply || '已记录这条消息。'}</p></div></div>
    : turn.kind === 'decision'
    ? <div className="conversation-turn" key={`decision-${turn.decision.id}`}><div className="request-author"><strong>你</strong><time dateTime={turn.at}>{formatTime(turn.at)}</time></div><div className="request-card"><p>{decisionText(turn.decision, turn.card)}</p></div></div>
    : <div className="conversation-turn" key={`card-${turn.card.card_id}`}><div className="agent-speaker"><img src={brandMark} alt="" /><strong>MYATOM</strong><time dateTime={turn.at}>{formatTime(turn.at)}</time></div><div className="agent-message past"><strong>{turn.card.type === 'clarification' ? '我整理了需要确认的问题' : turn.card.type === 'build_plan' ? '我拟好了构建计划' : turn.card.type === 'budget_extension' ? '额度已达上限' : turn.card.payload.failure_stage === 'plan' ? '生成计划失败' : turn.card.payload.failure_stage === 'source_validation' ? '源码校验未通过' : turn.card.payload.failure_stage === 'commit_version' ? '版本保存失败' : '构建未通过'}</strong>{turn.card.type === 'build_plan' && <p>{(turn.card.payload as Plan).title}</p>}{turn.card.type === 'budget_extension' && <p>{turn.card.payload.reason}</p>}{turn.card.type === 'test_result' && <p>{turn.card.payload.failure_summary?.latest_error || (['plan', 'commit_version'].includes(turn.card.payload.failure_stage || '') ? turn.card.payload.diagnostics : undefined) || '请查看检查结果。'}</p>}{turn.card.type === 'clarification' && <ul>{((turn.card.payload as Clarification).questions || []).map(question => <li key={question.id}>{question.text}</li>)}</ul>}{turn.card.type === 'build_plan' && <ul>{((turn.card.payload as Plan).features || []).slice(0, 3).map((feature, index) => <li key={index}>{feature}</li>)}</ul>}</div></div>)}</>
}

function FailureSummaryView({ summary }: { summary: FailureSummary }) {
  const source = summary.stage === 'source_validation'
  return <div className="failure-summary"><strong>当前问题小结</strong><p>{summary.cause}</p><p><b>已尝试：</b>{summary.total_attempts ?? summary.attempts.length} 次{source ? '源码校验' : '构建'}，其中自动修复 {summary.automatic_repairs} 轮。</p><p><b>最近一次：</b>{summary.latest_error}</p><details><summary>最近几次{source ? '源码校验' : '构建'}结果</summary><ol>{summary.attempts.map(item => <li key={item.number}><code>{item.command || '检查'}</code>：{item.error}</li>)}</ol></details></div>
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const modelHeader = init?.method === 'POST' && (/^\/projects\/[^/]+\/runs$/.test(path) || /^\/runs\/[^/]+\//.test(path))
    ? modelRequestHeader() : {}
  const response = await fetch(`/api${path}`, { credentials: 'same-origin', ...init, headers: { 'Content-Type': 'application/json', ...modelHeader, ...(init?.headers || {}) } })
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try { detail = (await response.json()).detail || detail } catch { /* response may be empty */ }
    throw new ApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return response.json() as Promise<T>
}

class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message) }
}

function formatTime(value?: string): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function makeKey() { return crypto.randomUUID() }

function App() {
  const layout = useColumnLayout()
  const initialRoute = parseRoute(location.pathname)
  const initialId = initialRoute.id
  const [projectId, setProjectId] = useState<string | null>(initialId)
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(currentModelConfig())
  const [inviteSession, setInviteSession] = useState<InviteSession | null>(null)
  const [platformModel, setPlatformModelChoice] = useState(false)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [project, setProject] = useState<Project | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [messages, setMessages] = useState<Submission[]>([])
  const [pendingSubmissionId, setPendingSubmissionId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [requestText, setRequestText] = useState(() => readSessionDrafts(REQUEST_DRAFTS_KEY, isTextDraft)[initialId || 'home'] || '')
  const [selectedExampleId, setSelectedExampleId] = useState<string | null>(null)
  const [exampleFeedback, setExampleFeedback] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [editedRequest, setEditedRequest] = useState('')
  const [editingOriginal, setEditingOriginal] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [budgetChoice, setBudgetChoice] = useState<BudgetChoice>({ model_calls: false, total_tokens: false, run_seconds: false, fix_rounds: false })
  const [conflictDraft, setConflictDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [accessError, setAccessError] = useState(false)
  const [syncState, setSyncState] = useState<'syncing' | 'connected' | 'disconnected'>('syncing')
  const [lastSynced, setLastSynced] = useState<string | null>(null)
  const [showProjects, setShowProjects] = useState(false)
  const [cancellingRun, setCancellingRun] = useState<string | null>(null)
  const [buildLog, setBuildLog] = useState<string | null>(null)
  const [showBuildLog, setShowBuildLog] = useState(false)
  const [traceCopied, setTraceCopied] = useState(false)
  const [buildLogLoading, setBuildLogLoading] = useState(false)
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [fileContent, setFileContent] = useState('')
  const [rightView, setRightView] = useState<RightView>(initialRoute.view)
  const [docTab, setDocTab] = useState<'requirements' | 'plan' | 'decisions' | 'files'>('requirements')
  const [switcherOpen, setSwitcherOpen] = useState(false)
  const [switcherSearch, setSwitcherSearch] = useState('')
  const [homeSearch, setHomeSearch] = useState('')
  const [allProjectsOpen, setAllProjectsOpen] = useState(false)
  const [sideSearch, setSideSearch] = useState('')
  const [homeView, setHomeView] = useState<'new' | 'projects'>('new')
  const [heroText, setHeroText] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches ? '今天想做什么？' : '')
  const [rightMode, setRightMode] = useState<'auto' | 'open' | 'closed'>('auto')
  const [workbenchTab, setWorkbenchTab] = useState<'preview' | 'code'>('preview')
  const [streamState, setStreamState] = useState<'idle' | 'connecting' | 'live' | 'polling'>('idle')
  const [streamRetryKey, setStreamRetryKey] = useState(0)
  const [previewState, setPreviewState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState('')
  const [previewReload, setPreviewReload] = useState(0)
  const [mobileTab, setMobileTab] = useState<'process' | 'results'>('process')
  const messageKeys = useRef<Record<string, MessageKey>>(readSessionDrafts(MESSAGE_KEYS_KEY, isMessageKey))
  const requestDrafts = useRef<Record<string, string>>(readSessionDrafts(REQUEST_DRAFTS_KEY, isTextDraft))
  const docTabsByProject = useRef<Record<string, DocTab>>({})
  const decisionDrafts = useRef<Record<string, DecisionDraft>>(readSessionDrafts(DECISION_DRAFTS_KEY, isDecisionDraft))
  const decisionDraftKey = useRef<string | null>(null)
  const switcherRef = useRef<HTMLDivElement | null>(null)
  const switcherButtonRef = useRef<HTMLButtonElement | null>(null)
  const allProjectsRef = useRef<HTMLDivElement | null>(null)
  const allProjectsTriggerRef = useRef<HTMLElement | null>(null)
  const focusNewProject = useRef(false)
  const focusHistoryRoute = useRef<{ id: string | null; view: RightView } | null>(null)
  const headingFocusFrame = useRef<number | null>(null)
  const runKey = useRef<string | null>(null)
  const pendingProjectId = useRef<string | null>(null)
  const activeProjectId = useRef<string | null>(initialId)
  const eventCursor = useRef<{ runId: string; seq: number }>({ runId: '', seq: 0 })
  const sidebarRef = useRef<HTMLElement | null>(null)
  const conversationScrollRef = useRef<HTMLDivElement | null>(null)
  const drawerReturnFocus = useRef<HTMLElement | null>(null)
  const rightHeadingRef = useRef<HTMLHeadingElement | null>(null)
  const run = project?.runs[0] || null
  function changeModelMode(useInvite: boolean) {
    setPlatformModelChoice(useInvite)
    setPlatformModel(useInvite)
  }
  function changeInviteSession(next: InviteSession) {
    const changedIdentity = inviteSession?.invited !== next.invited
    setInviteSession(next)
    if (inviteSession === null) changeModelMode(next.platform_model_available && !currentModelConfig()?.api_key)
    else if (!next.invited || !next.platform_model_available) changeModelMode(false)
    if (changedIdentity) {
      if (inviteSession !== null && !next.invited) navigate(null)
      else if (projectId) void refreshProject(projectId).catch(() => undefined)
      void refreshList().catch(() => undefined)
    }
  }
  useEffect(() => {
    if (!run?.needs_model_key || !modelConfig?.api_key || platformModel || !['clarifying', 'planning', 'building'].includes(run.status)) return
    api(`/runs/${run.id}/model`, { method: 'POST' }).catch(reason => setError((reason as Error).message))
  }, [run?.id, run?.status, run?.needs_model_key, modelConfig, platformModel])
  const turns = run ? conversationTurns(events, (project?.decisions || []).filter(item => item.run_id === run.id), messages, run) : []
  const originalRequest = String(events.find(item => item.type === 'run_created')?.payload.request_text || run?.request_text || '')
  const documentRun = run?.plan ? run : project?.runs.find(item => item.approved_spec_version && item.plan) || null
  const version = project?.versions.find(item => item.id === selectedVersion) || project?.versions.find(item => item.id === project.active_version_id) || project?.versions[0] || null
  const rightVisible = rightMode === 'open' || (rightMode === 'auto' && (!!version || rightView !== 'workbench'))
  const isActive = run && ['clarifying', 'planning', 'building'].includes(run.status)
  const isWaiting = run && ['awaiting_clarification', 'awaiting_plan', 'awaiting_repair', 'awaiting_budget'].includes(run.status)
  const clarification = run?.card?.type === 'clarification' ? run.card.payload as Clarification : null
  const canConfirmClarification = clarification?.questions.every(q => !q.required || !!answers[q.id]?.trim()) ?? false
  const messageInterpreting = !!pendingSubmissionId || !!(run && messages.some(item => item.run_id === run.id && item.card_id === run.card_id && item.status === 'interpreting'))

  useEffect(() => {
    if (projectId || homeView !== 'new') return
    const phrases = ['今天想做什么？', '快速产出产品模型？', '一个绝妙的主意！']
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (reduceMotion.matches) { setHeroText(phrases[0]); return }
    let index = 0
    let position = 0
    let deleting = false
    let timer: number
    setHeroText('')
    const tick = () => {
      const phrase = phrases[index]
      if (deleting) {
        position = Math.max(0, position - 1)
        setHeroText(phrase.slice(0, position))
        if (position === 0) { deleting = false; index = (index + 1) % phrases.length }
        timer = window.setTimeout(tick, position === 0 ? 360 : 72)
      } else {
        const next = phrases[index]
        position = Math.min(next.length, position + 1)
        setHeroText(next.slice(0, position))
        if (position === next.length) deleting = true
        timer = window.setTimeout(tick, position === next.length ? 1650 : 125)
      }
    }
    timer = window.setTimeout(tick, 280)
    return () => window.clearTimeout(timer)
  }, [projectId, homeView])

  const refreshList = useCallback(async () => {
    try {
      const result = await api<{ projects: ProjectSummary[] }>('/projects')
      setProjects(result.projects)
      setListError('')
    } catch (err) {
      setListError((err as Error).message)
      throw err
    } finally { setListLoading(false) }
  }, [])

  const refreshProject = useCallback(async (id: string) => {
    const data = await api<Project>(`/projects/${id}`)
    if (data.runs[0]) data.runs[0] = withRunElapsed(data.runs[0])
    if (activeProjectId.current !== id) return
    if (data.runs[0]) {
      const runId = data.runs[0].id
      if (eventCursor.current.runId !== runId) {
        eventCursor.current = { runId, seq: 0 }
        setEvents([])
        setMessages([])
      }
      const [result, messageResult] = await Promise.all([
        api<{ events: Event[] }>(`/runs/${runId}/events?after_seq=${eventCursor.current.seq}`),
        api<{ messages: Submission[] }>(`/runs/${runId}/messages`),
      ])
      if (activeProjectId.current !== id || eventCursor.current.runId !== runId) return
      setProject(data)
      setMessages(messageResult.messages)
      if (result.events.length) {
        eventCursor.current.seq = Math.max(eventCursor.current.seq, ...result.events.map(item => item.seq))
        setEvents(previous => {
          const bySeq = new Map(previous.map(item => [item.seq, item]))
          result.events.forEach(item => bySeq.set(item.seq, item))
          return [...bySeq.values()].sort((a, b) => a.seq - b.seq)
        })
      }
    } else { setProject(data); setEvents([]); setMessages([]); eventCursor.current = { runId: '', seq: 0 } }
    setSyncState('connected')
    setLastSynced(new Date().toISOString())
    setAccessError(false)
  }, [])

  useEffect(() => { refreshList().catch(err => setError((err as Error).message)) }, [refreshList])
  useEffect(() => {
    if (run?.id) refreshList().catch(() => undefined)
  }, [run?.id, run?.status, run?.phase, run?.version_id, refreshList])
  useEffect(() => {
    activeProjectId.current = projectId
    if (!projectId) { setProject(null); setEvents([]); setMessages([]); return }
    const handleFailure = (err: unknown) => {
      if (activeProjectId.current !== projectId) return
      setSyncState('disconnected')
      if (err instanceof ApiError && [401, 403, 404].includes(err.status)) setAccessError(true)
    }
    refreshProject(projectId).catch(handleFailure)
    const timer = window.setInterval(() => refreshProject(projectId).catch(handleFailure), 6000)
    return () => window.clearInterval(timer)
  }, [projectId, refreshProject])
  useEffect(() => {
    if (!projectId && focusNewProject.current) {
      focusNewProject.current = false
      document.getElementById('project-request')?.focus()
    }
  }, [projectId])
  useEffect(() => {
    const target = focusHistoryRoute.current
    if (!target || target.id !== projectId || target.view !== rightView) return
    focusHistoryRoute.current = null
    if (projectId) document.querySelector<HTMLButtonElement>(`.project-view-nav button[data-view="${rightView}"]`)?.focus()
    else sidebarRef.current?.querySelector<HTMLButtonElement>('.all-projects-link')?.focus()
  }, [projectId, rightView])
  useEffect(() => {
    const runId = run?.id
    if (!projectId || !runId) { setStreamState('idle'); return }
    if (run && ['completed', 'failed', 'cancelled', 'budget_exceeded'].includes(run.status)) {
      setStreamState('idle')
      refreshProject(projectId).catch(() => undefined)
      return
    }
    if (!('EventSource' in window)) { setStreamState('polling'); return }
    let stopped = false
    let source: EventSource | null = null
    let retryTimer: number | undefined
    let failures = 0
    const connect = async () => {
      setStreamState(failures >= 3 ? 'polling' : 'connecting')
      try { await refreshProject(projectId) } catch { /* polling continues */ }
      if (stopped || activeProjectId.current !== projectId) return
      source = new EventSource(`/api/runs/${runId}/stream?after_seq=${eventCursor.current.seq}`)
      source.onopen = () => { failures = 0; setStreamState('live') }
      source.onmessage = message => {
        try {
          const item = JSON.parse(message.data) as Event
          if (item.run_id !== runId || !Number.isSafeInteger(item.seq) || item.seq <= eventCursor.current.seq) return
          if (item.seq !== eventCursor.current.seq + 1) { refreshProject(projectId).catch(() => undefined); return }
          eventCursor.current.seq = item.seq
          setEvents(previous => [...previous.filter(existing => existing.seq !== item.seq), item].sort((a, b) => a.seq - b.seq))
          if (['completed', 'failed', 'cancelled', 'budget_exceeded'].includes(item.type)) {
            stopped = true
            source?.close()
            setStreamState('idle')
          }
          refreshProject(projectId).catch(() => undefined)
        } catch { /* malformed events are ignored; snapshot remains authoritative */ }
      }
      source.onerror = () => {
        source?.close()
        if (stopped) return
        failures += 1
        setStreamState(failures >= 3 ? 'polling' : 'connecting')
        const delay = Math.min(30000, 1000 * 2 ** Math.min(failures, 5)) + Math.floor(Math.random() * 600)
        retryTimer = window.setTimeout(connect, delay)
      }
    }
    connect()
    return () => { stopped = true; source?.close(); if (retryTimer) window.clearTimeout(retryTimer) }
  }, [projectId, run?.id, run?.status, refreshProject, streamRetryKey])
  useEffect(() => {
    const onPop = () => {
      const { id, view } = parseRoute(location.pathname)
      if (headingFocusFrame.current !== null) window.cancelAnimationFrame(headingFocusFrame.current)
      headingFocusFrame.current = null
      focusHistoryRoute.current = { id, view }
      setRightView(view)
      setRightMode(view === 'workbench' ? 'auto' : 'open')
      if (id === activeProjectId.current) { if (id) refreshProject(id).catch(() => undefined); return }
      requestDrafts.current[activeProjectId.current || 'home'] = requestText
      setRequestText(requestDrafts.current[id || 'home'] || '')
      setDocTab(id ? docTabsByProject.current[id] || 'requirements' : 'requirements')
      activeProjectId.current = id
      eventCursor.current = { runId: '', seq: 0 }
      setProject(null); setEvents([]); setMessages([]); setPendingSubmissionId(null); setProjectId(id); setSelectedVersion(null); setSelectedFile(null); setAccessError(false); setSyncState('syncing')
      setSwitcherOpen(false)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [requestText, refreshProject])
  useEffect(() => {
    requestDrafts.current[projectId || 'home'] = requestText
    saveSessionDrafts(REQUEST_DRAFTS_KEY, requestDrafts.current)
  }, [projectId, requestText])
  useEffect(() => {
    if (!run?.card_id) return
    const key = `${run.id}:${run.card_id}:${run.spec_version}`
    if (decisionDraftKey.current !== key) return
    decisionDrafts.current[key] = { answers, editedRequest, feedback }
    saveSessionDrafts(DECISION_DRAFTS_KEY, decisionDrafts.current)
  }, [run?.id, run?.card_id, run?.spec_version, answers, editedRequest, feedback])
  useEffect(() => {
    const draft = run?.card_id ? decisionDrafts.current[`${run.id}:${run.card_id}:${run.spec_version}`] : null
    decisionDraftKey.current = run?.card_id ? `${run.id}:${run.card_id}:${run.spec_version}` : null
    setEditingOriginal(false)
    if (run?.card?.type === 'clarification') {
      setAnswers(draft?.answers || {})
      setEditedRequest(draft?.editedRequest ?? run.request_text)
    }
    setFeedback(draft?.feedback || '')
    const budgetKind = run?.card?.type === 'budget_extension' ? run.card.payload.budget_kind : ''
    setBudgetChoice({ model_calls: budgetKind === 'model_calls', total_tokens: budgetKind === 'total_tokens' || budgetKind === 'output_reserve',
      run_seconds: budgetKind === 'run_seconds', fix_rounds: budgetKind === 'fix_rounds' })
  }, [run?.card_id, run?.spec_version])
  useEffect(() => {
    if (!pendingSubmissionId) return
    const message = messages.find(item => item.id === pendingSubmissionId)
    if (!message || message.status === 'interpreting') return
    if (message.status === 'committed') { setFeedback(''); setEditingOriginal(false) }
    setPendingSubmissionId(null)
  }, [messages, pendingSubmissionId])
  useEffect(() => {
    const finished = new Set(messages.filter(item => item.status !== 'interpreting').map(item => item.id))
    if (!finished.size) return
    let changed = false
    for (const [key, value] of Object.entries(messageKeys.current)) {
      if (finished.has(value.id)) { delete messageKeys.current[key]; changed = true }
    }
    if (changed) saveSessionDrafts(MESSAGE_KEYS_KEY, messageKeys.current)
  }, [messages])
  useEffect(() => {
    if (!run?.card_id || !['awaiting_clarification', 'awaiting_plan', 'awaiting_budget'].includes(run.status)) return
    const frame = window.requestAnimationFrame(() => {
      const scroll = conversationScrollRef.current
      const card = scroll?.querySelector<HTMLElement>('.decision-turn')
      if (scroll && card) scroll.scrollTop += card.getBoundingClientRect().top - scroll.getBoundingClientRect().top - 18
    })
    return () => window.cancelAnimationFrame(frame)
  }, [projectId, run?.card_id, run?.status])
  useEffect(() => {
    if (!version) { setSelectedFile(null); setFileContent(''); return }
    if (selectedVersion !== version.id) setSelectedVersion(version.id)
  }, [version?.id])
  useEffect(() => {
    if (!version || !selectedFile) return
    fetch(`/api/versions/${version.id}/files/${selectedFile}`, { credentials: 'same-origin' })
      .then(async response => { if (!response.ok) throw new Error('源码读取失败'); return response.text() })
      .then(setFileContent).catch(err => setFileContent(err.message))
  }, [version?.id, selectedFile])
  useEffect(() => {
    if (run?.id === cancellingRun && ['cancelled', 'failed', 'completed', 'budget_exceeded'].includes(run.status)) setCancellingRun(null)
  }, [run?.id, run?.status, cancellingRun])
  useEffect(() => { setBuildLog(null); setShowBuildLog(false); setTraceCopied(false) }, [run?.id])
  useEffect(() => {
    if (!version || rightView !== 'workbench' || workbenchTab !== 'preview') return
    let live = true
    setPreviewState('loading'); setPreviewUrl(null); setPreviewError('')
    api<PreviewResponse>(`/versions/${version.id}/preview`).then(result => {
      if (!live) return
      const url = new URL(result.url, window.location.href)
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error('预览地址无效。')
      if ((url.hostname === 'localhost' || url.hostname.endsWith('.localhost') || url.hostname === '127.0.0.1') && !['localhost', '127.0.0.1'].includes(window.location.hostname)) throw new Error('此版本只有本机预览地址，当前访问环境无法打开。')
      setPreviewUrl(url.href)
    }).catch(err => { if (live) { setPreviewState('error'); setPreviewError((err as Error).message) } })
    return () => { live = false }
  }, [version?.id, rightView, workbenchTab, previewReload])
  useEffect(() => {
    if (previewState !== 'loading' || !previewUrl) return
    const timer = window.setTimeout(() => {
      setPreviewState('error')
      setPreviewError('预览载入超过 12 秒。可重试预览或查看代码。')
      setPreviewUrl(null)
    }, 12000)
    return () => window.clearTimeout(timer)
  }, [previewState, previewUrl])

  function onPreviewLoad(frame: HTMLIFrameElement) {
    try {
      if (frame.contentWindow?.location.href === 'about:blank') return
    } catch { /* A loaded cross-origin preview is expected. */ }
    setPreviewState('ready')
  }
  useEffect(() => {
    if (!showProjects) return
    sidebarRef.current?.querySelector<HTMLElement>('button')?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setShowProjects(false); return }
      if (event.key !== 'Tab' || !sidebarRef.current) return
      const focusable = [...sidebarRef.current.querySelectorAll<HTMLElement>('button:not(:disabled)')]
      if (!focusable.length) return
      if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable.at(-1)?.focus() }
      else if (!event.shiftKey && document.activeElement === focusable.at(-1)) { event.preventDefault(); focusable[0].focus() }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => { window.removeEventListener('keydown', onKeyDown); drawerReturnFocus.current?.focus() }
  }, [showProjects])
  useEffect(() => {
    if (!switcherOpen) return
    switcherRef.current?.querySelector<HTMLInputElement>('input')?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setSwitcherOpen(false); switcherButtonRef.current?.focus(); return }
      if (['ArrowDown', 'ArrowUp'].includes(event.key) && switcherRef.current) {
        const options = [...switcherRef.current.querySelectorAll<HTMLButtonElement>('.switcher-list button')]
        if (!options.length) return
        const current = options.indexOf(document.activeElement as HTMLButtonElement)
        const next = event.key === 'ArrowDown' ? Math.min(current + 1, options.length - 1) : current <= 0 ? options.length - 1 : current - 1
        event.preventDefault(); options[next].focus(); return
      }
      if (event.key === 'Enter' && document.activeElement === switcherRef.current?.querySelector('input')) {
        event.preventDefault(); switcherRef.current?.querySelector<HTMLButtonElement>('.switcher-list button')?.click(); return
      }
      if (event.key !== 'Tab' || !switcherRef.current) return
      const focusable = [...switcherRef.current.querySelectorAll<HTMLElement>('input, button:not(:disabled)')]
      if (!focusable.length) return
      if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable.at(-1)?.focus() }
      else if (!event.shiftKey && document.activeElement === focusable.at(-1)) { event.preventDefault(); focusable[0].focus() }
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!switcherRef.current?.contains(event.target as Node) && !switcherButtonRef.current?.contains(event.target as Node)) setSwitcherOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('pointerdown', onPointerDown)
    return () => { window.removeEventListener('keydown', onKeyDown); window.removeEventListener('pointerdown', onPointerDown) }
  }, [switcherOpen])
  useEffect(() => {
    if (!allProjectsOpen) return
    allProjectsRef.current?.querySelector<HTMLInputElement>('input')?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setAllProjectsOpen(false); return }
      if (event.key !== 'Tab' || !allProjectsRef.current) return
      const focusable = [...allProjectsRef.current.querySelectorAll<HTMLElement>('input, button:not(:disabled)')]
      if (!focusable.length) return
      if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable.at(-1)?.focus() }
      else if (!event.shiftKey && document.activeElement === focusable.at(-1)) { event.preventDefault(); focusable[0].focus() }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => { window.removeEventListener('keydown', onKeyDown); allProjectsTriggerRef.current?.focus() }
  }, [allProjectsOpen])

  function navigate(id: string | null) {
    if (id === projectId) { selectRightView('workbench'); setSwitcherOpen(false); return }
    requestDrafts.current[projectId || 'home'] = requestText
    setRequestText(requestDrafts.current[id || 'home'] || '')
    setDocTab(id ? docTabsByProject.current[id] || 'requirements' : 'requirements')
    history.pushState({}, '', id ? `/projects/${id}` : '/')
    activeProjectId.current = id
    eventCursor.current = { runId: '', seq: 0 }
    setProjectId(id)
    setProject(null); setEvents([]); setMessages([]); setPendingSubmissionId(null); setSelectedVersion(null); setSelectedFile(null)
    setError('')
    setAccessError(false)
    setSyncState('syncing')
    setShowProjects(false)
    setSwitcherOpen(false)
    setSwitcherSearch('')
    setRightView('workbench')
    setWorkbenchTab('preview')
    setPreviewUrl(null)
    setMobileTab('process')
    setRightMode('auto')
  }
  function selectRightView(view: RightView) {
    if (!projectId) return
    setRightMode(view === 'workbench' && !version ? 'auto' : 'open')
    if (headingFocusFrame.current !== null) window.cancelAnimationFrame(headingFocusFrame.current)
    const path = `/projects/${projectId}${ROUTE_SEGMENT[view]}`
    if (location.pathname !== path) history.pushState({}, '', path)
    setRightView(view)
    headingFocusFrame.current = window.requestAnimationFrame(() => {
      headingFocusFrame.current = null
      rightHeadingRef.current?.focus()
    })
  }
  function selectDocTab(tab: DocTab) {
    if (projectId) docTabsByProject.current[projectId] = tab
    setDocTab(tab)
  }
  function startNewProject() {
    setHomeView('new')
    requestDrafts.current.home = ''
    setTitle('')
    setSelectedExampleId(null)
    setExampleFeedback('')
    focusNewProject.current = true
    if (projectId) navigate(null)
    else { setRequestText(''); document.getElementById('project-request')?.focus(); focusNewProject.current = false }
  }
  function openVersionFile(path: string) {
    setSelectedFile(path)
    setWorkbenchTab('code')
    selectRightView('workbench')
  }
  function openLatestVersion() {
    if (project?.active_version_id) setSelectedVersion(project.active_version_id)
    setWorkbenchTab('preview')
    selectRightView('workbench')
  }
  async function activateVersion(target: Version) {
    if (!project || busy || target.id === project.active_version_id) return
    setBusy(true); setError('')
    try {
      await api(`/projects/${project.id}/versions/${target.id}/activate`, { method: 'POST' })
      await refreshProject(project.id)
      setSelectedVersion(target.id)
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }
  function openProjects() {
    drawerReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setShowProjects(true)
  }
  function openHome(view: 'new' | 'projects') {
    if (view === 'projects') {
      allProjectsTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
      setSwitcherOpen(false)
      setHomeSearch('')
      setAllProjectsOpen(true)
      return
    }
    setAllProjectsOpen(false)
    setHomeView('new')
    if (projectId) navigate(null)
    else setSwitcherOpen(false)
  }

  function applyExample(example: Example) {
    setTitle(example.title)
    setRequestText(example.request_text)
    setSelectedExampleId(example.id)
    setExampleFeedback(`已填入「${example.title}」的需求。可以修改后再开始梳理需求。`)
    runKey.current = null
    window.requestAnimationFrame(() => document.getElementById('project-request')?.focus())
  }

  function editExampleDraft() {
    setSelectedExampleId(null)
    setExampleFeedback('')
    runKey.current = null
  }

  async function create() {
    if (busy) return
    setError('')
    if (inviteSession?.invite_required && !inviteSession.invited) { setError('请先输入邀请码，再创建项目。'); return }
    if (!modelConfig?.api_key && !platformModel) { setError('请在模型设置中填写 API Key，或使用测试邀请码。'); return }
    if (requestText.trim().length < 10) { setError('请至少用 10 个字描述应用需求。'); return }
    setBusy(true)
    try {
      const createdId = pendingProjectId.current || (await api<Project>('/projects', { method: 'POST', body: JSON.stringify({ title: title.trim() || requestText.trim().slice(0, 26) }) })).id
      pendingProjectId.current = createdId
      const key = runKey.current || makeKey(); runKey.current = key
      await api(`/projects/${createdId}/runs`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ request_text: requestText.trim() }) })
      runKey.current = null
      pendingProjectId.current = null
      await refreshList()
      navigate(createdId)
      requestDrafts.current.home = ''
      setTitle('')
      setSelectedExampleId(null)
      setExampleFeedback('')
      await refreshProject(createdId)
    } catch (err) { setError(`${pendingProjectId.current ? '项目已创建，但需求尚未确认提交。重试会继续使用该项目。' : ''}${(err as Error).message}`) }
    finally { setBusy(false) }
  }

  async function submitNewRun() {
    if (!project || busy) return
    if (inviteSession?.invite_required && !inviteSession.invited) { setError('请先输入邀请码，再提交需求。'); return }
    if (!modelConfig?.api_key && !platformModel) { setError('请在模型设置中填写 API Key，或使用测试邀请码。'); return }
    if (!canSubmitNewRunRequest(requestText, !!project.active_version_id)) {
      setError(project.active_version_id ? '请描述要修改的内容。' : '请至少用 10 个字描述应用需求。'); return
    }
    setBusy(true); setError('')
    try {
      const key = runKey.current || makeKey(); runKey.current = key
      await api(`/projects/${project.id}/runs`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ request_text: requestText.trim(), mode: project.active_version_id ? 'iterate' : 'create' }) })
      runKey.current = null; setRequestText(''); setEvents([]); setMessages([])
      await refreshProject(project.id)
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  async function sendCurrentMessage() {
    if (!run?.card_id || busy || !project || messageInterpreting) return
    const text = editingOriginal ? `请将原需求完整替换为：\n${editedRequest.trim()}` : feedback.trim()
    const selectedAnswers = run.status === 'awaiting_clarification' && !editingOriginal ? answers : {}
    const previous = messages.filter(item => item.run_id === run.id && item.card_id === run.card_id
      && item.spec_version === run.spec_version && item.status === 'needs_clarification').at(-1)
    const payload = { card_ref: { card_id: run.card_id, spec_version: run.spec_version }, text, answers: selectedAnswers,
      reply_to_interpretation_id: previous?.id || null }
    const keyName = `${run.id}:${run.card_id}:${run.spec_version}`
    const payloadSignature = JSON.stringify(payload)
    const prior = messageKeys.current[keyName]
    const id = prior?.payload === payloadSignature ? prior.id : makeKey()
    messageKeys.current[keyName] = { id, payload: payloadSignature }
    saveSessionDrafts(MESSAGE_KEYS_KEY, messageKeys.current)
    setBusy(true); setError('')
    try {
      await api(`/runs/${run.id}/messages`, { method: 'POST', headers: { 'Idempotency-Key': id },
        body: JSON.stringify({ submission_id: id, ...payload }) })
      setPendingSubmissionId(id)
      setConflictDraft('')
      await refreshProject(project.id)
    } catch (err) {
      setError((err as Error).message)
      if (err instanceof ApiError && err.status === 409) {
        setConflictDraft(editingOriginal ? editedRequest : JSON.stringify({ 消息: feedback, 回答: selectedAnswers }, null, 2))
        await refreshProject(project.id)
      }
    } finally { setBusy(false) }
  }

  async function cancel() {
    if (!run || busy || !project) return
    setBusy(true); setError('')
    setCancellingRun(run.id)
    try { await api(`/runs/${run.id}/cancel`, { method: 'POST' }); await refreshProject(project.id) }
    catch (err) { setCancellingRun(null); setError((err as Error).message) }
    finally { setBusy(false) }
  }

  async function openRepair() {
    if (!run || !project || busy) return
    setBusy(true); setError('')
    try {
      await api(`/runs/${run.id}/offer-repair`, { method: 'POST' })
      await refreshProject(project.id)
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  async function openBudget() {
    if (!run || !project || busy) return
    setBusy(true); setError('')
    try {
      await api(`/runs/${run.id}/offer-budget`, { method: 'POST' })
      await refreshProject(project.id)
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  async function extendBudget() {
    if (!run?.card_id || !project || busy || !budgetChoiceValid) return
    const payload = { card_id: run.card_id, spec_version: run.spec_version, ...budgetChoice }
    const keyName = `budget:${run.id}:${run.card_id}:${run.spec_version}`
    const payloadSignature = JSON.stringify(payload)
    const prior = messageKeys.current[keyName]
    const id = prior?.payload === payloadSignature ? prior.id : makeKey()
    messageKeys.current[keyName] = { id, payload: payloadSignature }
    saveSessionDrafts(MESSAGE_KEYS_KEY, messageKeys.current)
    setBusy(true); setError('')
    try {
      await api(`/runs/${run.id}/budgets/extend`, { method: 'POST', headers: { 'Idempotency-Key': id }, body: payloadSignature })
      await refreshProject(project.id)
    } catch (err) {
      setError((err as Error).message)
      if (err instanceof ApiError && err.status === 409) await refreshProject(project.id)
    } finally { setBusy(false) }
  }

  async function toggleBuildLog() {
    if (!run) return
    if (showBuildLog) { setShowBuildLog(false); return }
    setShowBuildLog(true)
    if (buildLog !== null) return
    setBuildLogLoading(true)
    try {
      const response = await fetch(`/api/runs/${run.id}/build-log`, { credentials: 'same-origin' })
      if (!response.ok) throw new Error(`构建日志暂不可用（${response.status}）`)
      const log = await response.text()
      setBuildLog(log.slice(-20000).replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '') || '没有可用日志。')
    } catch (err) { setBuildLog((err as Error).message) }
    finally { setBuildLogLoading(false) }
  }

  const canStartNew = !run || ['completed', 'failed', 'cancelled', 'budget_exceeded'].includes(run.status)
  const awaitingRequirement = run?.status === 'awaiting_clarification' && run.card?.type === 'clarification' && run.card.actions.includes('revise_clarification')
  const awaitingPlan = run?.status === 'awaiting_plan' && run.card?.type === 'build_plan'
  const awaitingRepair = run?.status === 'awaiting_repair' && run.card?.type === 'test_result'
  const awaitingBudget = run?.status === 'awaiting_budget' && run.card?.type === 'budget_extension'
  const requiredBudgetKind = run?.card?.payload.budget_kind === 'output_reserve' ? 'total_tokens' : run?.card?.payload.budget_kind
  const budgetChoiceValid = Object.values(budgetChoice).some(Boolean) &&
    (!requiredBudgetKind || !['model_calls', 'total_tokens', 'run_seconds', 'fix_rounds'].includes(requiredBudgetKind) || budgetChoice[requiredBudgetKind as BudgetKind])
  const editingRequirement = awaitingRequirement && editingOriginal
  const composerValue = editingRequirement ? editedRequest : isWaiting ? feedback : requestText
  const composerLabel = editingRequirement ? '编辑原需求' : '输入消息'
  const composerMaxLength = awaitingPlan || awaitingRepair ? 2000 : 5000
  const composerCanSend = editingRequirement ? editedRequest.trim().length >= 10 && editedRequest.trim() !== run.request_text
    : awaitingRequirement ? (canConfirmClarification && Object.keys(answers).length > 0) || !!feedback.trim()
    : awaitingPlan || awaitingRepair ? !!feedback.trim()
    : canStartNew && canSubmitNewRunRequest(requestText, !!project?.active_version_id)
  const composerAction = '发送'
  function submitComposer() {
    if (isWaiting) { void sendCurrentMessage(); return }
    if (canStartNew) void submitNewRun()
  }
  const composer = awaitingBudget ? <div className="new-run-card decision-composer budget-composer"><span>已选择 {Object.values(budgetChoice).filter(Boolean).length} 项额度</span><button type="button" className="primary" disabled={busy || !budgetChoiceValid} onClick={extendBudget}>确认扩额并继续 ↑</button></div>
    : project && <div className={`new-run-card ${isWaiting ? 'decision-composer' : ''}`}>{(!isWaiting || editingRequirement) && <div className="composer-heading"><label htmlFor="new-run-request">{composerLabel}</label>{editingRequirement && <button type="button" onClick={() => { setEditingOriginal(false); window.requestAnimationFrame(() => document.getElementById('new-run-request')?.focus()) }}>取消编辑</button>}</div>}<textarea id="new-run-request" aria-label={composerLabel} value={composerValue} onChange={event => {
    if (editingRequirement) setEditedRequest(event.target.value)
    else if (isWaiting) setFeedback(event.target.value)
    else { setRequestText(event.target.value); runKey.current = null }
  }} onKeyDown={event => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    if (!busy && !messageInterpreting && composerCanSend) submitComposer()
  }} rows={2} maxLength={composerMaxLength} placeholder={editingRequirement ? '修改完整需求后发送' : awaitingRequirement ? '选好卡片答案，也可以在这里补充说明…' : awaitingPlan ? '按这版计划开始生成，或写下要修改的地方…' : awaitingRepair ? '再修复一次、指定方向，或选择增加自动修复轮次…' : canStartNew ? '描述你想做的应用或下一步修改…' : '先记下下一轮想法，本轮结束后发送…'} /><div className="form-bottom"><span>{composerValue.length}/{composerMaxLength}</span><button type="button" className="primary" aria-label={composerAction} disabled={busy || messageInterpreting || !composerCanSend} onClick={submitComposer}>{composerAction} ↑</button></div></div>
  const visibleHomeProjects = projects.filter(item => item.title.toLocaleLowerCase().includes(homeSearch.trim().toLocaleLowerCase()))
  const visibleSideProjects = projects.filter(item => item.title.toLocaleLowerCase().includes(sideSearch.trim().toLocaleLowerCase()))
  const visibleSwitcherProjects = projects.filter(item => item.title.toLocaleLowerCase().includes(switcherSearch.trim().toLocaleLowerCase()))
  const layoutStyle = { '--user-sidebar-width': `${layout.current.sidebar}px`, '--user-chat-width': `${layout.current.chat}px` } as CSSProperties
  return <div className={`shell ${layout.dragging ? 'is-resizing' : ''}`} style={layoutStyle}>
    <span className="sr-only" role="status" aria-live="polite">{layout.announcement}</span>
    <aside id="project-sidebar" ref={sidebarRef} className={`sidebar ${showProjects ? 'open' : ''}`} aria-label="项目导航" role={showProjects ? 'dialog' : undefined} aria-modal={showProjects ? true : undefined}>
      <button className="brand" onClick={() => openHome('new')} aria-label="返回首页">
        <img src={brandLockup} alt="MYATOM" />
      </button>
      {projectId && <div className="current-project"><span className="sidebar-label">当前项目</span><button className="current-project-button" aria-haspopup="dialog" aria-expanded={switcherOpen} onClick={() => setSwitcherOpen(value => !value)}><span className="project-icon" aria-hidden="true">{projectGlyph(project?.title || projects.find(item => item.id === projectId)?.title || '项')}</span><span><strong>{project?.title || projects.find(item => item.id === projectId)?.title || '正在加载项目'}</strong><small>切换项目</small></span><span className="chevron" aria-hidden="true">⌄</span></button>
        {switcherOpen && <><div className="switcher-scrim" aria-hidden="true" onClick={() => setSwitcherOpen(false)} /><div ref={switcherRef} className="project-switcher" role="dialog" aria-modal="true" aria-label="切换项目"><div className="switcher-head"><h2>切换项目</h2><button aria-label="关闭项目切换" onClick={() => { setSwitcherOpen(false); switcherButtonRef.current?.focus() }}>×</button></div><label htmlFor="switcher-search" className="sr-only">搜索项目名称</label><input id="switcher-search" value={switcherSearch} onChange={event => setSwitcherSearch(event.target.value)} placeholder="⌕　搜索项目名称" /><span className="switcher-caption">{switcherSearch ? '搜索结果' : '最近项目'}</span><div className="switcher-list">{visibleSwitcherProjects.slice(0, switcherSearch ? undefined : 5).map(item => <button className={item.id === projectId ? 'selected' : ''} key={item.id} onClick={() => navigate(item.id)}><span className="project-icon" aria-hidden="true">{projectGlyph(item.title)}</span><span className="switcher-item-copy"><strong>{item.title}</strong><small>{item.latest_version_id ? `版本 #${item.latest_version_id.slice(0, 8)} · ` : ''}{item.latest_status ? STATUS[item.latest_status] || item.latest_status : '尚未开始'}</small></span>{item.id === projectId && <b aria-label="当前项目">✓</b>}</button>)}{!visibleSwitcherProjects.length && <p>没有匹配的项目</p>}</div><div className="switcher-actions"><button className="switcher-all" onClick={() => openHome('projects')}>所有项目</button><button className="switcher-new" onClick={startNewProject}>＋ 新建项目</button></div></div></>}
      </div>}
      <nav className="sidebar-primary" aria-label="主导航"><button className={`all-projects-link ${!projectId && homeView === 'projects' ? 'active' : ''}`} onClick={() => openHome('projects')}>⌁ <span>所有项目</span></button><button className={`all-projects-link create-link ${!projectId && homeView === 'new' ? 'active' : ''}`} onClick={startNewProject}>＋ <span>新建项目</span></button></nav>
      <div className="sidebar-history"><div className="sidebar-label recent-label">历史项目 <span>{projects.length}</span></div><label className="side-search"><span className="sr-only">搜索历史项目</span><input value={sideSearch} onChange={event => setSideSearch(event.target.value)} placeholder="搜索项目" /></label><nav className="recent-projects" aria-label="历史项目">{visibleSideProjects.map(item => <button className={item.id === projectId ? 'selected' : ''} key={item.id} onClick={() => navigate(item.id)}><span className="project-icon" aria-hidden="true">{projectGlyph(item.title)}</span><span className="sidebar-project-copy"><strong>{item.title}</strong><small>{item.latest_status ? STATUS[item.latest_status] || item.latest_status : '尚未开始'}{item.latest_version_id ? ` · #${item.latest_version_id.slice(0, 8)}` : ''}</small></span></button>)}{!visibleSideProjects.length && <p className="sidebar-empty">{listLoading ? '正在加载项目…' : sideSearch ? '没有匹配的项目' : listError ? '项目列表暂不可用' : '还没有历史项目'}</p>}</nav></div>
      <div className="sidebar-foot">{inviteSession?.invited ? '邀请码测试空间' : '访客空间'}{projectId && <button className="layout-reset" onClick={layout.reset} disabled={!layout.enabled}>恢复默认布局</button>}</div>
    </aside>
    {projectId && <div className="layout-divider sidebar-divider" role="separator" tabIndex={0} aria-label="调整导航栏宽度" aria-orientation="vertical" aria-controls="project-sidebar project-main" aria-valuemin={layout.range.sidebarMin} aria-valuemax={layout.range.sidebarMax} aria-valuenow={layout.current.sidebar} aria-valuetext={`导航栏 ${Math.round(layout.current.sidebar)} 像素`} title="拖动调整导航宽度；方向键微调；双击恢复默认" onPointerDown={event => layout.start('sidebar', event)} onPointerMove={layout.move} onPointerUp={layout.finish} onPointerCancel={layout.cancel} onLostPointerCapture={layout.cancel} onKeyDown={event => layout.key('sidebar', event)} onDoubleClick={layout.reset} />}
    {showProjects && <button className="drawer-scrim" aria-label="关闭项目列表" onClick={() => setShowProjects(false)} />}

    <main id="project-main" className={`main ${!projectId ? 'home-main' : ''}`}>
      {!projectId ? <>
        <header className="topbar"><div className="topbar-main"><button className="projects-toggle" onClick={openProjects} aria-label="打开项目列表">☰ <span>项目</span></button><strong>{homeView === 'new' ? '新建项目' : '所有项目'}</strong></div><div className="top-actions"><ModelSettings onChange={setModelConfig} session={inviteSession} onInviteChange={changeInviteSession} platformModel={platformModel} onModeChange={changeModelMode} /></div></header>
        {homeView === 'new' ? <div className="welcome v7-home">
          <h1 aria-label="今天想做什么？"><span aria-hidden="true">{heroText}</span><span className="typing-caret" aria-hidden="true" /></h1>
          {inviteSession?.invite_required && !inviteSession.invited && <p className="invite-home-notice" role="status">工作台可公开浏览。创建与预览项目需要先在右上角的模型设置中验证邀请码。</p>}
          <section className="start-project" aria-label="新项目需求"><div className="form-card"><label className="sr-only" htmlFor="project-request">描述你想创建的应用</label><textarea id="project-request" value={requestText} onChange={event => { setRequestText(event.target.value); editExampleDraft() }} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void create() } }} placeholder="例如：做一个可以安排番茄钟的待办应用…" maxLength={5000} rows={3} /><div className="start-bottom"><span className="request-count">{requestText.length}/5000</span><button className="primary" disabled={busy} onClick={create}>{busy ? '正在创建…' : '创建项目　→'}</button></div><details className="project-title-option"><summary>添加项目名称（可选）</summary><label htmlFor="project-title">项目名称</label><input id="project-title" value={title} onChange={event => { setTitle(event.target.value); editExampleDraft() }} placeholder="给项目起个名字" maxLength={100} /></details><div className="example-feedback" role="status" aria-live="polite">{exampleFeedback}</div></div></section>
          <section className="examples-panel" aria-labelledby="examples-heading"><h2 id="examples-heading">试试这些精选样例</h2><div className="example-list">{catalog.examples.map(example => <button type="button" className={`example-card ${selectedExampleId === example.id ? 'selected' : ''}`} aria-pressed={selectedExampleId === example.id} key={example.id} onClick={() => applyExample(example)}><strong>{example.title}</strong><span>{example.subtitle}</span><em>{selectedExampleId === example.id ? '✓ 已填入' : '↗'}</em></button>)}</div><p className="examples-note">样例只填入需求草稿，创建前仍可编辑。</p></section>
        </div> : <div className="welcome v7-projects"><section className="home-projects" aria-labelledby="home-projects-heading"><div className="home-projects-head"><div><span className="section-kicker">PROJECTS / 你的工作</span><h1 id="home-projects-heading">所有项目</h1><p>继续未完成的任务，或查看已保存的成果。</p></div><label className="home-search"><span className="sr-only">搜索项目</span><input value={homeSearch} onChange={event => setHomeSearch(event.target.value)} placeholder="搜索项目" /></label></div><div className="project-table"><div className="project-table-head"><span>项目</span><span>当前状态</span><span>最近版本</span><span>更新时间</span></div>{visibleHomeProjects.map(item => <button key={item.id} className="project-table-row" onClick={() => navigate(item.id)}><span className="project-title-cell"><span className="project-icon" aria-hidden="true">{projectGlyph(item.title)}</span><span><strong>{item.title}</strong><small>Web 应用项目</small></span></span><span>{item.latest_status ? STATUS[item.latest_status] || item.latest_status : '尚未开始'}</span><span>{item.latest_version_id ? `#${item.latest_version_id.slice(0, 8)}` : '—'}</span><span>{formatTime(item.updated_at)}　→</span></button>)}{!visibleHomeProjects.length && <div className="project-table-empty">{listLoading ? '正在加载项目…' : listError ? <>项目列表暂不可用：{listError} <button onClick={() => refreshList().catch(() => undefined)}>重试</button></> : homeSearch ? '没有匹配的项目。' : '还没有项目。写下第一条需求开始。'}</div>}</div><button className="secondary" onClick={startNewProject}>＋ 新建项目</button></section></div>}
      </> : <>
        <header className="topbar project-topbar"><div className="topbar-main"><button className="projects-toggle" onClick={openProjects} aria-label="打开项目列表">☰ <span>项目</span></button><span className="identity-kicker">当前项目</span><button ref={switcherButtonRef} className="top-project-switch" aria-haspopup="dialog" aria-expanded={switcherOpen} onClick={() => setSwitcherOpen(value => !value)}>{project?.title || '正在加载项目'} <span aria-hidden="true">⌄</span></button><span className={`status-pill ${run?.status || ''}`}>{run ? STATUS[run.status] || run.status : version ? `代码已保存 · #${version.id.slice(0, 8)}` : '等待需求'}</span></div><div className="top-actions"><ModelSettings onChange={setModelConfig} session={inviteSession} onInviteChange={changeInviteSession} platformModel={platformModel} onModeChange={changeModelMode} />{(version || run?.plan || run?.card?.type === 'build_plan' || rightVisible) && <button onClick={() => { if (rightVisible) setRightMode('closed'); else if (!version) selectRightView('documents'); else setRightMode('open') }} aria-expanded={rightVisible} aria-controls="results-pane">{rightVisible ? '收起右侧' : version ? '查看应用' : '查看计划文档'}</button>}<button onClick={layout.reset} disabled={!layout.enabled}>恢复默认布局</button><span className="top-status" aria-live="polite"><small>{syncState === 'disconnected' ? '连接中断 · 任务可能仍在运行' : syncState === 'syncing' ? '正在同步服务端状态' : `已保存 ${formatTime(project?.updated_at)} · ${streamState === 'live' ? '实时连接' : streamState === 'polling' ? '定时更新' : streamState === 'connecting' ? '正在恢复连接' : '状态已同步'}`}</small></span></div></header>
        {accessError ? <div className="empty-state" role="alert"><div className="empty-number">!</div><h3>无法打开此项目</h3><p>{inviteSession?.invite_required && !inviteSession.invited ? '请先在右上角的模型设置中验证邀请码。' : '项目不存在，或当前测试身份没有访问权限。请检查项目链接与邀请码。'}</p><button className="primary" onClick={() => navigate(null)}>返回首页</button></div> : <>
        {(syncState === 'disconnected' || streamState === 'polling') && <div className="connection-banner" role="status"><span>{syncState === 'disconnected' ? `无法同步最新状态；上次同步 ${formatTime(lastSynced || undefined)}。任务可能仍在运行。` : '实时连接中断，正在用定时更新补齐活动。'}</span><button onClick={() => { setSyncState('syncing'); setStreamRetryKey(value => value + 1); refreshProject(projectId).catch(() => setSyncState('disconnected')) }}>重新连接</button></div>}
        {run?.needs_model_key && !modelConfig?.api_key && <div className="connection-banner" role="status">任务在等待模型 Key。请在顶部「模型设置」中保存 Key，页面会继续当前任务。</div>}
        <div className="mobile-tabs" aria-label="项目视图"><button className={mobileTab === 'process' ? 'active' : ''} aria-pressed={mobileTab === 'process'} onClick={() => setMobileTab('process')}>过程</button><button className={mobileTab === 'results' ? 'active' : ''} aria-pressed={mobileTab === 'results'} onClick={() => setMobileTab('results')}>结果</button></div>
        <section className={`workspace ${mobileTab === 'results' ? 'show-results' : ''} ${!rightVisible ? 'right-collapsed' : ''}`}>
          <div id="conversation-pane" className="conversation">
            <div className="conversation-heading"><div><span className="eyebrow">MYATOM / AGENT SESSION</span><h2>对话</h2></div><button type="button" onClick={() => document.querySelector('.conversation-scroll')?.scrollTo({ top: 0, behavior: 'smooth' })}>查看历史 ↑</button></div>
            <div className="conversation-scroll" ref={conversationScrollRef}>
            <div className="conversation-content">
            {!project && <div className="empty-state" role="status"><div className="empty-number">…</div><h3>{syncState === 'disconnected' ? '暂时无法读取项目' : '正在载入项目'}</h3><p>项目、决策和版本以服务端记录为准。</p></div>}
            {project && !run && <div className="empty-state"><div className="empty-number">01</div><h3>项目已创建</h3><p>写下需求，Agent 将先梳理关键问题，再请你确认构建计划。</p></div>}
            {project && project.runs.length > 1 && <details className="history-turns"><summary>过往对话 · {project.runs.length - 1} 轮</summary>{project.runs.slice(1).map(previous => <div className="history-turn" key={previous.id}><span>你 · {formatTime(previous.created_at)}</span><p>{previous.request_text}</p><small><img src={brandMark} alt="" /> MYATOM · Agent　{STATUS[previous.status] || previous.status}{previous.version_id ? ` · 版本 #${previous.version_id.slice(0, 8)}` : ''}</small></div>)}</details>}
            {run && <>
              <div className="request-author"><strong>你</strong><time dateTime={run.created_at}>{formatTime(run.created_at)}</time></div><div className="request-card"><p>{originalRequest}</p></div>
              <ConversationTurns turns={turns} />
              {isActive && <div className="agent-speaker current-speaker"><img src={brandMark} alt="" /><strong>MYATOM</strong><small>正在处理</small></div>}
              {isActive && (cancellingRun === run.id ? <div className="agent-message current" role="status"><strong>正在取消任务</strong><p>收到取消请求后，我会在服务端停止并保留此前的版本。</p></div> : <RunProgress run={run} events={events} connected={syncState === 'connected'} />)}
              {(run.status === 'awaiting_clarification' || run.status === 'awaiting_plan') && <RunProgress run={run} events={events} connected={syncState === 'connected'} />}
              {isWaiting && <div className="decision-turn"><div className="agent-speaker current-speaker"><img src={brandMark} alt="" /><strong>MYATOM</strong></div><p className="decision-intro">{awaitingRequirement ? '还有几个问题需要确认。' : awaitingPlan ? '我整理好了构建计划，请确认或告诉我需要调整的地方。' : run.status === 'awaiting_budget' ? '当前额度已用尽，请选择需要增加的额度。' : run.card?.payload.failure_stage === 'source_validation' ? '源码检查仍有问题，请告诉我下一步怎么处理。' : '这一版未通过构建，请告诉我下一步怎么处理。'}</p>
              {conflictDraft && isWaiting && <div className="conflict-note" role="alert"><strong>卡片版本已变化，请核对最新内容</strong><p>以下是你刚才未提交成功的草稿，可复制后重新填写。</p><pre>{conflictDraft}</pre><button onClick={() => setConflictDraft('')}>关闭草稿提示</button></div>}
              {run.status === 'awaiting_clarification' && run.card?.type === 'clarification' && <div className="decision-card"><div className="card-heading"><span className="card-overline">需求澄清</span><span className="pending-badge">等待回复</span></div>
                {((run.card.payload as Clarification).questions || []).map(q => <div className="question" key={q.id}><label htmlFor={`answer-${q.id}`}><span>{q.text} {q.required && <b aria-label="必填">*</b>}</span></label>{q.default && <div className="suggestion"><small>建议答案：{q.default}</small><button type="button" disabled={busy} onClick={() => setAnswers(current => ({ ...current, [q.id]: q.default }))}>采用建议</button></div>}<input id={`answer-${q.id}`} value={answers[q.id] || ''} onChange={event => setAnswers(current => ({ ...current, [q.id]: event.target.value }))} placeholder="输入你的回答" maxLength={500} aria-required={q.required} />{!q.required && <button className="skip-question" disabled={busy} onClick={() => setAnswers(current => ({ ...current, [q.id]: '' }))}>不填写这题</button>}</div>)}
                {Boolean((run.card.payload as Clarification).assumptions?.length) && <details className="decision-details"><summary>查看已知条件</summary><ul className="plain-list">{(run.card.payload as Clarification).assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></details>}
                <div className="card-actions"><button type="button" disabled={busy} onClick={() => { setEditingOriginal(true); window.requestAnimationFrame(() => document.getElementById('new-run-request')?.focus()) }}>修改原需求</button></div></div>}
              {run.status === 'awaiting_plan' && run.card?.type === 'build_plan' && <div className="decision-card"><div className="card-heading"><span className="card-overline">构建计划</span><span className="pending-badge">等待回复</span></div><h3>{(run.card.payload as Plan).title}</h3><strong className="plan-list-heading">计划要做什么 · 尚未开始</strong><ul className="plan-highlights">{plannedTasks(run.card.payload as Plan).map((task, i) => <li key={i}>{task}</li>)}</ul>{(run.card.payload as Plan).change_set && <div className="iteration-summary"><strong>基于上一可用版本继续</strong><span>沿用 {(run.card.payload as Plan).change_set?.retained.length} 项 · 新增 {(run.card.payload as Plan).change_set?.added.length} 项 · 调整 {(run.card.payload as Plan).change_set?.modified.length} 项</span>{Boolean((run.card.payload as Plan).change_set?.removed.length) && <p>将删除：{(run.card.payload as Plan).change_set?.removed.join('；')}</p>}</div>}<details className="decision-details"><summary>查看完整计划与边界</summary><PlanView plan={run.card.payload as Plan} /></details><button type="button" className="plan-approval-choice" data-selected={feedback.trim() === '按这版计划开始生成'} aria-label={feedback.trim() === '按这版计划开始生成' ? '取消选用：按这版计划开始生成' : '选用：按这版计划开始生成'} aria-describedby="plan-approval-help" onClick={() => { setFeedback(current => current.trim() === '按这版计划开始生成' ? '' : '按这版计划开始生成'); window.requestAnimationFrame(() => document.getElementById('new-run-request')?.focus()) }}><span aria-hidden="true">{feedback.trim() === '按这版计划开始生成' ? '✓' : '→'}</span>{feedback.trim() === '按这版计划开始生成' ? '已选用：按这版计划开始生成' : '按这版计划开始生成'}</button><p id="plan-approval-help" className="plan-approval-help">选用后填入下方输入框；点击“发送”才会开始生成。</p>{project && project.versions.length >= 5 && <p className="version-limit-note">当前已有 5 个版本；新版本成功后将淘汰最早版本。</p>}</div>}
              {run.status === 'awaiting_budget' && run.card?.type === 'budget_extension' && <BudgetExtensionCard data={run.card.payload as BudgetData} choice={budgetChoice} onChange={(kind, selected) => setBudgetChoice(current => ({ ...current, [kind]: selected }))} />}
              {run.status === 'awaiting_repair' && run.card?.type === 'test_result' && <div className="decision-card repair-card"><div className="card-heading"><span className="card-overline">{run.card.payload.failure_stage === 'source_validation' ? '源码检查' : '构建检查'}</span><span className="pending-badge">等待回复</span></div><h3>{run.card.payload.failure_stage === 'source_validation' ? '源码还需调整' : '这一版尚未构建通过'}</h3>{run.card.payload.failure_summary && <FailureSummaryView summary={run.card.payload.failure_summary} />}<p>候选代码和检查记录已保留；现有可用版本未受影响。</p><p>{run.card.payload.failure_stage === 'source_validation' ? '可以要求继续修复一次，或指定修复方向。' : run.card.actions.includes('continue_repair') ? '可以要求继续修复、指定修复方向，或用现有代码重新构建。' : '环境恢复后，可以用现有代码重新构建。'}</p>{run.card.actions.includes('extend_auto_repair') && <button type="button" className="plan-approval-choice" data-selected={feedback.trim() === '增加30轮自动修复并继续'} onClick={() => { setFeedback(current => current.trim() === '增加30轮自动修复并继续' ? '' : '增加30轮自动修复并继续'); window.requestAnimationFrame(() => document.getElementById('new-run-request')?.focus()) }}>选用：增加 30 轮自动修复并继续</button>}<details className="support-id"><summary>查看问题编号</summary><code>{run.trace_id}</code></details></div>}
              {isWaiting && run.card && !['clarification', 'build_plan', 'test_result', 'budget_extension'].includes(run.card.type) && <div className="decision-card"><h3>暂不支持此决策卡</h3><p>卡片类型：{run.card.type}。请刷新状态，或联系项目维护者处理。</p></div>}
              {composer}
              </div>}
              {run.status === 'completed' && <div className="result-card"><span className="card-overline">本轮结果</span><h3>应用已生成并保存</h3><p>{run.card?.type === 'test_result' && run.card.payload.build?.ok ? '构建检查已通过。' : '请核对实际检查记录。'}可以打开这一版的预览，亲自试用。</p><div className="success-line">✓ 版本 #{run.version_id?.slice(0, 8)}</div><button onClick={openLatestVersion}>查看应用 →</button></div>}
              {['failed', 'budget_exceeded', 'cancelled'].includes(run.status) && <div className="result-card failure"><span className="card-overline">本轮结果</span><h3>{run.status === 'budget_exceeded' ? '额度已达上限' : run.card?.payload.failure_stage === 'plan' ? '生成计划失败' : run.card?.payload.failure_stage === 'commit_version' ? '版本保存失败' : STATUS[run.status]}</h3>{run.card?.payload.failure_summary ? <FailureSummaryView summary={run.card.payload.failure_summary} /> : <p>{run.error || '本次任务没有生成新版本。此前保存的版本仍可查看。'}</p>}{run.card?.payload.recovery_blocker && <p className="recovery-blocker">{run.card.payload.recovery_blocker}</p>}{run.card?.type === 'test_result' && (run.card.payload.failure_stage === 'build' || (!run.card.payload.failure_stage && Boolean(run.card.payload.build?.steps?.length))) && <div className="failure-checks"><strong>已执行的构建检查</strong>{run.card.payload.build?.steps?.length ? run.card.payload.build.steps.map((step, i) => <div className="build-step" key={i}><span>{step.command}</span><small>{step.seconds}s · {step.exit_code === 0 ? '通过' : `失败（exit ${step.exit_code}）`}</small></div>) : <p>没有可用的命令记录。</p>}<small>浏览器交互检查：未执行</small></div>}<p>{run.status === 'budget_exceeded' ? '已有版本不会被覆盖；可以明确增加额度并继续当前任务。' : '本轮已停止；已有版本不会被覆盖。'}</p><div className="failure-actions">{run.status === 'budget_exceeded' && <button className="primary" disabled={busy} onClick={openBudget}>查看扩额选项</button>}{run.card?.actions.includes('open_repair') && <button className="primary" disabled={busy} onClick={openRepair}>查看修复选项</button>}<button onClick={() => { setRequestText(run.request_text); setMobileTab('process'); document.getElementById('new-run-request')?.focus() }}>{run.card?.payload.failure_stage === 'plan' ? '查看需求并开始新一轮' : '修改需求并开始新一轮'}</button>{version && <button onClick={openLatestVersion}>查看已有版本</button>}</div><details className="support-id"><summary>需要反馈问题？</summary><p>向维护者提供问题编号：<code>{run.trace_id}</code></p><button type="button" onClick={() => navigator.clipboard.writeText(run.trace_id).then(() => setTraceCopied(true)).catch(() => setError('复制失败，请手动选中问题编号。'))}>{traceCopied ? '已复制' : '复制问题编号'}</button></details></div>}
              {['completed', 'failed', 'budget_exceeded', 'cancelled', 'awaiting_repair'].includes(run.status) && <RunProgress run={run} events={events} connected={syncState === 'connected'} />}
              {(isActive || isWaiting) && <button className="text-danger" disabled={busy || cancellingRun === run.id} onClick={cancel}>{cancellingRun === run.id ? '正在取消…' : '取消本次任务'}</button>}
            </>}
            </div>
            </div>
            {!isWaiting && composer}
          </div>
          <div className="layout-divider chat-divider" role="separator" tabIndex={0} aria-label="调整对话与内容区宽度" aria-orientation="vertical" aria-controls="conversation-pane results-pane" aria-valuemin={layout.range.chatMin} aria-valuemax={layout.range.chatMax} aria-valuenow={layout.current.chat} aria-valuetext={`对话区 ${Math.round(layout.current.chat)} 像素`} title="拖动调整对话宽度；方向键微调；双击恢复默认" onPointerDown={event => layout.start('chat', event)} onPointerMove={layout.move} onPointerUp={layout.finish} onPointerCancel={layout.cancel} onLostPointerCapture={layout.cancel} onKeyDown={event => layout.key('chat', event)} onDoubleClick={layout.reset} />
          <aside id="results-pane" className="results-panel" aria-label={RIGHT_LABEL[rightView]} hidden={!rightVisible}>
            <nav className="project-view-nav" aria-label="项目内容视图">{(['workbench', 'overview', 'documents', 'tests', 'versions'] as RightView[]).map(view => <button key={view} data-view={view} className={rightView === view ? 'active' : ''} aria-current={rightView === view ? 'page' : undefined} onClick={() => selectRightView(view)}><img src={RIGHT_ICON[view]} alt="" />{RIGHT_LABEL[view]}{view === 'tests' && run?.card?.type === 'test_result' && run.card.status === 'failed' && <i aria-label="有失败检查" />}</button>)}</nav>
            <div className={`right-content${rightView === 'workbench' ? ' workbench-content' : ''}${rightView === 'workbench' && version && workbenchTab === 'preview' ? ' preview-content' : ''}`}>{rightView === 'workbench' ? <h3 className="sr-only" ref={rightHeadingRef} tabIndex={-1}>产物预览</h3> : <div className="right-heading"><div><span className="eyebrow">PROJECT / {project?.title || projectId.slice(0, 8).toUpperCase()}</span><h3 ref={rightHeadingRef} tabIndex={-1}>{RIGHT_LABEL[rightView]}</h3></div><span>{project?.versions.length || 0} 个已存版本</span></div>}
            {rightView === 'workbench' && <>
              <div className="workbench-toolbar"><div className="workbench-tabs" aria-label="成果视图"><button className={workbenchTab === 'preview' ? 'active' : ''} aria-pressed={workbenchTab === 'preview'} onClick={() => setWorkbenchTab('preview')}>预览</button><button className={workbenchTab === 'code' ? 'active' : ''} aria-pressed={workbenchTab === 'code'} onClick={() => setWorkbenchTab('code')}>代码</button></div>{version && <select aria-label="选择生成版本" value={version.id} onChange={event => { setSelectedVersion(event.target.value); setSelectedFile(null) }}>{project?.versions.map(item => <option value={item.id} key={item.id}>#{item.id.slice(0, 8)} · {formatTime(item.created_at)}{item.id === project.active_version_id ? ' · 当前' : ''}</option>)}</select>}</div>
              {version && project?.active_version_id !== version.id && <div className="version-selection-status"><span>正在查看历史版本</span><button disabled={busy} onClick={() => activateVersion(version)}>设为当前版本</button></div>}{!version ? <div className="prebuild"><span className="prebuild-label"><i className="status-pin" />{isWaiting ? '生成前 / 等待确认' : isActive ? '生成中 / 请稍候' : '尚未生成版本'}</span><h3>{isWaiting ? '确认关键决定，再看结果。' : isActive ? 'Agent 正在完成这一版。' : '从需求开始，完成第一版。'}</h3><p>{isWaiting ? '左侧说明已确定的内容与下一步。这里不会显示不存在的应用或测试结果。' : isActive ? '生成与构建的真实进度会在左侧同步；通过检查后才能预览。' : '提交需求并确认计划后，预览和源码将在这里出现。'}</p><div className="prebuild-grid"><div><small>已知目标</small><b>{run?.request_text || '等待你提交需求'}</b></div><div><small>当前待办</small><b>{run ? PHASE[run.phase] || STATUS[run.status] || run.phase : '写下你的应用想法'}</b></div></div><div className="preview-placeholder"><img src={brandMark} alt="" /><b>尚无可预览版本</b><small>只有构建和预览检查通过的版本才会出现在这里。</small></div></div> : workbenchTab === 'preview' ? <div className="preview-workspace"><div className="preview-bar"><div><span className="window-dots" aria-hidden="true">● ● ●</span><strong>预览环境 · 版本 #{version.id.slice(0, 8)}</strong></div><button onClick={() => setPreviewReload(value => value + 1)}>重新载入</button></div>{previewState === 'error' ? <div className="preview-fallback" role="alert"><h4>该版本预览暂不可用</h4><p>{previewError}</p><div><button onClick={() => setPreviewReload(value => value + 1)}>重试预览</button><button onClick={() => setWorkbenchTab('code')}>查看代码</button></div></div> : <div className="preview-frame-wrap">{previewUrl && <iframe title={`项目 ${project?.title || ''} 的版本预览`} className={previewState === 'ready' ? 'ready' : ''} src={previewUrl} sandbox="allow-scripts allow-forms allow-same-origin" onLoad={event => onPreviewLoad(event.currentTarget)} onError={() => { setPreviewState('error'); setPreviewError('预览页面未能载入。') }} />}{previewState === 'loading' && <div className="preview-loading" role="status">正在载入真实应用预览…</div>}</div>}<div className="preview-data-note"><strong>数据保存</strong><span>{previewState === 'ready' ? '业务数据保存在当前浏览器的项目空间；同项目跨版本共用。请刷新核对；换浏览器或清除存储后无法恢复。' : '预览尚未载入，无法确认本次业务数据是否保存。'}</span><small>受信预览 · 非公网沙箱</small></div></div> : <div className="code-workspace"><div className="code-files"><strong>源码文件</strong><span>{version.manifest.files.length} 个文件 · {version.manifest.template}</span>{version.manifest.files.map(file => <button className={selectedFile === file.path ? 'active' : ''} key={file.path} onClick={() => setSelectedFile(file.path)}>{file.path}</button>)}</div><div className="code-reader"><div>{selectedFile || '选择左侧文件查看源码'}</div><pre>{selectedFile ? fileContent || '正在读取文件…' : '代码已保存。选择一个源码文件查看内容。'}</pre></div></div>}
            </>}
            {rightView === 'overview' && <OverviewPanel project={project} run={run} version={version} events={events} isWaiting={!!isWaiting} isActive={!!isActive} onWorkbench={() => selectRightView('workbench')} onOpenLatest={openLatestVersion} />}
            {rightView === 'documents' && <DocumentsPanel run={run} documentRun={documentRun} version={version} tab={docTab} onTab={selectDocTab} onWorkbench={() => selectRightView('workbench')} onOpenFile={openVersionFile} />}
            {rightView === 'tests' && <TestsPanel run={run} version={version} showBuildLog={showBuildLog} buildLogLoading={buildLogLoading} buildLog={buildLog} onToggleBuildLog={toggleBuildLog} />}
            {rightView === 'versions' && <VersionsPanel project={project} busy={busy} onPreview={item => { setSelectedVersion(item.id); setWorkbenchTab('preview'); selectRightView('workbench') }} onActivate={activateVersion} />}
            </div>
          </aside>
        </section>
        </>}
      </>}
      {error && <div className="toast" role="alert"><span>{error}</span><button onClick={() => setError('')} aria-label="关闭错误">×</button></div>}
    </main>
    {allProjectsOpen && <div className="all-projects-overlay"><button className="all-projects-backdrop" aria-label="关闭所有项目" onClick={() => setAllProjectsOpen(false)} /><div ref={allProjectsRef} className="all-projects-dialog" role="dialog" aria-modal="true" aria-labelledby="all-projects-title"><div className="all-projects-head"><h2 id="all-projects-title">所有项目</h2><button aria-label="关闭所有项目" onClick={() => setAllProjectsOpen(false)}>×</button></div><label className="all-projects-search"><span className="sr-only">搜索项目名称</span><input value={homeSearch} onChange={event => setHomeSearch(event.target.value)} placeholder="搜索项目名称" /></label><p className="all-projects-caption">{homeSearch ? `搜索结果 · ${visibleHomeProjects.length}` : `你的项目 · ${projects.length}`}</p><div className="all-projects-list">{visibleHomeProjects.map(item => <button key={item.id} className={item.id === projectId ? 'selected' : ''} onClick={() => { setAllProjectsOpen(false); navigate(item.id) }}><span className="project-icon" aria-hidden="true">{projectGlyph(item.title)}</span><span><strong>{item.title}</strong><small>{item.latest_status ? STATUS[item.latest_status] || item.latest_status : '尚未开始'}{item.latest_version_id ? ` · 版本 #${item.latest_version_id.slice(0, 8)}` : ''}</small></span>{item.id === projectId ? <em>当前项目</em> : <b aria-hidden="true">↗</b>}</button>)}{!visibleHomeProjects.length && <p className="all-projects-empty">{listLoading ? '正在加载项目…' : listError ? `项目列表暂不可用：${listError}` : homeSearch ? '没有找到项目。' : '还没有项目。'}</p>}</div><div className="all-projects-foot"><span>项目状态来自服务端</span><button onClick={() => { setAllProjectsOpen(false); startNewProject() }}>＋ 新建项目</button></div></div></div>}
  </div>
}

function OverviewPanel({ project, run, version, events, isWaiting, isActive, onWorkbench, onOpenLatest }: { project: Project | null; run: Run | null; version: Version | null; events: Event[]; isWaiting: boolean; isActive: boolean; onWorkbench: () => void; onOpenLatest: () => void }) {
  const latestVersion = project?.versions[0] || version
  const requirementsDone = !!run && (!!run.plan || !!run.approved_spec_version || ['planning', 'awaiting_plan', 'building', 'completed'].includes(run.status))
  const milestones = [
    { label: '需求已确认', done: requirementsDone, detail: requirementsDone ? `规格 ${run?.spec_version}` : '等待确认' },
    { label: '计划已确认', done: !!run?.approved_spec_version, detail: run?.approved_spec_version ? `规格 ${run.approved_spec_version}` : '等待确认' },
    { label: '版本已保存', done: !!latestVersion, detail: latestVersion ? formatTime(latestVersion.created_at) : '尚未生成' },
    { label: '浏览器验证', done: false, detail: '尚无执行证据' },
  ]
  const recent = events.filter(item => USER_ACTIVITY[item.type]).slice(-3).reverse()
  return <div className="right-content overview-page"><div className="overview-intro"><div><h4>从需求到版本，正在继续。</h4><p>当前可以继续修改应用；公开发布尚未完成。</p></div><button className="primary" onClick={onWorkbench}>返回产物预览　→</button></div><div className="overview-columns"><section><h4>项目阶段</h4><div className="milestone-list">{milestones.map((item, index) => <div className="milestone" key={item.label}><span className={item.done ? 'done' : ''}>{item.done ? '✓' : index + 1}</span><div><strong>{item.label}</strong><small>{item.detail}</small></div></div>)}</div></section><section><h4>项目目标</h4><p className="overview-goal">{run?.request_text || '尚未提交需求。'}</p><h4>最新版本</h4><button className="overview-version" disabled={!latestVersion} onClick={onOpenLatest}>{latestVersion ? `#${latestVersion.id.slice(0, 8)} 已保存　→` : '尚无已保存版本'}</button><small>{latestVersion ? `构建${latestVersion.manifest.build.ok ? '通过' : '失败'} · ${formatTime(latestVersion.created_at)}` : '确认计划后开始生成'}</small><h4>下一步</h4><p>{isWaiting ? '回到对话确认当前决策卡。' : isActive ? '观察实时进度，等待生成结果。' : latestVersion ? '继续迭代，或打开真实预览。' : '在对话中提交需求。'}</p></section></div><div className="overview-activity"><strong>最近进展</strong><div>{recent.map(item => <span key={item.event_id}>{formatTime(item.at)}　{USER_ACTIVITY[item.type]}</span>)}{!recent.length && <span>暂无进展</span>}</div></div></div>
}

type DocTab = 'requirements' | 'plan' | 'decisions' | 'files'
function DocumentsPanel({ run, documentRun, version, tab, onTab, onWorkbench, onOpenFile }: { run: Run | null; documentRun: Run | null; version: Version | null; tab: DocTab; onTab: (tab: DocTab) => void; onWorkbench: () => void; onOpenFile: (path: string) => void }) {
  const tabs: { id: DocTab; label: string }[] = [{ id: 'requirements', label: '需求' }, { id: 'plan', label: '计划' }, { id: 'decisions', label: '决定' }, { id: 'files', label: '文件' }]
  const plan = documentRun?.plan
  const currentPlan = run?.plan
  const historicalPlan = !!plan && documentRun?.id !== run?.id
  return <div className="right-content docs-page"><p className="right-description">需求、计划与决定按规格版本保留。</p><div className="docs-tabs" role="tablist" aria-label="文档分类">{tabs.map(item => <button role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'active' : ''} key={item.id} onClick={() => onTab(item.id)}>{item.label}</button>)}</div><div className="docs-layout"><div className="docs-article">{tab === 'requirements' && <><h4>需求说明</h4><p className="docs-meta">{run ? `本轮运行 / ${formatTime(run.created_at)} / 规格 ${run.spec_version}` : '尚未创建运行'}</p><section id="doc-goal"><span>01</span><div><h5>目标</h5><p>{run?.request_text || '尚未提交需求。'}</p></div></section><section id="doc-features"><span>02</span><div><h5>核心功能</h5>{currentPlan?.features.length ? <ul>{currentPlan.features.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p>确认需求后会显示计划中的功能。</p>}</div></section><section id="doc-data"><span>03</span><div><h5>数据与边界</h5>{currentPlan?.data_model.length ? <ul>{currentPlan.data_model.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p>尚未形成数据计划。</p>}</div></section></>}{tab === 'plan' && <><h4>{historicalPlan ? '历史构建计划' : '构建计划'}</h4><p className="docs-meta">{plan ? `${historicalPlan ? '历史运行 · ' : ''}规格 ${documentRun?.spec_version} · ${documentRun?.approved_spec_version ? '已批准' : '待确认'}` : '尚未生成计划'}</p>{plan ? <PlanView plan={plan} /> : <p>完成需求澄清后，计划会显示在这里。</p>}</>}{tab === 'decisions' && <><h4>决定记录</h4><p className="docs-meta">来自当前保存的运行状态。</p><div className="docs-decision"><strong>需求澄清</strong><span>{run?.spec_version && run.phase !== 'Clarify' ? `规格 ${run.spec_version}` : '尚未完成'}</span></div><div className="docs-decision"><strong>构建计划</strong><span>{run?.approved_spec_version ? `已批准规格 ${run.approved_spec_version}` : '尚未批准'}</span></div><p>如果需要修改已确认内容，请在产物预览页提交新一轮需求。</p></>}{tab === 'files' && <><h4>版本文件</h4><p className="docs-meta">{version ? `版本 #${version.id.slice(0, 8)} · ${version.manifest.files.length} 个文件` : '尚无已存版本'}</p>{version?.manifest.files.map(file => <button className="docs-file" key={file.path} onClick={() => onOpenFile(file.path)}><code>{file.path}</code><small>{file.bytes} B　→</small></button>)}{!version && <p>生成并保存版本后，文件清单会显示在这里。</p>}</>}</div><aside className="docs-toc"><strong>目录</strong>{tab === 'requirements' ? <><a href="#doc-goal">01　目标</a><a href="#doc-features">02　核心功能</a><a href="#doc-data">03　数据与边界</a></> : <span>{tabs.find(item => item.id === tab)?.label}</span>}</aside></div><div className="docs-foot"><strong>要修改已确认内容？</strong><p>在对话中提出新要求，形成新的运行与规格版本。</p><button onClick={onWorkbench}>返回产物预览 →</button></div></div>
}

function TestsPanel({ run, version, showBuildLog, buildLogLoading, buildLog, onToggleBuildLog }: { run: Run | null; version: Version | null; showBuildLog: boolean; buildLogLoading: boolean; buildLog: string | null; onToggleBuildLog: () => void }) {
  const currentRunResult = run?.card?.type === 'test_result'
  const canReadLog = currentRunResult && !!run
  const build = currentRunResult ? run.card?.payload.build : version?.manifest.build
  const steps = build?.steps || []
  const passed = steps.filter(step => step.exit_code === 0).length
  const total = steps.length + 1
  const diagnosis = currentRunResult ? run?.card?.payload.diagnosis : undefined
  const diagnosisPanel = diagnosis && <div className="test-explanation"><strong>失败诊断</strong><p>类别：{diagnosis.category} · 命令：{diagnosis.command || '无'} · {diagnosis.repairable ? '可尝试改代码修复' : '不适合自动改代码修复'}</p><p>{diagnosis.reason} · 证据：{diagnosis.evidence_ref}</p></div>
  return <div className="right-content tests-page"><p className="right-description">结论与证据对应当前运行或已存版本；未执行项单独列出。</p>{diagnosisPanel}<div className="test-summary"><strong>{passed} / {total}</strong><div><h4>{steps.length ? '检查已执行' : '尚无执行记录'}</h4><p>{currentRunResult ? `本轮运行 #${run?.id.slice(0, 8)}` : version ? `版本 #${version.id.slice(0, 8)}` : '本轮尚无保存版本'} · 浏览器检查尚无执行证据</p></div></div><div className="test-bars" aria-hidden="true">{steps.map((step, i) => <span className={step.exit_code === 0 ? 'pass' : 'fail'} key={i} />)}<span className="pending" /></div><div className="test-table-head"><span>检查项</span><span>结果</span><span>证据</span></div>{steps.map((step, i) => <div className="test-row" key={i}><span className={`test-icon ${step.exit_code === 0 ? 'pass' : 'fail'}`}>{step.exit_code === 0 ? '✓' : '!'}</span><div><strong>{step.command}</strong><small>执行 {step.seconds}s · exit {step.exit_code}</small></div><span className={`test-tag ${step.exit_code === 0 ? 'pass' : 'fail'}`}>{step.exit_code === 0 ? '通过' : '失败'}</span>{canReadLog ? <button onClick={onToggleBuildLog}>{showBuildLog ? '收起日志' : '查看日志'}</button> : <span className="no-evidence">仅有步骤摘要</span>}</div>)}<div className="test-row"><span className="test-icon pending">!</span><div><strong>浏览器检查</strong><small>暂无当前版本的真实交互执行记录</small></div><span className="test-tag pending">未执行</span><span className="no-evidence">暂无证据</span></div>{canReadLog && showBuildLog && <pre className="right-log">{buildLogLoading ? '正在读取日志…' : buildLog || '没有可用日志。'}</pre>}<div className="test-explanation"><strong>结果解释</strong><p>构建通过代表代码检查通过；浏览器流程需要实际运行后才能标记完成。</p></div></div>
}

function VersionsPanel({ project, busy, onPreview, onActivate }: { project: Project | null; busy: boolean; onPreview: (version: Version) => void; onActivate: (version: Version) => void }) {
  const versions = project?.versions || []
  const current = versions.find(item => item.id === project?.active_version_id)
  return <div className="right-content versions-page"><p className="right-description">每次成功生成会保存一份完整快照，最多保留 5 个可用版本。</p>
    <div className="versions-current"><span className="eyebrow">当前版本</span><h4>{current ? `#${current.id.slice(0, 8)}` : '尚无版本'}</h4><p>{current ? `保存于 ${formatTime(current.created_at)} · 构建${current.manifest.build.ok ? '通过' : '未通过'}` : '完成首次构建后，这里会显示当前版本。'}</p></div>
    <section className="versions-history" aria-label="版本记录"><h4>版本记录 <small>{versions.length} / 5</small></h4>{versions.length ? versions.map(item => <div className="version-row" key={item.id}><div className="version-row-main"><strong>版本 <code>#{item.id.slice(0, 8)}</code></strong>{item.id === project?.active_version_id && <span className="current-version-badge">当前版本</span>}<small>{formatTime(item.created_at)} · 构建{item.manifest.build.ok ? '通过' : '未通过'} · {item.manifest.files.length} 个文件</small></div><div className="version-row-actions"><button onClick={() => onPreview(item)}>查看预览</button>{item.id !== project?.active_version_id && <button className="primary" disabled={busy} onClick={() => onActivate(item)}>设为当前版本</button>}</div></div>) : <p className="versions-empty">还没有可用版本。确认计划并完成构建后，版本会保存在这里。</p>}</section>
    {versions.length > 0 && <p className="versions-data-note">切换当前版本只改变代码快照；浏览器中的业务数据不会随之回滚。请在切换后检查旧版能否读取现有数据。</p>}
  </div>
}

function PlanView({ plan }: { plan: Plan }) {
  const fieldType = { text: '文本', number: '数字', boolean: '是/否' }
  const legacyStorage = Boolean(plan.entities?.length) || /appData|写回服务端|服务端(?:保存|读写|数据|持久)/i.test([
    ...plan.features, ...plan.data_model, ...plan.acceptance, ...plan.tasks,
  ].join(' '))
  return <div className="plan-view">{plan.change_set && <section className="iteration-changes"><div className="card-subtitle">本轮修改</div>{plan.change_set.added.length > 0 && <p><strong>新增：</strong>{plan.change_set.added.join('；')}</p>}{plan.change_set.modified.length > 0 && <p><strong>调整：</strong>{plan.change_set.modified.map(item => `${item.before} → ${item.after}`).join('；')}</p>}{plan.change_set.removed.length > 0 && <p><strong>删除（确认后生效）：</strong>{plan.change_set.removed.join('；')}</p>}<details><summary>沿用上一版的功能（{plan.change_set.retained.length}）</summary><ul>{plan.change_set.retained.map((item, i) => <li key={i}>{item}</li>)}</ul></details></section>}<div className="card-subtitle">页面与流程</div><div className="plan-pages">{plan.pages.map((page, i) => <div key={i}><strong>{page.name}</strong><span>{page.purpose}</span></div>)}</div><div className="card-subtitle">将实现</div><ul className="check-list">{plan.features.map((item, i) => <li key={i}>{item}</li>)}</ul><div className="card-subtitle">数据与验收</div>{legacyStorage && <p className="recovery-blocker">这份历史计划依赖服务端业务存储，已超出当前交付物边界。新一轮需求须改用项目预览域 localStorage。</p>}<ul className="plain-list">{plan.data_model.map((item, i) => <li key={i}>{item}</li>)}</ul>{Boolean(plan.entities?.length) && <div className="entity-list" aria-label="历史服务端数据结构">{plan.entities?.map(entity => <div className="entity-card" key={entity.name}><strong>{entity.name}</strong><span>历史服务端保存方案 · 当前不支持</span><ul>{entity.fields.map(field => <li key={field.name}><code>{field.name}</code><span>{fieldType[field.type] || field.type}</span>{field.required && <b>必填</b>}</li>)}</ul></div>)}</div>}<div className="acceptance">{plan.acceptance.map((item, i) => <div key={i}><span>{String(i + 1).padStart(2, '0')}</span>{item}</div>)}</div><div className="plan-template">固定模板：{plan.template}</div>{plan.limitations.length > 0 && <div className="limitations">本轮限制：{plan.limitations.join('；')}</div>}</div>
}

export default App

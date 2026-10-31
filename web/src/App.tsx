import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useColumnLayout } from './useColumnLayout'
import catalog from '../../examples/catalog.json'
import brandLockup from '../../design/v3/icons/brand-lockup.svg'
import brandMark from '../../design/v3/icons/brand-mark.svg'
import workbenchIcon from '../../design/v3/icons/workbench.svg'
import overviewIcon from '../../design/v3/icons/overview.svg'
import docsIcon from '../../design/v3/icons/docs.svg'
import testsIcon from '../../design/v3/icons/tests.svg'
import publishIcon from '../../design/v3/icons/publish.svg'

type Example = (typeof catalog.examples)[number]

type Question = { id: string; text: string; default: string; required: boolean }
type Clarification = { summary: string; assumptions: string[]; questions: Question[] }
type PlanEntity = { name: string; fields: { name: string; type: 'text' | 'number' | 'boolean'; required: boolean }[] }
type Plan = { title: string; pages: { name: string; purpose: string }[]; features: string[]; data_model: string[]; entities?: PlanEntity[]; acceptance: string[]; tasks: string[]; limitations: string[]; template: string }
type FileInfo = { path: string; sha256: string; bytes: number }
type BuildStep = { command: string; exit_code: number; seconds: number }
type Card = { type: string; schema_version: number; card_id: string; run_id: string; status: string; payload: Clarification & Plan & { version_id?: string; build?: { ok: boolean; steps: BuildStep[] }; files?: FileInfo[]; browser_check?: string; diagnostics_ref?: string }; actions: string[] }
type Run = { id: string; project_id: string; request_text: string; status: string; phase: string; card: Card | null; card_id: string | null; spec_version: number; approved_spec_version: number | null; plan?: Plan | null; model_calls: number; tokens_used: number; fix_rounds: number; error: string | null; version_id: string | null; trace_id: string; created_at: string; updated_at: string }
type Version = { id: string; project_id: string; run_id: string; manifest: { files: FileInfo[]; build: { ok: boolean; steps: BuildStep[] }; template: string; preview: { status: string } | null; entities?: PlanEntity[] }; created_at: string }
type Project = { id: string; title: string; created_at: string; updated_at: string; runs: Run[]; versions: Version[] }
type ProjectSummary = Pick<Project, 'id' | 'title' | 'updated_at'> & {
  latest_status: string | null
  latest_phase: string | null
  latest_version_id: string | null
}
type Event = { run_id: string; seq: number; event_id: string; type: string; payload: Record<string, unknown>; at: string }
type RightView = 'workbench' | 'overview' | 'documents' | 'tests' | 'publish'
type PreviewResponse = { url: string; expires_at: string }

const STATUS: Record<string, string> = {
  clarifying: '正在梳理需求', awaiting_clarification: '等待需求确认', planning: '正在拟定计划',
  awaiting_plan: '等待计划确认', building: '正在生成代码', completed: '代码已保存', failed: '需要处理',
  cancelled: '已取消', budget_exceeded: '额度已达上限',
}
const PHASE: Record<string, string> = {
  Clarify: '需求澄清', WaitClarify: '需求确认', Plan: '制定计划', WaitPlan: '计划确认',
  Prepare: '准备模板', CodeLoop: '编写代码', BuildTest: '构建与测试', Diagnose: '诊断修复',
  Package: '保存版本', Done: '已完成', NeedsUser: '需要处理', Cancelled: '已取消',
}
const EVENT: Record<string, string> = {
  run_created: '需求已提交', phase: '阶段更新', card: '决策卡已生成', decision_submitted: '已提交确认',
  model_started: '模型正在处理', model_used: '模型用量已记录', model_response: '模型已响应', files_written: '源码已写入',
  build_result: '构建已完成', version_saved: '版本已保存', completed: '任务已完成',
  failed: '任务遇到问题', cancelled: '任务已取消', cancel_requested: '正在取消', budget_exceeded: '预算已达上限',
}
const RIGHT_LABEL: Record<RightView, string> = {
  workbench: '工作台', overview: '项目概览', documents: '项目文档', tests: '测试', publish: '发布',
}
const RIGHT_ICON: Record<RightView, string> = { workbench: workbenchIcon, overview: overviewIcon, documents: docsIcon, tests: testsIcon, publish: publishIcon }
const ROUTE_SEGMENT: Record<RightView, string> = { workbench: '', overview: '/overview', documents: '/docs', tests: '/tests', publish: '/publish' }
function parseRoute(path: string): { id: string | null; view: RightView } {
  const match = path.match(/^\/projects\/([^/]+)(?:\/(overview|docs|tests|publish))?\/?$/)
  const views: Record<string, RightView> = { overview: 'overview', docs: 'documents', tests: 'tests', publish: 'publish' }
  return { id: match?.[1] || null, view: views[match?.[2] || ''] || 'workbench' }
}
function projectGlyph(title: string): string { return [...title.trim()][0] || '项' }

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { credentials: 'same-origin', ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } })
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
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [project, setProject] = useState<Project | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [title, setTitle] = useState('')
  const [requestText, setRequestText] = useState('')
  const [selectedExampleId, setSelectedExampleId] = useState<string | null>(null)
  const [exampleFeedback, setExampleFeedback] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [editedRequest, setEditedRequest] = useState('')
  const [feedback, setFeedback] = useState('')
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
  const [rightHidden, setRightHidden] = useState(false)
  const [workbenchTab, setWorkbenchTab] = useState<'preview' | 'code'>('preview')
  const [streamState, setStreamState] = useState<'idle' | 'connecting' | 'live' | 'polling'>('idle')
  const [streamRetryKey, setStreamRetryKey] = useState(0)
  const [previewState, setPreviewState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewExpires, setPreviewExpires] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState('')
  const [previewReload, setPreviewReload] = useState(0)
  const [mobileTab, setMobileTab] = useState<'process' | 'results'>('process')
  const decisionKeys = useRef<Record<string, string>>({})
  const requestDrafts = useRef<Record<string, string>>({})
  const docTabsByProject = useRef<Record<string, DocTab>>({})
  const decisionDrafts = useRef<Record<string, { answers: Record<string, string>; editedRequest: string; feedback: string }>>({})
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
  const documentRun = run?.plan ? run : project?.runs.find(item => item.approved_spec_version && item.plan) || null
  const version = project?.versions.find(item => item.id === selectedVersion) || project?.versions[0] || null
  const isActive = run && ['clarifying', 'planning', 'building'].includes(run.status)
  const isWaiting = run && ['awaiting_clarification', 'awaiting_plan'].includes(run.status)
  const clarification = run?.card?.type === 'clarification' ? run.card.payload as Clarification : null
  const canConfirmClarification = clarification?.questions.every(q => Object.prototype.hasOwnProperty.call(answers, q.id) && (!q.required || !!answers[q.id]?.trim())) ?? false

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
    if (activeProjectId.current !== id) return
    setProject(data)
    if (data.runs[0]) {
      const runId = data.runs[0].id
      if (eventCursor.current.runId !== runId) {
        eventCursor.current = { runId, seq: 0 }
        setEvents([])
      }
      const result = await api<{ events: Event[] }>(`/runs/${runId}/events?after_seq=${eventCursor.current.seq}`)
      if (activeProjectId.current !== id || eventCursor.current.runId !== runId) return
      if (result.events.length) {
        eventCursor.current.seq = Math.max(eventCursor.current.seq, ...result.events.map(item => item.seq))
        setEvents(previous => {
          const bySeq = new Map(previous.map(item => [item.seq, item]))
          result.events.forEach(item => bySeq.set(item.seq, item))
          return [...bySeq.values()].sort((a, b) => a.seq - b.seq)
        })
      }
    } else { setEvents([]); eventCursor.current = { runId: '', seq: 0 } }
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
    if (!projectId) { setProject(null); setEvents([]); return }
    const handleFailure = (err: unknown) => {
      if (activeProjectId.current !== projectId) return
      setSyncState('disconnected')
      if (err instanceof ApiError && [403, 404].includes(err.status)) setAccessError(true)
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
      if (id === activeProjectId.current) { if (id) refreshProject(id).catch(() => undefined); return }
      requestDrafts.current[activeProjectId.current || 'home'] = requestText
      setRequestText(requestDrafts.current[id || 'home'] || '')
      setDocTab(id ? docTabsByProject.current[id] || 'requirements' : 'requirements')
      activeProjectId.current = id
      eventCursor.current = { runId: '', seq: 0 }
      setProject(null); setEvents([]); setProjectId(id); setSelectedVersion(null); setSelectedFile(null); setAccessError(false); setSyncState('syncing')
      setSwitcherOpen(false)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [requestText, refreshProject])
  useEffect(() => {
    if (!run?.card_id) return
    const key = `${run.id}:${run.card_id}:${run.spec_version}`
    if (decisionDraftKey.current !== key) return
    decisionDrafts.current[key] = { answers, editedRequest, feedback }
  }, [run?.id, run?.card_id, run?.spec_version, answers, editedRequest, feedback])
  useEffect(() => {
    const draft = run?.card_id ? decisionDrafts.current[`${run.id}:${run.card_id}:${run.spec_version}`] : null
    decisionDraftKey.current = run?.card_id ? `${run.id}:${run.card_id}:${run.spec_version}` : null
    if (run?.card?.type === 'clarification') {
      setAnswers(draft?.answers || {})
      setEditedRequest(draft?.editedRequest ?? run.request_text)
    }
    setFeedback(draft?.feedback || '')
  }, [run?.card_id, run?.spec_version])
  useEffect(() => {
    if (!run?.card_id || !['awaiting_clarification', 'awaiting_plan'].includes(run.status)) return
    const frame = window.requestAnimationFrame(() => {
      const scroll = conversationScrollRef.current
      const card = scroll?.querySelector<HTMLElement>('.decision-card')
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
  useEffect(() => { setBuildLog(null); setShowBuildLog(false) }, [run?.id])
  useEffect(() => {
    if (!version || rightView !== 'workbench' || workbenchTab !== 'preview') return
    let live = true
    setPreviewState('loading'); setPreviewUrl(null); setPreviewExpires(null); setPreviewError('')
    api<PreviewResponse>(`/versions/${version.id}/preview`).then(result => {
      if (!live) return
      const url = new URL(result.url, window.location.href)
      if (!['http:', 'https:'].includes(url.protocol) || url.origin === window.location.origin) throw new Error('预览地址未与工作台隔离，已阻止载入。')
      if (['localhost', '127.0.0.1'].includes(url.hostname) && !['localhost', '127.0.0.1'].includes(window.location.hostname)) throw new Error('此版本只有本机预览地址，当前访问环境无法打开。')
      setPreviewExpires(result.expires_at)
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
    setProject(null); setEvents([]); setSelectedVersion(null); setSelectedFile(null)
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
    setRightHidden(false)
  }
  function selectRightView(view: RightView) {
    if (!projectId) return
    setRightHidden(false)
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
    if (project?.versions[0]) setSelectedVersion(project.versions[0].id)
    setWorkbenchTab('preview')
    selectRightView('workbench')
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
    if (requestText.trim().length < 10) { setError('请至少用 10 个字描述新需求。'); return }
    setBusy(true); setError('')
    try {
      const key = runKey.current || makeKey(); runKey.current = key
      await api(`/projects/${project.id}/runs`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ request_text: requestText.trim() }) })
      runKey.current = null; setRequestText(''); setEvents([])
      await refreshProject(project.id)
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  async function decide(action: string) {
    if (!run?.card_id || busy || !project || !run.card?.actions.includes(action)) return
    const payload = { card_id: run.card_id, spec_version: run.spec_version, action,
      answers: action === 'confirm_clarification' ? answers : undefined,
      request_text: action === 'revise_clarification' ? editedRequest.trim() : undefined,
      feedback: action === 'revise_plan' ? feedback : undefined }
    const keyName = `${run.id}:${run.card_id}:${JSON.stringify(payload)}`
    const key = decisionKeys.current[keyName] || makeKey(); decisionKeys.current[keyName] = key
    setBusy(true); setError('')
    try {
      await api(`/runs/${run.id}/decisions`, { method: 'POST', headers: { 'Idempotency-Key': key },
        body: JSON.stringify(payload) })
      delete decisionKeys.current[keyName]
      setConflictDraft('')
      await refreshProject(project.id)
    } catch (err) {
      setError((err as Error).message)
      if (err instanceof ApiError && err.status === 409) {
        setConflictDraft(action === 'confirm_clarification' ? JSON.stringify({ 原需求: editedRequest, 回答: answers }, null, 2) : feedback || '确认前的计划版本已变化')
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
      <div className="sidebar-foot">访客空间{projectId && <button className="layout-reset" onClick={layout.reset} disabled={!layout.enabled}>恢复默认布局</button>}</div>
    </aside>
    {projectId && <div className="layout-divider sidebar-divider" role="separator" tabIndex={0} aria-label="调整导航栏宽度" aria-orientation="vertical" aria-controls="project-sidebar project-main" aria-valuemin={layout.range.sidebarMin} aria-valuemax={layout.range.sidebarMax} aria-valuenow={layout.current.sidebar} aria-valuetext={`导航栏 ${Math.round(layout.current.sidebar)} 像素`} title="拖动调整导航宽度；方向键微调；双击恢复默认" onPointerDown={event => layout.start('sidebar', event)} onPointerMove={layout.move} onPointerUp={layout.finish} onPointerCancel={layout.cancel} onLostPointerCapture={layout.cancel} onKeyDown={event => layout.key('sidebar', event)} onDoubleClick={layout.reset} />}
    {showProjects && <button className="drawer-scrim" aria-label="关闭项目列表" onClick={() => setShowProjects(false)} />}

    <main id="project-main" className={`main ${!projectId ? 'home-main' : ''}`}>
      {!projectId ? <>
        <header className="topbar"><div className="topbar-main"><button className="projects-toggle" onClick={openProjects} aria-label="打开项目列表">☰ <span>项目</span></button><strong>{homeView === 'new' ? '新建项目' : '所有项目'}</strong></div></header>
        {homeView === 'new' ? <div className="welcome v7-home">
          <h1 aria-label="今天想做什么？"><span aria-hidden="true">{heroText}</span><span className="typing-caret" aria-hidden="true" /></h1>
          <section className="start-project" aria-label="新项目需求"><div className="form-card"><label className="sr-only" htmlFor="project-request">描述你想创建的应用</label><textarea id="project-request" value={requestText} onChange={event => { setRequestText(event.target.value); editExampleDraft() }} placeholder="例如：做一个可以安排番茄钟的待办应用…" maxLength={5000} rows={3} /><div className="start-bottom"><span className="request-count">{requestText.length} / 5000</span><button className="primary" disabled={busy} onClick={create}>{busy ? '正在创建…' : '创建项目　→'}</button></div><details className="project-title-option"><summary>添加项目名称（可选）</summary><label htmlFor="project-title">项目名称</label><input id="project-title" value={title} onChange={event => { setTitle(event.target.value); editExampleDraft() }} placeholder="给项目起个名字" maxLength={100} /></details><div className="example-feedback" role="status" aria-live="polite">{exampleFeedback}</div></div></section>
          <section className="examples-panel" aria-labelledby="examples-heading"><h2 id="examples-heading">试试这些精选样例</h2><div className="example-list">{catalog.examples.map(example => <button type="button" className={`example-card ${selectedExampleId === example.id ? 'selected' : ''}`} aria-pressed={selectedExampleId === example.id} key={example.id} onClick={() => applyExample(example)}><strong>{example.title}</strong><span>{example.subtitle}</span><em>{selectedExampleId === example.id ? '✓ 已填入' : '↗'}</em></button>)}</div><p className="examples-note">样例只填入需求草稿，创建前仍可编辑。</p></section>
        </div> : <div className="welcome v7-projects"><section className="home-projects" aria-labelledby="home-projects-heading"><div className="home-projects-head"><div><span className="section-kicker">PROJECTS / 你的工作</span><h1 id="home-projects-heading">所有项目</h1><p>继续未完成的任务，或查看已保存的成果。</p></div><label className="home-search"><span className="sr-only">搜索项目</span><input value={homeSearch} onChange={event => setHomeSearch(event.target.value)} placeholder="搜索项目" /></label></div><div className="project-table"><div className="project-table-head"><span>项目</span><span>当前状态</span><span>最近版本</span><span>更新时间</span></div>{visibleHomeProjects.map(item => <button key={item.id} className="project-table-row" onClick={() => navigate(item.id)}><span className="project-title-cell"><span className="project-icon" aria-hidden="true">{projectGlyph(item.title)}</span><span><strong>{item.title}</strong><small>Web 应用项目</small></span></span><span>{item.latest_status ? STATUS[item.latest_status] || item.latest_status : '尚未开始'}</span><span>{item.latest_version_id ? `#${item.latest_version_id.slice(0, 8)}` : '—'}</span><span>{formatTime(item.updated_at)}　→</span></button>)}{!visibleHomeProjects.length && <div className="project-table-empty">{listLoading ? '正在加载项目…' : listError ? <>项目列表暂不可用：{listError} <button onClick={() => refreshList().catch(() => undefined)}>重试</button></> : homeSearch ? '没有匹配的项目。' : '还没有项目。写下第一条需求开始。'}</div>}</div><button className="secondary" onClick={startNewProject}>＋ 新建项目</button></section></div>}
      </> : <>
        <header className="topbar project-topbar"><div className="topbar-main"><button className="projects-toggle" onClick={openProjects} aria-label="打开项目列表">☰ <span>项目</span></button><span className="identity-kicker">当前项目</span><button ref={switcherButtonRef} className="top-project-switch" aria-haspopup="dialog" aria-expanded={switcherOpen} onClick={() => setSwitcherOpen(value => !value)}>{project?.title || '正在加载项目'} <span aria-hidden="true">⌄</span></button><span className={`status-pill ${run?.status || ''}`}>{version ? `代码已保存 · #${version.id.slice(0, 8)}` : run ? STATUS[run.status] || run.status : '等待需求'}</span></div><div className="top-actions"><button onClick={() => setRightHidden(value => !value)} aria-expanded={!rightHidden} aria-controls="results-pane">{rightHidden ? '打开右侧' : '收起右侧'}</button><button onClick={layout.reset} disabled={!layout.enabled}>恢复默认布局</button><span className="top-status" aria-live="polite"><small>{syncState === 'disconnected' ? '连接中断 · 任务可能仍在运行' : syncState === 'syncing' ? '正在同步服务端状态' : `已保存 ${formatTime(project?.updated_at)} · ${streamState === 'live' ? '实时连接' : streamState === 'polling' ? '定时更新' : streamState === 'connecting' ? '正在恢复连接' : '状态已同步'}`}</small></span></div></header>
        {accessError ? <div className="empty-state" role="alert"><div className="empty-number">!</div><h3>无法打开此项目</h3><p>项目不存在，或当前访客没有访问权限。请检查项目链接与访问凭证。</p><button className="primary" onClick={() => navigate(null)}>返回首页</button></div> : <>
        {(syncState === 'disconnected' || streamState === 'polling') && <div className="connection-banner" role="status"><span>{syncState === 'disconnected' ? `无法同步最新状态；上次同步 ${formatTime(lastSynced || undefined)}。任务可能仍在运行。` : '实时连接中断，正在用定时更新补齐活动。'}</span><button onClick={() => { setSyncState('syncing'); setStreamRetryKey(value => value + 1); refreshProject(projectId).catch(() => setSyncState('disconnected')) }}>重新连接</button></div>}
        <div className="mobile-tabs" aria-label="工作台视图"><button className={mobileTab === 'process' ? 'active' : ''} aria-pressed={mobileTab === 'process'} onClick={() => setMobileTab('process')}>过程</button><button className={mobileTab === 'results' ? 'active' : ''} aria-pressed={mobileTab === 'results'} onClick={() => setMobileTab('results')}>结果</button></div>
        <section className={`workspace ${mobileTab === 'results' ? 'show-results' : ''} ${rightHidden ? 'right-collapsed' : ''}`}>
          <div id="conversation-pane" className="conversation">
            <div className="conversation-heading"><div><span className="eyebrow">MYATOM / AGENT SESSION</span><h2>对话</h2></div><button type="button" onClick={() => document.querySelector('.conversation-scroll')?.scrollTo({ top: 0, behavior: 'smooth' })}>查看历史 ↑</button></div>
            <div className="conversation-scroll" ref={conversationScrollRef}>
            {!project && <div className="empty-state" role="status"><div className="empty-number">…</div><h3>{syncState === 'disconnected' ? '暂时无法读取项目' : '正在载入项目'}</h3><p>项目、决策和版本以服务端记录为准。</p></div>}
            {project && !run && <div className="empty-state"><div className="empty-number">01</div><h3>项目已创建</h3><p>写下需求，Agent 将先梳理关键问题，再请你确认构建计划。</p></div>}
            {project && project.runs.length > 1 && <details className="history-turns"><summary>过往对话 · {project.runs.length - 1} 轮</summary>{project.runs.slice(1).map(previous => <div className="history-turn" key={previous.id}><span>你 · {formatTime(previous.created_at)}</span><p>{previous.request_text}</p><small><img src={brandMark} alt="" /> MYATOM · Agent　{STATUS[previous.status] || previous.status}{previous.version_id ? ` · 版本 #${previous.version_id.slice(0, 8)}` : ''}</small></div>)}</details>}
            {run && <>
              <div className="section-head"><span>当前任务</span><span>RUN {run.id.slice(0, 8)}</span></div>
              <div className="request-author"><strong>你</strong><time dateTime={run.created_at}>{formatTime(run.created_at)}</time></div><div className="request-card"><p>{run.request_text}</p></div>
              <div className={`journey ${run.status === 'completed' ? 'visually-compact' : ''}`}><span className="journey-line" /><span className="journey-step done">1</span><span>需求</span><span className={`journey-step ${['awaiting_plan', 'building', 'completed'].includes(run.status) ? 'done' : 'current'}`}>2</span><span>计划</span><span className={`journey-step ${run.status === 'completed' ? 'done' : run.status === 'building' ? 'current' : ''}`}>3</span><span>构建</span></div>
              <div className="agent-speaker"><img src={brandMark} alt="" /><strong>MYATOM · Agent</strong><small>当前</small></div>
              {run.approved_spec_version && run.plan && <div className="confirmed-card"><div className="confirmed-card-heading"><strong>已确认需求</strong><small>规格 {run.approved_spec_version}</small></div><div className="confirmed-card-body"><strong>本次将完成</strong>{run.plan.features.slice(0, 3).map((item, index) => <div key={index}><b>{String(index + 1).padStart(2, '0')}</b><span title={item}>{item}</span></div>)}<button onClick={() => { selectDocTab('plan'); selectRightView('documents') }}>查看完整计划 →</button></div></div>}
              {(isActive || isWaiting) && <div className="progress-card" role="status"><span className="card-overline">当前阶段</span><div className="progress-title"><span className={isActive ? 'pulse' : 'pause'} aria-hidden="true" /> <strong>{PHASE[run.phase] || run.phase}</strong></div><p>{cancellingRun === run.id ? '正在取消；服务端确认后会显示最终状态。' : isActive ? 'Agent 正在处理，阶段与结果将从服务端同步。' : '正在等待你的确认；确认前不会生成代码。'}</p>{run.phase === 'Diagnose' && <p>正在进行第 {run.fix_rounds}/2 轮修复。</p>}<div className="metric-row"><span>模型调用 <b>{run.model_calls}</b></span><span>Token <b>{run.tokens_used}</b></span><span>修复轮次 <b>{run.fix_rounds}</b></span></div><details className="trace-details"><summary>运行详情</summary><code>Trace {run.trace_id}</code><p>已批准计划版本：{run.approved_spec_version ?? '尚未确认'}</p></details></div>}
              {conflictDraft && isWaiting && <div className="conflict-note" role="alert"><strong>卡片版本已变化，请核对最新内容</strong><p>以下是你刚才未提交成功的草稿，可复制后重新填写。</p><pre>{conflictDraft}</pre><button onClick={() => setConflictDraft('')}>关闭草稿提示</button></div>}
              {run.status === 'awaiting_clarification' && run.card?.type === 'clarification' && <div className="decision-card"><div className="card-heading"><span className="card-overline">01 / 需求澄清</span><span className="pending-badge">需要你确认</span></div><h3>先把关键问题说清楚</h3><p className="card-summary">{(run.card.payload as Clarification).summary}</p>
                <div className="card-subtitle">当前假设</div><ul className="plain-list">{((run.card.payload as Clarification).assumptions || []).map((a, i) => <li key={i}>{a}</li>)}{!(run.card.payload as Clarification).assumptions?.length && <li>暂无需要确认的假设</li>}</ul>
                {((run.card.payload as Clarification).questions || []).map(q => <div className="question" key={q.id}><label htmlFor={`answer-${q.id}`}><span>{q.text} {q.required && <b aria-label="必填">*</b>}</span></label>{q.default && <div className="suggestion"><small>建议答案：{q.default}</small><button type="button" disabled={busy} onClick={() => setAnswers(current => ({ ...current, [q.id]: q.default }))}>采用建议</button></div>}<input id={`answer-${q.id}`} value={answers[q.id] || ''} onChange={event => setAnswers(current => ({ ...current, [q.id]: event.target.value }))} placeholder="输入你的回答" maxLength={500} aria-required={q.required} />{!q.required && <button className="skip-question" disabled={busy} onClick={() => setAnswers(current => ({ ...current, [q.id]: '' }))}>不填写这题</button>}</div>)}
                {run.card.actions.includes('revise_clarification') && <div className="request-edit"><label htmlFor="edited-request">修改原需求</label><textarea id="edited-request" value={editedRequest} onChange={event => setEditedRequest(event.target.value)} rows={3} minLength={10} maxLength={5000} /><small>{editedRequest.length} / 5000 字 · 修改后会重新澄清，不会直接生成代码。</small></div>}
                <div className="card-actions">{run.card.actions.includes('revise_clarification') && <button disabled={busy || editedRequest.trim().length < 10 || editedRequest.trim() === run.request_text} onClick={() => decide('revise_clarification')}>按修改后的需求重新澄清</button>}<button className="primary" disabled={busy || !canConfirmClarification} onClick={() => decide('confirm_clarification')}>{busy ? '正在提交…' : '确认这些需求 →'}</button></div><div className="card-foot">建议答案需要明确点击“采用建议” · 确认后将生成构建计划 · 版本 {run.spec_version}</div></div>}
              {run.status === 'awaiting_plan' && run.card?.type === 'build_plan' && <div className="decision-card"><div className="card-heading"><span className="card-overline">02 / BUILD PLAN</span><span className="pending-badge">需要你确认</span></div><h3>{(run.card.payload as Plan).title}</h3><PlanView plan={run.card.payload as Plan} /><label className="feedback"><span>希望调整计划？</span><textarea value={feedback} onChange={event => setFeedback(event.target.value)} placeholder="写下要修改的范围、页面或验收点，系统将重新生成一版计划供确认" rows={3} maxLength={2000} /></label><div className="card-actions">{run.card.actions.includes('return_to_clarification') && <button disabled={busy} onClick={() => decide('return_to_clarification')}>返回需求澄清</button>}<button disabled={busy || !feedback.trim()} onClick={() => decide('revise_plan')}>提交修改意见，生成新版计划</button><button className="primary" disabled={busy} onClick={() => decide('approve_plan')}>{busy ? '正在提交…' : '确认并开始生成 →'}</button></div><div className="card-foot">确认后开始消耗模型额度并写入源码 · 当前计划版本 {run.spec_version}</div></div>}
              {run.status === 'completed' && <div className="result-card"><span className="card-overline">03 / 构建结果</span><h3>代码已生成并保存</h3><p>{run.card?.type === 'test_result' && run.card.payload.build?.ok ? '构建检查已通过。' : '请在右侧核对实际检查记录。'}可在右侧打开该版本的真实预览或查看源码。</p><div className="success-line">✓ 已批准计划版本 {run.approved_spec_version} · 源码版本 {run.version_id?.slice(0, 8)}</div></div>}
              {['failed', 'budget_exceeded', 'cancelled'].includes(run.status) && <div className="result-card failure"><span className="card-overline">任务结果</span><h3>{STATUS[run.status]}</h3><p>{run.error || '本次任务没有生成新版本。此前保存的版本仍可查看。'}</p>{run.card?.type === 'test_result' && <div className="failure-checks"><strong>已执行的构建检查</strong>{run.card.payload.build?.steps?.length ? run.card.payload.build.steps.map((step, i) => <div className="build-step" key={i}><span>{step.command}</span><small>{step.seconds}s · {step.exit_code === 0 ? '通过' : `失败（exit ${step.exit_code}）`}</small></div>) : <p>没有可用的命令记录。</p>}<small>浏览器交互检查：未执行</small></div>}<p>已尝试修复 {run.fix_rounds} 轮；本轮停止，已有版本不会被覆盖。</p><button onClick={() => { setRequestText(run.request_text); setMobileTab('process'); document.getElementById('new-run-request')?.focus() }}>用相同需求重新开始</button></div>}
              {run.card?.type === 'test_result' && Boolean(run.card.payload.build?.steps?.length || run.card.payload.diagnostics_ref) && <div className="build-log"><button aria-expanded={showBuildLog} onClick={toggleBuildLog}>{showBuildLog ? '收起构建日志' : '查看构建日志'}</button>{showBuildLog && <div role="region" aria-label="构建日志">{buildLogLoading ? <p>正在读取日志…</p> : <pre>{buildLog}</pre>}</div>}</div>}
              {isWaiting && run.card && !['clarification', 'build_plan'].includes(run.card.type) && <div className="decision-card"><h3>暂不支持此决策卡</h3><p>卡片类型：{run.card.type}。请刷新状态，或联系项目维护者处理。</p></div>}
              <details className="activity-details"><summary>过程记录 · {events.length} 条</summary><div className="activity-list">{events.map(item => <div className="activity" key={item.event_id}><span className="activity-point" aria-hidden="true" /><div><strong>{item.type === 'phase' ? PHASE[String(item.payload.phase)] || '阶段更新' : EVENT[item.type] || item.type}</strong>{item.type === 'build_result' && <small>{item.payload.ok ? '命令通过' : '命令失败，等待后续结果'}</small>}{item.type === 'model_response' && item.payload.finish_reason === 'length' && <small>输出达到上限，正在调整后重试</small>}</div><time dateTime={item.at}>{formatTime(item.at)}</time></div>)}</div></details>
              {(isActive || isWaiting) && <button className="text-danger" disabled={busy || cancellingRun === run.id} onClick={cancel}>{cancellingRun === run.id ? '正在取消…' : '取消本次任务'}</button>}
            </>}
            </div>
            {project && canStartNew && <div className="new-run-card"><label htmlFor="new-run-request">继续迭代</label><textarea id="new-run-request" value={requestText} onChange={event => { setRequestText(event.target.value); runKey.current = null }} rows={2} maxLength={5000} placeholder="描述你想修改的地方…" /><div className="form-bottom"><span>新需求将形成下一版本 · {requestText.length} / 5000</span><button className="primary" aria-label="开始新一轮需求" disabled={busy} onClick={submitNewRun}>↑</button></div></div>}
          </div>
          <div className="layout-divider chat-divider" role="separator" tabIndex={0} aria-label="调整对话与内容区宽度" aria-orientation="vertical" aria-controls="conversation-pane results-pane" aria-valuemin={layout.range.chatMin} aria-valuemax={layout.range.chatMax} aria-valuenow={layout.current.chat} aria-valuetext={`对话区 ${Math.round(layout.current.chat)} 像素`} title="拖动调整对话宽度；方向键微调；双击恢复默认" onPointerDown={event => layout.start('chat', event)} onPointerMove={layout.move} onPointerUp={layout.finish} onPointerCancel={layout.cancel} onLostPointerCapture={layout.cancel} onKeyDown={event => layout.key('chat', event)} onDoubleClick={layout.reset} />
          <aside id="results-pane" className="results-panel" aria-label={RIGHT_LABEL[rightView]} hidden={rightHidden}>
            <nav className="project-view-nav" aria-label="项目内容视图">{(['workbench', 'overview', 'documents', 'tests', 'publish'] as RightView[]).map(view => <button key={view} data-view={view} className={rightView === view ? 'active' : ''} aria-current={rightView === view ? 'page' : undefined} onClick={() => selectRightView(view)}><img src={RIGHT_ICON[view]} alt="" />{RIGHT_LABEL[view]}{view === 'tests' && run?.card?.type === 'test_result' && run.card.status === 'failed' && <i aria-label="有失败检查" />}</button>)}</nav>
            <div className="right-content"><div className="right-heading"><div><span className="eyebrow">PROJECT / {project?.title || projectId.slice(0, 8).toUpperCase()}</span><h3 ref={rightHeadingRef} tabIndex={-1}>{rightView === 'workbench' ? '预览与文件' : RIGHT_LABEL[rightView]}</h3></div><span>{project?.versions.length || 0} 个已存版本</span></div>
            {rightView === 'workbench' && <>
              <div className="workbench-toolbar"><div className="workbench-tabs" aria-label="成果视图"><button className={workbenchTab === 'preview' ? 'active' : ''} aria-pressed={workbenchTab === 'preview'} onClick={() => setWorkbenchTab('preview')}>预览</button><button className={workbenchTab === 'code' ? 'active' : ''} aria-pressed={workbenchTab === 'code'} onClick={() => setWorkbenchTab('code')}>代码</button></div>{version && <select aria-label="选择生成版本" value={version.id} onChange={event => { setSelectedVersion(event.target.value); setSelectedFile(null) }}>{project?.versions.map((item, index) => <option value={item.id} key={item.id}>v{project.versions.length - index} · {formatTime(item.created_at)}</option>)}</select>}</div>
              {!version ? <div className="prebuild"><span className="prebuild-label"><i className="status-pin" />{isWaiting ? '生成前 / 等待确认' : isActive ? '生成中 / 请稍候' : '尚未生成版本'}</span><h3>{isWaiting ? '确认关键决定，再看结果。' : isActive ? 'Agent 正在完成这一版。' : '从需求开始，完成第一版。'}</h3><p>{isWaiting ? '左侧说明已确定的内容与下一步。这里不会显示不存在的应用或测试结果。' : isActive ? '生成与构建的真实进度会在左侧同步；通过检查后才能预览。' : '提交需求并确认计划后，预览和源码将在这里出现。'}</p><div className="prebuild-grid"><div><small>已知目标</small><b>{run?.request_text || '等待你提交需求'}</b></div><div><small>当前待办</small><b>{run ? PHASE[run.phase] || STATUS[run.status] || run.phase : '写下你的应用想法'}</b></div></div><div className="preview-placeholder"><img src={brandMark} alt="" /><b>尚无可预览版本</b><small>只有构建和预览检查通过的版本才会出现在这里。</small></div></div> : workbenchTab === 'preview' ? <div className="preview-workspace"><div className="preview-bar"><div><span className="window-dots" aria-hidden="true">● ● ●</span><strong>预览环境 · 版本 #{version.id.slice(0, 8)}</strong></div><button onClick={() => setPreviewReload(value => value + 1)}>重新载入</button></div>{previewState === 'error' ? <div className="preview-fallback" role="alert"><h4>该版本预览暂不可用</h4><p>{previewError}</p><div><button onClick={() => setPreviewReload(value => value + 1)}>重试预览</button><button onClick={() => setWorkbenchTab('code')}>查看代码</button></div></div> : <div className="preview-frame-wrap">{previewUrl && <iframe key={`${version.id}:${previewReload}`} title={`项目 ${project?.title || ''} 的版本预览`} className={previewState === 'ready' ? 'ready' : ''} src={previewUrl} sandbox="allow-scripts allow-forms allow-same-origin" onLoad={event => onPreviewLoad(event.currentTarget)} onError={() => { setPreviewState('error'); setPreviewError('预览页面未能载入。') }} />}{previewState === 'loading' && <div className="preview-loading" role="status">正在载入真实应用预览…</div>}</div>}<div className="preview-data-note"><strong>数据保存</strong><span>{previewState === 'ready' ? version.manifest.entities?.length ? '本版本声明了服务端数据结构；提交后刷新应用，核对记录仍在。' : '此版本未声明服务端数据结构；请在预览内核对保存行为。' : '预览尚未载入，无法确认本次业务数据是否保存。'}</span><small>本地预览 · 非公网沙箱{previewExpires && ` · 链接有效至 ${formatTime(previewExpires)}`}</small></div></div> : <div className="code-workspace"><div className="code-files"><strong>源码文件</strong><span>{version.manifest.files.length} 个文件 · {version.manifest.template}</span>{version.manifest.files.map(file => <button className={selectedFile === file.path ? 'active' : ''} key={file.path} onClick={() => setSelectedFile(file.path)}>{file.path}</button>)}</div><div className="code-reader"><div>{selectedFile || '选择左侧文件查看源码'}</div><pre>{selectedFile ? fileContent || '正在读取文件…' : '代码已保存。选择一个源码文件查看内容。'}</pre></div></div>}
            </>}
            {rightView === 'overview' && <OverviewPanel project={project} run={run} version={version} events={events} isWaiting={!!isWaiting} isActive={!!isActive} onWorkbench={() => selectRightView('workbench')} onOpenLatest={openLatestVersion} />}
            {rightView === 'documents' && <DocumentsPanel run={run} documentRun={documentRun} version={version} tab={docTab} onTab={selectDocTab} onWorkbench={() => selectRightView('workbench')} onOpenFile={openVersionFile} />}
            {rightView === 'tests' && <TestsPanel run={run} version={version} showBuildLog={showBuildLog} buildLogLoading={buildLogLoading} buildLog={buildLog} onToggleBuildLog={toggleBuildLog} />}
            {rightView === 'publish' && <PublishPanel version={version} onTests={() => selectRightView('tests')} />}
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
  return <div className="right-content overview-page"><div className="overview-intro"><div><h4>从需求到版本，正在继续。</h4><p>当前可以继续修改应用；公开发布尚未完成。</p></div><button className="primary" onClick={onWorkbench}>返回工作台　→</button></div><div className="overview-columns"><section><h4>项目阶段</h4><div className="milestone-list">{milestones.map((item, index) => <div className="milestone" key={item.label}><span className={item.done ? 'done' : ''}>{item.done ? '✓' : index + 1}</span><div><strong>{item.label}</strong><small>{item.detail}</small></div></div>)}</div></section><section><h4>项目目标</h4><p className="overview-goal">{run?.request_text || '尚未提交需求。'}</p><h4>最新版本</h4><button className="overview-version" disabled={!latestVersion} onClick={onOpenLatest}>{latestVersion ? `#${latestVersion.id.slice(0, 8)} 已保存　→` : '尚无已保存版本'}</button><small>{latestVersion ? `构建${latestVersion.manifest.build.ok ? '通过' : '失败'} · ${formatTime(latestVersion.created_at)}` : '确认计划后开始生成'}</small><h4>下一步</h4><p>{isWaiting ? '回到对话确认当前决策卡。' : isActive ? '观察实时进度，等待生成结果。' : latestVersion ? '继续迭代，或在工作台打开真实预览。' : '在对话中提交需求。'}</p></section></div><div className="overview-activity"><strong>最近活动</strong><div>{events.slice(-3).reverse().map(item => <span key={item.event_id}>{formatTime(item.at)}　{item.type === 'phase' ? PHASE[String(item.payload.phase)] || '阶段更新' : EVENT[item.type] || item.type}</span>)}{!events.length && <span>暂无活动记录</span>}</div></div><small className="overview-project-meta">项目 {project?.id.slice(0, 8) || '—'}</small></div>
}

type DocTab = 'requirements' | 'plan' | 'decisions' | 'files'
function DocumentsPanel({ run, documentRun, version, tab, onTab, onWorkbench, onOpenFile }: { run: Run | null; documentRun: Run | null; version: Version | null; tab: DocTab; onTab: (tab: DocTab) => void; onWorkbench: () => void; onOpenFile: (path: string) => void }) {
  const tabs: { id: DocTab; label: string }[] = [{ id: 'requirements', label: '需求' }, { id: 'plan', label: '计划' }, { id: 'decisions', label: '决定' }, { id: 'files', label: '文件' }]
  const plan = documentRun?.plan
  return <div className="right-content docs-page"><p className="right-description">需求、计划与决定按规格版本保留。</p><div className="docs-tabs" role="tablist" aria-label="文档分类">{tabs.map(item => <button role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'active' : ''} key={item.id} onClick={() => onTab(item.id)}>{item.label}</button>)}</div><div className="docs-layout"><div className="docs-article">{tab === 'requirements' && <><h4>需求说明</h4><p className="docs-meta">{run ? `本轮运行 / ${formatTime(run.created_at)} / 规格 ${run.spec_version}` : '尚未创建运行'}</p><section id="doc-goal"><span>01</span><div><h5>目标</h5><p>{run?.request_text || '尚未提交需求。'}</p></div></section><section id="doc-features"><span>02</span><div><h5>核心功能</h5>{plan?.features.length ? <ul>{plan.features.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p>确认需求后会显示计划中的功能。</p>}</div></section><section id="doc-data"><span>03</span><div><h5>数据与边界</h5>{plan?.data_model.length ? <ul>{plan.data_model.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p>尚未形成数据计划。</p>}</div></section></>}{tab === 'plan' && <><h4>构建计划</h4><p className="docs-meta">{plan ? `规格 ${documentRun?.spec_version} · ${documentRun?.approved_spec_version ? '已批准' : '待确认'}` : '尚未生成计划'}</p>{plan ? <PlanView plan={plan} /> : <p>完成需求澄清后，计划会显示在这里。</p>}</>}{tab === 'decisions' && <><h4>决定记录</h4><p className="docs-meta">来自当前保存的运行状态。</p><div className="docs-decision"><strong>需求澄清</strong><span>{run?.spec_version && run.phase !== 'Clarify' ? `规格 ${run.spec_version}` : '尚未完成'}</span></div><div className="docs-decision"><strong>构建计划</strong><span>{run?.approved_spec_version ? `已批准规格 ${run.approved_spec_version}` : '尚未批准'}</span></div><p>如果需要修改已确认内容，请在工作台提交新一轮需求。</p></>}{tab === 'files' && <><h4>版本文件</h4><p className="docs-meta">{version ? `版本 #${version.id.slice(0, 8)} · ${version.manifest.files.length} 个文件` : '尚无已存版本'}</p>{version?.manifest.files.map(file => <button className="docs-file" key={file.path} onClick={() => onOpenFile(file.path)}><code>{file.path}</code><small>{file.bytes} B　→</small></button>)}{!version && <p>生成并保存版本后，文件清单会显示在这里。</p>}</>}</div><aside className="docs-toc"><strong>目录</strong>{tab === 'requirements' ? <><a href="#doc-goal">01　目标</a><a href="#doc-features">02　核心功能</a><a href="#doc-data">03　数据与边界</a></> : <span>{tabs.find(item => item.id === tab)?.label}</span>}</aside></div><div className="docs-foot"><strong>要修改已确认内容？</strong><p>在工作台提出新要求，形成新的运行与规格版本。</p><button onClick={onWorkbench}>返回工作台 →</button></div></div>
}

function TestsPanel({ run, version, showBuildLog, buildLogLoading, buildLog, onToggleBuildLog }: { run: Run | null; version: Version | null; showBuildLog: boolean; buildLogLoading: boolean; buildLog: string | null; onToggleBuildLog: () => void }) {
  const currentRunResult = run?.card?.type === 'test_result'
  const canReadLog = currentRunResult && !!run
  const build = currentRunResult ? run.card?.payload.build : version?.manifest.build
  const steps = build?.steps || []
  const passed = steps.filter(step => step.exit_code === 0).length
  const total = steps.length + 1
  return <div className="right-content tests-page"><p className="right-description">结论与证据对应当前运行或已存版本；未执行项单独列出。</p><div className="test-summary"><strong>{passed} / {total}</strong><div><h4>{steps.length ? '检查已执行' : '尚无执行记录'}</h4><p>{currentRunResult ? `本轮运行 #${run?.id.slice(0, 8)}` : version ? `版本 #${version.id.slice(0, 8)}` : '本轮尚无保存版本'} · 浏览器检查尚无执行证据</p></div></div><div className="test-bars" aria-hidden="true">{steps.map((step, i) => <span className={step.exit_code === 0 ? 'pass' : 'fail'} key={i} />)}<span className="pending" /></div><div className="test-table-head"><span>检查项</span><span>结果</span><span>证据</span></div>{steps.map((step, i) => <div className="test-row" key={i}><span className={`test-icon ${step.exit_code === 0 ? 'pass' : 'fail'}`}>{step.exit_code === 0 ? '✓' : '!'}</span><div><strong>{step.command}</strong><small>执行 {step.seconds}s · exit {step.exit_code}</small></div><span className={`test-tag ${step.exit_code === 0 ? 'pass' : 'fail'}`}>{step.exit_code === 0 ? '通过' : '失败'}</span>{canReadLog ? <button onClick={onToggleBuildLog}>{showBuildLog ? '收起日志' : '查看日志'}</button> : <span className="no-evidence">仅有步骤摘要</span>}</div>)}<div className="test-row"><span className="test-icon pending">!</span><div><strong>浏览器检查</strong><small>暂无当前版本的真实交互执行记录</small></div><span className="test-tag pending">未执行</span><span className="no-evidence">暂无证据</span></div>{canReadLog && showBuildLog && <pre className="right-log">{buildLogLoading ? '正在读取日志…' : buildLog || '没有可用日志。'}</pre>}<div className="test-explanation"><strong>结果解释</strong><p>构建通过代表代码检查通过；浏览器流程需要实际运行后才能标记完成。</p></div></div>
}

function PublishPanel({ version, onTests }: { version: Version | null; onTests: () => void }) {
  const checks = [
    { label: '代码版本', detail: version ? `#${version.id.slice(0, 8)} 已保存` : '尚无版本', done: !!version, status: version ? '已具备' : '待完成' },
    { label: '构建与类型检查', detail: version?.manifest.build.ok ? '已保存版本的构建通过' : '尚无通过记录', done: !!version?.manifest.build.ok, status: version?.manifest.build.ok ? '已具备' : '待完成' },
    { label: '浏览器验证', detail: '尚无当前版本的真实业务流程记录', done: false, status: '待完成' },
    { label: '公开环境', detail: '发布服务尚未接入', done: false, status: '不可用' },
  ]
  return <div className="right-content publish-page"><p className="right-description">检查发布条件，并只在真实上线后展示公开链接。</p><div className="publish-status"><h4>尚未发布</h4><p>当前项目还没有公开访问地址。预览可供项目内检查。</p></div><div className="publish-columns"><section><h4>发布前检查</h4>{checks.map(item => <div className="publish-check" key={item.label}><span className={`test-icon ${item.done ? 'pass' : 'pending'}`}>{item.done ? '✓' : '!'}</span><div><strong>{item.label}</strong><small>{item.detail}</small></div><b className={item.done ? 'ready' : ''}>{item.status}</b></div>)}</section><aside><h4>公开链接</h4><div className="public-link-empty"><span>↗</span><strong>尚无公开地址</strong><p>发布成功后显示真实 URL 及对应版本。</p></div></aside></div><div className="publish-next"><div><strong>下一步</strong><p>完成真实浏览器验证，并接入发布环境后再启用发布操作。</p></div><button onClick={onTests}>查看测试 →</button></div></div>
}

function PlanView({ plan }: { plan: Plan }) {
  const fieldType = { text: '文本', number: '数字', boolean: '是/否' }
  return <div className="plan-view"><div className="card-subtitle">页面与流程</div><div className="plan-pages">{plan.pages.map((page, i) => <div key={i}><strong>{page.name}</strong><span>{page.purpose}</span></div>)}</div><div className="card-subtitle">将实现</div><ul className="check-list">{plan.features.map((item, i) => <li key={i}>{item}</li>)}</ul><div className="card-subtitle">数据与验收</div><ul className="plain-list">{plan.data_model.map((item, i) => <li key={i}>{item}</li>)}</ul>{Boolean(plan.entities?.length) && <div className="entity-list" aria-label="将保存的数据结构">{plan.entities?.map(entity => <div className="entity-card" key={entity.name}><strong>{entity.name}</strong><span>服务端保存</span><ul>{entity.fields.map(field => <li key={field.name}><code>{field.name}</code><span>{fieldType[field.type] || field.type}</span>{field.required && <b>必填</b>}</li>)}</ul></div>)}</div>}<div className="acceptance">{plan.acceptance.map((item, i) => <div key={i}><span>{String(i + 1).padStart(2, '0')}</span>{item}</div>)}</div><div className="plan-template">固定模板：{plan.template}</div>{plan.limitations.length > 0 && <div className="limitations">本轮限制：{plan.limitations.join('；')}</div>}</div>
}

export default App

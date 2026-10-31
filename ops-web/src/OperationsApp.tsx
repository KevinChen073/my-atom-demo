import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ApiError,
  getException,
  listExceptions,
  type ExceptionDetail,
  type ExceptionFilters,
  type ExceptionPage,
  type ExceptionRecord,
} from './api'

const emptyFilters: ExceptionFilters = { source: '', code: '', project_id: '', trace_id: '' }

type LoadState<T> =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; value: T; readAt: Date }
  | { kind: 'error'; status: number }

function shortId(id: string | null): string {
  return id ? id.slice(0, 8).toUpperCase() : '无关联'
}

function displayTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(date)
}

function sourceLabel(source: string): string {
  return ({ agent: 'Agent', build: '构建', api: 'API' } as Record<string, string>)[source] ?? source
}

function errorMessage(status: number): string {
  if (status === 503) return '运维服务尚未配置或异常表不可用。请检查服务配置与统一数据库。'
  if (status === 422) return '筛选条件无效。请检查项目 ID、Trace ID 与错误码后重试。'
  if (status === 404) return '这条异常记录已不存在。请刷新列表。'
  return '读取失败。请检查运维服务连接后重试。'
}

function Brand() {
  return (
    <div className="brand" aria-label="MYATOM 运维">
      <span className="brand-mark" aria-hidden="true"><span /></span>
      <span className="brand-name">MYATOM</span>
      <span className="brand-divider" />
      <span className="brand-unit">OPERATIONS</span>
    </div>
  )
}

function AccessGate({ onUnlock, error }: { onUnlock: (key: string) => void; error: string }) {
  const [draft, setDraft] = useState('')
  const [isPending, setIsPending] = useState(false)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const key = draft.trim()
    if (!key) return
    setIsPending(true)
    onUnlock(key)
    setDraft('')
  }

  useEffect(() => {
    if (error) setIsPending(false)
  }, [error])

  return (
    <main className="access-layout">
      <div className="access-copy">
        <p className="eyebrow">INDEPENDENT OPERATIONS · 01</p>
        <h1>异常中心</h1>
        <p>跨项目查看终态异常，依据 Trace ID 追踪原因与运行节点。</p>
        <div className="access-boundary">
          <span className="boundary-symbol" aria-hidden="true">↗</span>
          <div><strong>独立运维入口</strong><span>仅从统一数据库读取，不连接主工作台会话。</span></div>
        </div>
      </div>
      <form className="access-form" autoComplete="off" onSubmit={submit}>
        <p className="panel-kicker">管理员验证</p>
        <h2>输入运维密钥</h2>
        <p className="form-helper">密钥仅在当前页面内存中使用，刷新后需重新输入。</p>
        <label htmlFor="operations-key">运维密钥</label>
        <input
          id="operations-key"
          type="password"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          autoComplete="new-password"
          spellCheck={false}
          autoFocus
          required
        />
        {error && <p className="field-error" role="alert">{error}</p>}
        <button className="primary-button" type="submit" disabled={isPending && !error}>
          {isPending && !error ? '正在验证…' : '进入异常中心'}
          <span aria-hidden="true">↗</span>
        </button>
      </form>
    </main>
  )
}

function Filters({
  initial,
  onApply,
}: {
  initial: ExceptionFilters
  onApply: (filters: ExceptionFilters) => void
}) {
  const [draft, setDraft] = useState(initial)

  function update(name: keyof ExceptionFilters, value: string) {
    setDraft((current) => ({ ...current, [name]: value }))
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onApply({
      source: draft.source,
      code: draft.code.trim(),
      project_id: draft.project_id.trim(),
      trace_id: draft.trace_id.trim(),
    })
  }

  function reset() {
    setDraft(emptyFilters)
    onApply(emptyFilters)
  }

  return (
    <form className="filters" onSubmit={submit} aria-label="异常筛选">
      <div className="filter-field filter-source">
        <label htmlFor="source">来源</label>
        <select id="source" value={draft.source} onChange={(event) => update('source', event.target.value)}>
          <option value="">全部来源</option>
          <option value="agent">Agent</option>
          <option value="build">构建</option>
          <option value="api">API</option>
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="code">错误码</label>
        <input id="code" type="search" placeholder="如 model_output_invalid" value={draft.code} onChange={(event) => update('code', event.target.value)} />
      </div>
      <div className="filter-field">
        <label htmlFor="project-id">项目 ID</label>
        <input id="project-id" type="search" placeholder="输入完整 ID" value={draft.project_id} onChange={(event) => update('project_id', event.target.value)} />
      </div>
      <div className="filter-field">
        <label htmlFor="trace-id">Trace ID</label>
        <input id="trace-id" type="search" placeholder="输入完整 ID" value={draft.trace_id} onChange={(event) => update('trace_id', event.target.value)} />
      </div>
      <div className="filter-actions">
        <button type="submit" className="filter-submit">应用筛选</button>
        <button type="button" className="text-button" onClick={reset}>清空</button>
      </div>
    </form>
  )
}

function RecordList({
  records,
  selectedId,
  onSelect,
}: {
  records: ExceptionRecord[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <ul className="record-list" aria-label="异常记录">
      {records.map((record) => (
        <li key={record.id}>
          <button
            type="button"
            id={`record-${record.id}`}
            className={`record-row${selectedId === record.id ? ' is-selected' : ''}`}
            onClick={() => onSelect(record.id)}
            aria-current={selectedId === record.id ? 'true' : undefined}
          >
            <span className="record-time">{displayTime(record.occurred_at)}</span>
            <span className="record-main">
              <span className="record-topline"><span className={`source-tag source-${record.source}`}>{sourceLabel(record.source)}</span><strong>{record.reason}</strong></span>
              <span className="record-meta"><span>{record.phase}</span><span className="mono">{record.code}</span></span>
            </span>
            <span className="record-links"><span>项目 <code>{shortId(record.project_id)}</code></span><span>Run <code>{shortId(record.run_id)}</code></span><span>Trace <code>{shortId(record.trace_id)}</code></span></span>
            <span className="row-arrow" aria-hidden="true">↗</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

function Detail({
  state,
  onClose,
  onRetry,
}: {
  state: LoadState<ExceptionDetail>
  onClose: () => void
  onRetry: () => void
}) {
  const titleRef = useRef<HTMLHeadingElement>(null)
  const [copyFeedback, setCopyFeedback] = useState('')
  const detailId = state.kind === 'ready' ? state.value.exception.id : null

  useEffect(() => {
    if (state.kind === 'ready') titleRef.current?.focus()
    setCopyFeedback('')
  }, [detailId, state.kind])

  async function copyTrace(traceId: string) {
    try {
      await navigator.clipboard.writeText(traceId)
      setCopyFeedback('Trace ID 已复制')
    } catch {
      setCopyFeedback('复制失败，请手动选择 Trace ID')
    }
  }

  return (
    <aside className="detail" aria-label="异常详情">
      <div className="detail-header">
        <div><p className="panel-kicker">RECORD DETAIL</p><h2 ref={titleRef} tabIndex={-1}>异常详情</h2></div>
        <button type="button" className="icon-button" aria-label="关闭异常详情" onClick={onClose}>×</button>
      </div>
      {state.kind === 'loading' && <div className="detail-status" role="status">正在读取详情…</div>}
      {state.kind === 'error' && <div className="detail-status" role="alert"><p>{errorMessage(state.status)}</p><button type="button" className="secondary-button" onClick={onRetry}>重试</button></div>}
      {state.kind === 'ready' && <>
        <div className="detail-summary">
          <span className={`source-tag source-${state.value.exception.source}`}>{sourceLabel(state.value.exception.source)}</span>
          <p>{state.value.exception.reason}</p>
          <time dateTime={state.value.exception.occurred_at}>{displayTime(state.value.exception.occurred_at)}</time>
        </div>
        <div className="trace-block">
          <div className="trace-heading"><h3>Trace ID</h3><button type="button" className="text-button" onClick={() => copyTrace(state.value.exception.trace_id)}>复制</button></div>
          <code>{state.value.exception.trace_id}</code>
          <p className="copy-feedback" role="status" aria-live="polite">{copyFeedback}</p>
        </div>
        <dl className="detail-fields">
          <div><dt>异常 ID</dt><dd className="mono">{state.value.exception.id}</dd></div>
          <div><dt>错误码</dt><dd className="mono">{state.value.exception.code}</dd></div>
          <div><dt>异常类型</dt><dd className="mono">{state.value.exception.exception_type}</dd></div>
          <div><dt>阶段</dt><dd>{state.value.exception.phase}</dd></div>
          <div><dt>严重程度</dt><dd>{state.value.exception.severity === 'error' ? '错误' : state.value.exception.severity}</dd></div>
          <div><dt>项目 ID</dt><dd className="mono">{state.value.exception.project_id ?? '无关联'}</dd></div>
          <div><dt>Run ID</dt><dd className="mono">{state.value.exception.run_id ?? '无关联'}</dd></div>
        </dl>
        <section className="timeline" aria-labelledby="timeline-heading">
          <div className="section-heading"><h3 id="timeline-heading">关联事件</h3><span>最多 30 条</span></div>
          {state.value.timeline.length === 0 ? <p className="timeline-empty">没有可展示的事件记录。</p> : <ol>
            {state.value.timeline.map((event) => <li key={event.seq}><span className="timeline-node" aria-hidden="true" /><span className="timeline-event"><strong>{event.type}</strong><small>序号 {event.seq}</small></span><time dateTime={event.at}>{displayTime(event.at)}</time></li>)}
          </ol>}
        </section>
      </>}
    </aside>
  )
}

export function OperationsApp() {
  const [key, setKey] = useState<string | null>(null)
  const [accessError, setAccessError] = useState('')
  const [filters, setFilters] = useState<ExceptionFilters>(emptyFilters)
  const [cursors, setCursors] = useState<(string | null)[]>([null])
  const [pageIndex, setPageIndex] = useState(0)
  const [listState, setListState] = useState<LoadState<ExceptionPage>>({ kind: 'idle' })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailState, setDetailState] = useState<LoadState<ExceptionDetail>>({ kind: 'idle' })
  const [refresh, setRefresh] = useState(0)
  const [detailRefresh, setDetailRefresh] = useState(0)
  const cursor = cursors[pageIndex] ?? null

  function lock(message = '') {
    setKey(null)
    setAccessError(message)
    setListState({ kind: 'idle' })
    setDetailState({ kind: 'idle' })
    setSelectedId(null)
    setFilters(emptyFilters)
    setCursors([null])
    setPageIndex(0)
  }

  useEffect(() => {
    if (!key) return
    const controller = new AbortController()
    setListState({ kind: 'loading' })
    listExceptions(key, filters, cursor, controller.signal)
      .then((value) => setListState({ kind: 'ready', value, readAt: new Date() }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 401) {
          lock('密钥无效或已失效，请重新输入。')
          return
        }
        setListState({ kind: 'error', status: error instanceof ApiError ? error.status : 0 })
      })
    return () => controller.abort()
  }, [key, filters, cursor, refresh])

  useEffect(() => {
    if (!key || !selectedId) return
    const controller = new AbortController()
    setDetailState({ kind: 'loading' })
    getException(key, selectedId, controller.signal)
      .then((value) => setDetailState({ kind: 'ready', value, readAt: new Date() }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 401) {
          lock('密钥无效或已失效，请重新输入。')
          return
        }
        setDetailState({ kind: 'error', status: error instanceof ApiError ? error.status : 0 })
      })
    return () => controller.abort()
  }, [key, selectedId, detailRefresh])

  function applyFilters(next: ExceptionFilters) {
    setFilters(next)
    setCursors([null])
    setPageIndex(0)
    setSelectedId(null)
    setDetailState({ kind: 'idle' })
  }

  function nextPage(nextCursor: string) {
    setCursors((current) => [...current.slice(0, pageIndex + 1), nextCursor])
    setPageIndex(pageIndex + 1)
    setSelectedId(null)
    setDetailState({ kind: 'idle' })
  }

  return (
    <div className="app-shell">
      <header className="topbar"><Brand /><span className="topbar-context">独立运维服务 <span className="context-dot" aria-hidden="true" /> 只读数据库</span></header>
      {!key ? <AccessGate key={accessError} error={accessError} onUnlock={(input) => { setAccessError(''); setKey(input) }} /> : <main className="console-layout">
        <div className="page-heading">
          <div><p className="eyebrow">SYSTEM OBSERVABILITY / EXCEPTIONS</p><h1>异常中心</h1><p>跨项目终态异常记录。选择记录查看安全摘要与关联事件。</p></div>
          <div className="heading-actions"><span className="read-only-badge"><span aria-hidden="true">◉</span>只读模式</span><button type="button" className="text-button" onClick={() => lock()}>退出运维</button></div>
        </div>
        <Filters initial={filters} onApply={applyFilters} />
        <div className={`content-grid${selectedId ? ' has-detail' : ''}`}>
          <section className="list-panel" aria-labelledby="records-heading">
            <div className="list-header"><div><p className="panel-kicker">EXCEPTION RECORDS</p><h2 id="records-heading">异常记录</h2></div><div className="list-header-right">{listState.kind === 'ready' && <span>最近读取 {displayTime(listState.readAt.toISOString())}</span>}<button type="button" className="secondary-button" onClick={() => setRefresh((value) => value + 1)} disabled={listState.kind === 'loading'}>刷新</button></div></div>
            {listState.kind === 'loading' && <div className="list-status" role="status" aria-busy="true"><span className="loading-line" /><span className="loading-line" /><span className="loading-line" /><p>正在读取异常记录…</p></div>}
            {listState.kind === 'error' && <div className="list-status error-status" role="alert"><span className="status-symbol" aria-hidden="true">!</span><h3>读取失败</h3><p>{errorMessage(listState.status)}</p><button type="button" className="secondary-button" onClick={() => setRefresh((value) => value + 1)}>重试读取</button></div>}
            {listState.kind === 'ready' && listState.value.items.length === 0 && <div className="list-status empty-status" role="status"><span className="status-symbol" aria-hidden="true">◇</span><h3>{Object.values(filters).some(Boolean) ? '没有匹配的异常' : '暂无异常记录'}</h3><p>{Object.values(filters).some(Boolean) ? '调整筛选条件后重新查询。' : '统一数据库当前没有终态异常记录。'}</p></div>}
            {listState.kind === 'ready' && listState.value.items.length > 0 && <RecordList records={listState.value.items} selectedId={selectedId} onSelect={setSelectedId} />}
            {listState.kind === 'ready' && (pageIndex > 0 || listState.value.next_cursor) && <div className="pagination"><span>第 {pageIndex + 1} 页 · 本页 {listState.value.items.length} 条</span><div><button type="button" className="secondary-button" disabled={pageIndex === 0} onClick={() => { setPageIndex((value) => value - 1); setSelectedId(null) }}>上一页</button><button type="button" className="secondary-button" disabled={!listState.value.next_cursor} onClick={() => { if (listState.value.next_cursor) nextPage(listState.value.next_cursor) }}>下一页</button></div></div>}
          </section>
          {selectedId && <Detail state={detailState} onClose={() => { document.getElementById(`record-${selectedId}`)?.focus(); setSelectedId(null); setDetailState({ kind: 'idle' }) }} onRetry={() => setDetailRefresh((value) => value + 1)} />}
        </div>
        <footer className="page-footer"><span>MYATOM OPERATIONS</span><span>异常摘要仅含安全字段 · Trace ID 仅用于关联排查</span></footer>
      </main>}
    </div>
  )
}

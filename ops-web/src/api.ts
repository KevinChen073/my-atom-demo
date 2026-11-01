export type ExceptionRecord = {
  id: string
  trace_id: string
  project_id: string | null
  run_id: string | null
  source: 'agent' | 'build' | 'api'
  phase: string
  code: string
  exception_type: string
  reason: string
  severity: string
  occurred_at: string
}

export type TimelineEvent = { type: string; at: string; seq: number }
export type ExceptionPage = { items: ExceptionRecord[]; next_cursor: string | null }
export type RunMetrics = {
  created_at: string
  elapsed_seconds: number | null
  active_seconds: number | null
  model_calls: number
  tokens_used: number
}
export type BuildCheck = {
  attempt: number; outcome: 'passed' | 'failed'; category: string; command: string
  exit_code: number | null; duration_seconds: number | null; fix_round: number
  model_calls: number | null; tokens_used: number | null; fingerprints: string[]
  target_files: string[]; error_codes: string[]; stop_code: string; occurred_at: string
}
export type ExceptionDetail = { exception: ExceptionRecord; timeline: TimelineEvent[]; run_metrics: RunMetrics | null; build_checks: BuildCheck[] }

export type ExceptionFilters = {
  source: string
  code: string
  project_id: string
  trace_id: string
}

export class ApiError extends Error {
  constructor(readonly status: number) {
    super('Exception console request failed')
  }
}

async function request<T>(path: string, key: string, signal?: AbortSignal): Promise<T> {
  const integrated = window.location.pathname.startsWith('/ops')
  const response = await fetch(path, {
    method: 'GET',
    headers: integrated ? {} : { 'X-Operations-Key': key },
    cache: 'no-store',
    credentials: integrated ? 'same-origin' : 'omit',
    signal,
  })
  if (!response.ok) throw new ApiError(response.status)
  return response.json() as Promise<T>
}

export function listExceptions(
  key: string,
  filters: ExceptionFilters,
  cursor: string | null,
  signal?: AbortSignal,
): Promise<ExceptionPage> {
  const params = new URLSearchParams({ limit: '30' })
  if (cursor) params.set('cursor', cursor)
  for (const [name, value] of Object.entries(filters)) {
    const trimmed = value.trim()
    if (trimmed) params.set(name, trimmed)
  }
  return request<ExceptionPage>(`/api/ops/exceptions?${params.toString()}`, key, signal)
}

export function getException(key: string, id: string, signal?: AbortSignal): Promise<ExceptionDetail> {
  return request<ExceptionDetail>(`/api/ops/exceptions/${encodeURIComponent(id)}`, key, signal)
}
